import math
import mimetypes
import os
import random
from datetime import timedelta
from typing import Optional

import jwt
from celery.result import AsyncResult
from django.contrib.auth import authenticate
from django.contrib.auth.models import Group, User
from django.db import models as db_models, transaction
from django.db.models import Avg, Count, Q
from django.utils import timezone
from django.http import FileResponse
from ninja import NinjaAPI, UploadedFile, File
from ninja.errors import HttpError

from .auth import api_auth, create_token, decode_token
from .cache import (
    cache_get,
    cache_set,
    course_detail_cache_key,
    course_list_cache_key,
    dashboard_cache_key,
    invalidate_course_cache,
    invalidate_dashboard_cache,
)
from .models import (
    Category, Course, CourseMember, CourseContent, CourseReview,
    CourseSection, CoursePublishRequest, CoursePrerequisite,
    LessonProgress, Wishlist, Quiz, QuizQuestion, QuizAttempt, QuizAttemptAnswer,
)
from .mongo import get_activity_report, get_learning_report, log_activity, log_learning_activity
from .permissions import require_admin, require_instructor, require_student, is_admin, user_roles
from .rate_limit import rate_limit, rate_limit_login
from .schemas import (
    AccessTokenOut,
    CategoryIn,
    CategoryOut,
    CategoryUpdateIn,
    ContentIn,
    ContentOut,
    ContentUpdateIn,
    CourseIn,
    CourseOut,
    CourseUpdateIn,
    DashboardCourseOut,
    EnrollmentIn,
    EnrollmentOut,
    EnrollmentProgressDetailOut,
    ErrorOut,
    FileUploadOut,
    LessonProgressItemOut,
    LoginIn,
    MessageOut,
    PaginatedCategoryOut,
    PaginatedContentOut,
    PaginatedCourseOut,
    PaginatedEnrollmentOut,
    PaginatedWishlistOut,
    PrerequisiteIn,
    PrerequisiteOut,
    ProgressIn,
    ProgressOut,
    PublishRequestOut,
    PublishReviewIn,
    RecommendedCourseOut,
    RefreshIn,
    RegisterIn,
    ReviewIn,
    ReviewListOut,
    ReviewOut,
    SectionIn,
    SectionOut,
    SectionUpdateIn,
    SectionWithLessonsOut,
    StudentDashboardOut,
    TaskOut,
    TaskStatusOut,
    TokenOut,
    UserOut,
    UserUpdateIn,
    WishlistDashboardOut,
    WishlistIn,
    WishlistOut,
    ChatbotIn,
    ChatbotOut,
    QuizIn,
    QuizOut,
    QuizUpdateIn,
    QuizQuestionIn,
    QuizQuestionOut,
    QuizQuestionBankOut,
    QuizQuestionUpdateIn,
    QuizAttemptStartOut,
    QuizSubmitIn,
    QuizAttemptResultOut,
    LearningMapOut,
)
from .tasks import (
    export_course_report,
    fetch_course_data,
    format_report,
    generate_certificate,
    generate_course_report,
    run_bulk_reports,
    run_course_report_chain,
    save_report,
    send_enrollment_email,
    send_welcome_email,
    update_course_statistics as update_course_statistics_task,
)

api = NinjaAPI(
    title="Simple LMS API",
    version="1.0.0",
    description="REST API Simple LMS dengan JWT, Redis caching, MongoDB logs, Celery, RabbitMQ, dan rate limiting",
    docs_url="/docs",
)


# HELPER

def get_object_or_404(model, **kwargs):
    if hasattr(model, 'objects'):
        obj = model.objects.filter(**kwargs).first()
    else:
        obj = model.filter(**kwargs).first()
    if obj is None:
        model_name = getattr(model, '__name__', 'Data')
        raise HttpError(404, f"{model_name} tidak ditemukan")
    return obj


# ── ORDERING HELPERS ──────────────────────────────────────────────────────────

def _next_section_order(course_id: int) -> int:
    from django.db.models import Max
    agg = CourseSection.objects.filter(course_id=course_id).aggregate(Max("order"))
    return (agg["order__max"] or 0) + 1


def _next_content_order(course_id: int, section_id=None) -> int:
    from django.db.models import Max
    qs = CourseContent.objects.filter(course_id=course_id, section_id=section_id)
    agg = qs.aggregate(Max("order"))
    return (agg["order__max"] or 0) + 1


def _validate_content_order(course_id: int, section_id, order: int, exclude_id=None):
    qs = CourseContent.objects.filter(
        course_id=course_id, section_id=section_id, order=order
    )
    if exclude_id is not None:
        qs = qs.exclude(id=exclude_id)
    if qs.exists():
        scope = f"section {section_id}" if section_id else "tanpa section"
        raise HttpError(
            409,
            f"order={order} sudah digunakan lesson lain dalam {scope} di course ini. "
            "Pilih order lain atau kirim tanpa field order agar otomatis ditetapkan."
        )


def _validate_section_order(course_id: int, order: int, exclude_id=None):
    qs = CourseSection.objects.filter(course_id=course_id, order=order)
    if exclude_id is not None:
        qs = qs.exclude(id=exclude_id)
    if qs.exists():
        raise HttpError(
            409,
            f"order={order} sudah digunakan section lain dalam course ini. "
            "Pilih order lain atau kirim tanpa field order agar otomatis ditetapkan."
        )


def _validate_positive_order(order):
    """Tolak order yang bukan integer positif."""
    if order is not None and order < 1:
        raise HttpError(400, "order harus bernilai positif (>= 1)")


def _validate_positive_duration(duration):
    """Tolak duration_minutes yang negatif atau nol."""
    if duration is not None and duration < 1:
        raise HttpError(400, "duration_minutes harus bernilai positif (>= 1)")


def serialize_user(user: User):
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "roles": user_roles(user),
    }


def serialize_course(course: Course):
    cat = course.category
    return {
        "id": course.id,
        "name": course.name,
        "description": course.description,
        "price": course.price,
        "level": course.level,
        "status": course.status,
        "rating_avg": course.rating_avg,
        "total_reviews": course.total_reviews,
        "image": course.image.url if course.image else None,
        "category": serialize_category(cat) if cat else None,
        "teacher": {
            "id": course.teacher.id,
            "username": course.teacher.username,
            "first_name": course.teacher.first_name,
            "last_name": course.teacher.last_name,
            "email": course.teacher.email,
        },
        "created_at": course.created_at,
        "updated_at": course.updated_at,
    }


def serialize_enrollment(member: CourseMember):
    return {
        "id": member.id,
        "course_id": member.course_id.id,
        "course_name": member.course_id.name,
        "user_id": member.user_id.id,
        "username": member.user_id.username,
        "roles": member.roles,
    }


def serialize_content(content: CourseContent):
    return {
        "id": content.id,
        "name": content.name,
        "description": content.description,
        "subject": content.subject,
        "body": content.body,
        "video_url": content.video_url,
        "file_attachment": (
            content.file_attachment.url if content.file_attachment else None
        ),
        "course_id": content.course_id_id,
        "parent_id": content.parent_id_id,
        "section_id": content.section_id,
        "order": content.order,
        "duration_minutes": content.duration_minutes,
    }


def serialize_category(category: Category):
    return {
        "id": category.id,
        "name": category.name,
        "description": category.description,
        "slug": category.slug,
    }


def is_course_owner_or_admin(user: User, course: Course) -> bool:
    return course.teacher_id == user.id or is_admin(user)


# 1. AUTHENTICATION ENDPOINTS

@api.post("/auth/register", response={201: UserOut, 400: ErrorOut}, tags=["Authentication"])
def register(request, data: RegisterIn):
    if User.objects.filter(username=data.username).exists():
        raise HttpError(400, "Username sudah digunakan")

    if User.objects.filter(email=data.email).exists():
        raise HttpError(400, "Email sudah digunakan")

    user = User.objects.create_user(
        username=data.username,
        password=data.password,
        email=data.email,
        first_name=data.first_name,
        last_name=data.last_name,
    )
    student_group, _ = Group.objects.get_or_create(name="Student")
    user.groups.add(student_group)

    log_activity(user, "register", {"email": user.email})

    # Kirim welcome email di background agar response user tidak terlambat
    send_welcome_email.delay(user.id)

    return 201, serialize_user(user)


@api.post("/auth/login", response={200: TokenOut, 401: ErrorOut, 429: ErrorOut}, tags=["Authentication"])
@rate_limit_login()
def login(request, data: LoginIn):
    user = authenticate(username=data.username, password=data.password)
    if user is None:
        raise HttpError(401, "Username atau password salah")

    log_activity(user, "login", {})
    return {
        "access": create_token(user, "access"),
        "refresh": create_token(user, "refresh"),
    }


@api.post("/auth/refresh", response={200: AccessTokenOut, 401: ErrorOut}, tags=["Authentication"])
def refresh_token(request, data: RefreshIn):
    try:
        payload = decode_token(data.refresh)
        if payload.get("token_type") != "refresh":
            raise HttpError(401, "Token bukan refresh token")

        user = User.objects.filter(id=payload.get("user_id")).first()
        if user is None:
            raise HttpError(401, "User tidak ditemukan")

        log_activity(user, "refresh_token", {})
        return {"access": create_token(user, "access")}
    except jwt.ExpiredSignatureError:
        raise HttpError(401, "Refresh token sudah expired")
    except jwt.InvalidTokenError:
        raise HttpError(401, "Refresh token tidak valid")


@api.get("/auth/me", auth=api_auth, response={200: UserOut, 401: ErrorOut}, tags=["Authentication"])
def get_me(request):
    log_activity(request.user, "view_profile", {})
    return serialize_user(request.user)


@api.put("/auth/me", auth=api_auth, response={200: UserOut, 400: ErrorOut, 401: ErrorOut}, tags=["Authentication"])
def update_me(request, data: UserUpdateIn):
    user = request.user

    if data.email is not None:
        if User.objects.exclude(id=user.id).filter(email=data.email).exists():
            raise HttpError(400, "Email sudah digunakan user lain")
        user.email = data.email

    if data.first_name is not None:
        user.first_name = data.first_name
    if data.last_name is not None:
        user.last_name = data.last_name

    user.save()
    log_activity(user, "update_profile", {})
    return serialize_user(user)


# 2. COURSES PUBLIC ENDPOINTS + REDIS CACHE + RATE LIMIT

@api.get("/courses", response={200: PaginatedCourseOut, 429: ErrorOut}, tags=["Courses"])
@rate_limit(prefix="courses")
def list_courses(
    request,
    search: Optional[str] = None,
    category_id: Optional[int] = None,
    instructor_id: Optional[int] = None,
    level: Optional[str] = None,
    status: Optional[str] = None,
    min_price: Optional[int] = None,
    max_price: Optional[int] = None,
    ordering: str = "-created_at",
    page: int = 1,
    page_size: int = 10,
):
    allowed_ordering = {"name", "-name", "price", "-price", "created_at", "-created_at", "rating_avg", "-rating_avg"}
    if ordering not in allowed_ordering:
        raise HttpError(400, "Parameter ordering tidak valid")

    allowed_levels = {"beginner", "intermediate", "advanced", None}
    if level not in allowed_levels:
        raise HttpError(400, "Level tidak valid. Pilih: beginner, intermediate, advanced")

    allowed_statuses = {"draft", "pending_review", "published", "archived", None}
    if status not in allowed_statuses:
        raise HttpError(400, "Status tidak valid. Pilih: draft, pending_review, published, archived")

    page = max(page, 1)
    page_size = max(min(page_size, 100), 1)
    cache_key = course_list_cache_key(
        search, min_price, max_price, ordering, page, page_size,
        category_id=category_id, level=level, status=status, instructor_id=instructor_id,
    )
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    qs = Course.objects.select_related("teacher", "category").all()
    if search:
        qs = qs.filter(Q(name__icontains=search) | Q(description__icontains=search))
    if instructor_id is not None:
        qs = qs.filter(teacher_id=instructor_id)
    if category_id is not None:
        qs = qs.filter(category_id=category_id)
    if level:
        qs = qs.filter(level=level)
    if status:
        qs = qs.filter(status=status)
    if min_price is not None:
        qs = qs.filter(price__gte=min_price)
    if max_price is not None:
        qs = qs.filter(price__lte=max_price)

    qs = qs.order_by(ordering)
    total = qs.count()
    start = (page - 1) * page_size
    end = start + page_size

    response = {
        "total": total,
        "page": page,
        "page_size": page_size,
        "data": [serialize_course(course) for course in qs[start:end]],
    }
    cache_set(cache_key, response, timeout=300)
    return response


@api.get("/courses/{course_id}", response={200: CourseOut, 404: ErrorOut}, tags=["Courses"])
def detail_course(request, course_id: int):
    cache_key = course_detail_cache_key(course_id)
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    course = get_object_or_404(
        Course.objects.select_related("teacher", "category"), id=course_id
    )
    response = serialize_course(course)
    cache_set(cache_key, response, timeout=300)
    log_activity(getattr(request, 'user', None), "view_course_detail", {"course_id": course_id})
    return response


# 3. COURSES PROTECTED ENDPOINTS

@api.post("/courses", auth=api_auth, response={201: CourseOut, 400: ErrorOut, 401: ErrorOut, 403: ErrorOut}, tags=["Courses"])
@require_instructor
def create_course(request, data: CourseIn):
    if data.price < 0:
        raise HttpError(400, "Harga tidak boleh negatif")

    allowed_levels = {"beginner", "intermediate", "advanced"}
    if data.level not in allowed_levels:
        raise HttpError(400, "Level tidak valid")

    # Instructor hanya boleh membuat course dengan status draft atau archived
    # Status published hanya bisa dicapai lewat alur review admin
    allowed_statuses_instructor = {"draft", "archived"}
    if data.status not in allowed_statuses_instructor | {"published"} and not is_admin(request.user):
        raise HttpError(400, "Status tidak valid")
    if data.status == "published" and not is_admin(request.user):
        raise HttpError(403, "Instructor tidak boleh langsung mempublikasikan course. Gunakan endpoint submit-for-review.")
    if data.status == "pending_review":
        raise HttpError(400, "Status pending_review tidak bisa diset secara manual")

    # Default ke draft jika tidak diberikan
    status = data.status if data.status in {"draft", "archived"} else "draft"
    if is_admin(request.user) and data.status in {"draft", "published", "archived"}:
        status = data.status

    category = None
    if data.category_id is not None:
        category = get_object_or_404(Category, id=data.category_id)

    course = Course.objects.create(
        name=data.name,
        description=data.description,
        price=data.price,
        image=data.image or "",
        teacher=request.user,
        category=category,
        level=data.level,
        status=status,
    )
    invalidate_course_cache(course.id)
    log_activity(request.user, "create_course", {"course_id": course.id})
    return 201, serialize_course(course)


@api.patch("/courses/{course_id}", auth=api_auth, response={200: CourseOut, 400: ErrorOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut}, tags=["Courses"])
def update_course(request, course_id: int, data: CourseUpdateIn):
    course = get_object_or_404(
        Course.objects.select_related("teacher", "category"), id=course_id
    )
    if not is_course_owner_or_admin(request.user, course):
        raise HttpError(403, "Hanya owner course atau admin yang boleh mengedit course")

    provided_fields = (
        getattr(data, "model_fields_set", None)
        or getattr(data, "__fields_set__", set())
        or set()
    )

    # Cek apakah ada field konten yang diubah (bukan status).
    # Pakai provided_fields agar PATCH category_id=null tetap dianggap request valid
    # untuk mengosongkan kategori course menjadi "Tanpa kategori".
    content_fields_changed = bool({
        "name", "description", "price", "image", "category_id", "level"
    } & set(provided_fields))

    if data.name is not None:
        course.name = data.name
    if data.description is not None:
        course.description = data.description
    if data.price is not None:
        if data.price < 0:
            raise HttpError(400, "Harga tidak boleh negatif")
        course.price = data.price
    if data.image is not None:
        course.image = data.image
    if "category_id" in provided_fields:
        course.category = get_object_or_404(Category, id=data.category_id) if data.category_id is not None else None
    if data.level is not None:
        allowed_levels = {"beginner", "intermediate", "advanced"}
        if data.level not in allowed_levels:
            raise HttpError(400, "Level tidak valid")
        course.level = data.level

    if data.status is not None:
        # Admin bisa set status apapun secara langsung
        if is_admin(request.user):
            allowed_statuses = {"draft", "pending_review", "published", "archived"}
            if data.status not in allowed_statuses:
                raise HttpError(400, "Status tidak valid")
            course.status = data.status
        else:
            # Instructor hanya boleh mengubah ke draft atau archived
            # (published hanya lewat endpoint submit-for-review → approve)
            allowed_statuses_instructor = {"draft", "archived"}
            if data.status not in allowed_statuses_instructor:
                raise HttpError(403, "Instructor tidak bisa langsung mengubah status ke '" + data.status + "'. "
                                     "Gunakan endpoint submit-for-review untuk publish.")
            course.status = data.status
    else:
        # Jika instructor mengedit konten sebuah course yang sudah published,
        # status otomatis dikembalikan ke draft agar perlu review ulang
        if content_fields_changed and course.status == "published" and not is_admin(request.user):
            course.status = "draft"

    course.save()
    invalidate_course_cache(course.id)
    log_activity(request.user, "update_course", {"course_id": course.id})
    return serialize_course(course)


@api.delete("/courses/{course_id}", auth=api_auth, response={200: MessageOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut}, tags=["Courses"])
def delete_course(request, course_id: int):
    course = get_object_or_404(Course, id=course_id)
    if not is_course_owner_or_admin(request.user, course):
        raise HttpError(403, "Hanya owner course atau admin yang boleh menghapus course")

    course.delete()
    invalidate_course_cache(course_id)
    log_activity(request.user, "delete_course", {"course_id": course_id})
    return {"message": "Course berhasil dihapus"}


# 3.2 CATEGORY ENDPOINTS

@api.get(
    "/categories",
    response={200: PaginatedCategoryOut},
    tags=["Categories"],
    summary="List semua kategori",
)
def list_categories(request, page: int = 1, page_size: int = 20):
    page = max(page, 1)
    page_size = max(min(page_size, 100), 1)
    qs = Category.objects.all()
    total = qs.count()
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "data": [serialize_category(c) for c in qs[start:end]],
    }


@api.get(
    "/categories/{category_id}",
    response={200: CategoryOut, 404: ErrorOut},
    tags=["Categories"],
    summary="Detail satu kategori beserta jumlah course di dalamnya",
)
def detail_category(request, category_id: int):
    category = get_object_or_404(Category, id=category_id)
    return serialize_category(category)


@api.post(
    "/categories",
    auth=api_auth,
    response={201: CategoryOut, 400: ErrorOut, 401: ErrorOut, 403: ErrorOut},
    tags=["Categories"],
    summary="Buat kategori baru (Admin only)",
)
def create_category(request, data: CategoryIn):
    if not is_admin(request.user):
        raise HttpError(403, "Hanya admin yang boleh membuat kategori")

    if Category.objects.filter(name=data.name).exists():
        raise HttpError(400, "Nama kategori sudah digunakan")

    category = Category(
        name=data.name,
        description=data.description,
        slug=data.slug or "",
    )
    category.save()  # save() akan auto-generate slug jika kosong
    log_activity(request.user, "create_category", {"category_id": category.id})
    return 201, serialize_category(category)


@api.patch(
    "/categories/{category_id}",
    auth=api_auth,
    response={200: CategoryOut, 400: ErrorOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    tags=["Categories"],
    summary="Update kategori (Admin only)",
)
def update_category(request, category_id: int, data: CategoryUpdateIn):
    if not is_admin(request.user):
        raise HttpError(403, "Hanya admin yang boleh mengubah kategori")

    category = get_object_or_404(Category, id=category_id)

    if data.name is not None:
        if Category.objects.exclude(id=category_id).filter(name=data.name).exists():
            raise HttpError(400, "Nama kategori sudah digunakan")
        category.name = data.name
        # Reset slug agar di-generate ulang dari nama baru
        category.slug = ""
    if data.description is not None:
        category.description = data.description
    if data.slug is not None and data.slug != "":
        category.slug = data.slug

    category.save()
    log_activity(request.user, "update_category", {"category_id": category.id})
    return serialize_category(category)


@api.delete(
    "/categories/{category_id}",
    auth=api_auth,
    response={200: MessageOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    tags=["Categories"],
    summary="Hapus kategori (Admin only)",
)
def delete_category(request, category_id: int):
    if not is_admin(request.user):
        raise HttpError(403, "Hanya admin yang boleh menghapus kategori")

    category = get_object_or_404(Category, id=category_id)
    name = category.name
    category.delete()  # Course yang punya category ini → category jadi NULL (SET_NULL)
    log_activity(request.user, "delete_category", {"category_id": category_id, "name": name})
    return {"message": f"Kategori '{name}' berhasil dihapus"}


@api.get(
    "/categories/{category_id}/courses",
    response={200: PaginatedCourseOut, 404: ErrorOut},
    tags=["Categories"],
    summary="List semua course dalam suatu kategori",
)
def list_courses_by_category(request, category_id: int, page: int = 1, page_size: int = 10):
    category = get_object_or_404(Category, id=category_id)
    page = max(page, 1)
    page_size = max(min(page_size, 100), 1)
    qs = Course.objects.select_related("teacher", "category").filter(category=category)
    total = qs.count()
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "data": [serialize_course(c) for c in qs[start:end]],
    }


@api.get(
    "/courses/{course_id}/contents",
    response={200: PaginatedContentOut, 404: ErrorOut},
    tags=["Contents"],
    summary="List semua lesson dalam sebuah course",
)
def list_contents(request, course_id: int, page: int = 1, page_size: int = 10):
    course = get_object_or_404(Course, id=course_id)
    page = max(page, 1)
    page_size = max(min(page_size, 100), 1)

    qs = (
        CourseContent.objects
        .filter(course_id=course)
        .select_related("section")
        .order_by(
            # Prioritas: section.order (NULL terakhir), lalu order dalam section, lalu id
            db_models.F("section__order").asc(nulls_last=True),
            db_models.F("section_id").asc(nulls_last=True),
            "order",
            "id",
        )
    )
    total = qs.count()
    start = (page - 1) * page_size
    end = start + page_size

    log_activity(
        getattr(request, "user", None),
        "list_contents",
        {"course_id": course_id},
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "data": [serialize_content(c) for c in qs[start:end]],
    }


@api.get(
    "/courses/{course_id}/contents/{content_id}",
    response={200: ContentOut, 404: ErrorOut},
    tags=["Contents"],
    summary="Detail satu lesson",
)
def detail_content(request, course_id: int, content_id: int):
    course = get_object_or_404(Course, id=course_id)
    content = get_object_or_404(CourseContent, id=content_id, course_id=course)
    log_activity(
        getattr(request, "user", None),
        "view_content_detail",
        {"course_id": course_id, "content_id": content_id},
    )
    return serialize_content(content)


@api.post(
    "/courses/{course_id}/contents",
    auth=api_auth,
    response={201: ContentOut, 400: ErrorOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    tags=["Contents"],
    summary="Tambah lesson baru ke course (Instructor/Admin)",
)
def create_content(request, course_id: int, data: ContentIn):
    course = Course.objects.select_related("teacher").filter(id=course_id).first()
    if course is None:
        raise HttpError(404, "Course tidak ditemukan")
    if not is_course_owner_or_admin(request.user, course):
        raise HttpError(403, "Hanya owner course atau admin yang boleh menambahkan konten")

    # Validasi parent_id jika diberikan (untuk konten bersarang)
    parent = None
    if data.parent_id is not None:
        if data.parent_id == 0:
            raise HttpError(400, "parent_id tidak valid")
        parent = get_object_or_404(CourseContent, id=data.parent_id, course_id=course)

    # Validasi section_id jika diberikan
    section = None
    if data.section_id is not None:
        section = get_object_or_404(CourseSection, id=data.section_id, course=course)

    section_id_for_scope = section.id if section else None

    # Validasi positif
    _validate_positive_order(data.order)
    _validate_positive_duration(data.duration_minutes)

    # Auto-assign order jika tidak dikirim, atau validasi jika dikirim manual
    if data.order is None:
        order = _next_content_order(course.id, section_id_for_scope)
    else:
        _validate_content_order(course.id, section_id_for_scope, data.order)
        order = data.order

    content = CourseContent.objects.create(
        name=data.name,
        description=data.description,
        subject=data.subject,
        body=data.body,
        video_url=data.video_url,
        course_id=course,
        parent_id=parent,
        section=section,
        order=order,
        duration_minutes=data.duration_minutes,
    )
    invalidate_course_cache(course.id)
    log_activity(
        request.user,
        "create_content",
        {"course_id": course.id, "content_id": content.id},
    )
    return 201, serialize_content(content)


@api.patch(
    "/courses/{course_id}/contents/{content_id}",
    auth=api_auth,
    response={200: ContentOut, 400: ErrorOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    tags=["Contents"],
    summary="Update lesson (Instructor/Admin)",
)
def update_content(request, course_id: int, content_id: int, data: ContentUpdateIn):
    course = Course.objects.select_related("teacher").filter(id=course_id).first()
    if course is None:
        raise HttpError(404, "Course tidak ditemukan")
    if not is_course_owner_or_admin(request.user, course):
        raise HttpError(403, "Hanya owner course atau admin yang boleh mengedit konten")

    content = get_object_or_404(CourseContent, id=content_id, course_id=course)

    if data.name is not None:
        content.name = data.name
    if data.description is not None:
        content.description = data.description
    if data.subject is not None:
        content.subject = data.subject
    if data.body is not None:
        content.body = data.body
    if data.video_url is not None:
        content.video_url = data.video_url
    if data.parent_id is not None:
        if data.parent_id == content_id:
            raise HttpError(400, "Konten tidak bisa menjadi parent dari dirinya sendiri")
        parent = get_object_or_404(CourseContent, id=data.parent_id, course_id=course)
        content.parent_id = parent

    # Resolusi section baru (untuk menentukan scope order)
    new_section_id = content.section_id  # default: scope tidak berubah
    if data.section_id is not None:
        new_section = get_object_or_404(CourseSection, id=data.section_id, course=course)
        content.section = new_section
        new_section_id = new_section.id

    # Validasi order jika diubah
    if data.order is not None:
        _validate_positive_order(data.order)
        _validate_content_order(course.id, new_section_id, data.order, exclude_id=content_id)
        content.order = data.order

    if data.duration_minutes is not None:
        _validate_positive_duration(data.duration_minutes)
        content.duration_minutes = data.duration_minutes

    content.save()
    invalidate_course_cache(course.id)
    log_activity(
        request.user,
        "update_content",
        {"course_id": course.id, "content_id": content.id},
    )
    return serialize_content(content)


@api.delete(
    "/courses/{course_id}/contents/{content_id}",
    auth=api_auth,
    response={200: MessageOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    tags=["Contents"],
    summary="Hapus lesson (Instructor/Admin)",
)
def delete_content(request, course_id: int, content_id: int):
    course = Course.objects.select_related("teacher").filter(id=course_id).first()
    if course is None:
        raise HttpError(404, "Course tidak ditemukan")
    if not is_course_owner_or_admin(request.user, course):
        raise HttpError(403, "Hanya owner course atau admin yang boleh menghapus konten")

    content = get_object_or_404(CourseContent, id=content_id, course_id=course)
    content.delete()
    invalidate_course_cache(course.id)
    log_activity(
        request.user,
        "delete_content",
        {"course_id": course.id, "content_id": content_id},
    )
    return {"message": "Konten berhasil dihapus"}


# 4. ENROLLMENTS ENDPOINTS + CELERY TASKS + MONGODB LOGS

@api.post("/enrollments", auth=api_auth, response={201: EnrollmentOut, 400: ErrorOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut}, tags=["Enrollments"])
@require_student
def enroll_to_course(request, data: EnrollmentIn):
    course = get_object_or_404(Course, id=data.course_id)
    if CourseMember.objects.filter(course_id=course, user_id=request.user).exists():
        raise HttpError(400, "Anda sudah terdaftar di course ini")

    # Cek prerequisite: pastikan semua course prasyarat sudah diselesaikan
    prereqs = CoursePrerequisite.objects.filter(course=course).select_related("required_course")
    if prereqs.exists():
        unmet = []
        for prereq in prereqs:
            req_course = prereq.required_course
            # Cek apakah user sudah enroll di prerequisite course
            member = CourseMember.objects.filter(
                course_id=req_course, user_id=request.user
            ).first()
            if member is None:
                unmet.append(f"'{req_course.name}' (belum diambil)")
                continue
            # Cek apakah sudah menyelesaikan semua lesson
            total_content = CourseContent.objects.filter(course_id=req_course).count()
            completed_content = LessonProgress.objects.filter(
                member=member, is_completed=True
            ).count()
            if total_content == 0 or completed_content < total_content:
                pct = round(completed_content / total_content * 100, 1) if total_content > 0 else 0
                unmet.append(f"'{req_course.name}' (progress {pct}%, belum selesai)")
        if unmet:
            raise HttpError(
                403,
                "Anda harus menyelesaikan course prasyarat terlebih dahulu: " + ", ".join(unmet),
            )

    member = CourseMember.objects.create(course_id=course, user_id=request.user, roles="std")
    log_activity(request.user, "enroll_course", {"course_id": course.id, "enrollment_id": member.id})
    log_learning_activity(request.user, course.id, "enrolled", {"enrollment_id": member.id})
    send_enrollment_email.delay(member.id)
    invalidate_course_cache(course.id)
    invalidate_dashboard_cache(request.user.id)
    return 201, serialize_enrollment(member)


@api.get("/enrollments/my-courses", auth=api_auth, response={200: PaginatedEnrollmentOut, 401: ErrorOut}, tags=["Enrollments"])
def my_courses(request, page: int = 1, page_size: int = 10):
    page = max(page, 1)
    page_size = max(min(page_size, 100), 1)

    qs = (
        CourseMember.objects.select_related("course_id", "user_id")
        .filter(user_id=request.user)
        .order_by("course_id__name")
    )
    total = qs.count()
    start = (page - 1) * page_size
    end = start + page_size

    log_activity(request.user, "view_my_courses", {})
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "data": [serialize_enrollment(member) for member in qs[start:end]],
    }


@api.post("/enrollments/{enrollment_id}/progress", auth=api_auth, response={201: ProgressOut, 400: ErrorOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut}, tags=["Enrollments"])
def mark_lesson_complete(request, enrollment_id: int, data: ProgressIn):
    member = CourseMember.objects.select_related("course_id", "user_id").filter(id=enrollment_id).first()
    if member is None:
        raise HttpError(404, "CourseMember tidak ditemukan")
    if member.user_id_id != request.user.id:
        raise HttpError(403, "Anda tidak boleh mengubah progress enrollment milik user lain")

    content = get_object_or_404(CourseContent, id=data.content_id, course_id=member.course_id)
    if not _content_unlocked(member.course_id, member, content):
        raise HttpError(403, "Selesaikan lesson sebelumnya terlebih dahulu sebelum melanjutkan")

    progress, created = LessonProgress.objects.get_or_create(
        member=member,
        content=content,
        defaults={"is_completed": True},
    )
    if not created:
        progress.is_completed = True
        progress.save()

    log_learning_activity(request.user, member.course_id_id, "lesson_completed", {"content_id": content.id})
    invalidate_dashboard_cache(request.user.id)

    if _course_completed_by_member(member.course_id, member):
        generate_certificate.delay(member.id)

    return 201, {
        "id": progress.id,
        "enrollment_id": member.id,
        "content_id": content.id,
        "content_name": content.name,
        "is_completed": progress.is_completed,
        "completed_at": progress.completed_at,
    }


# 5. REPORTS, TASK CONTROL, AND MONITORING HELPERS

@api.post("/courses/{course_id}/export-report", auth=api_auth, response={202: TaskOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut}, tags=["Async Tasks"])
def request_course_report_export(request, course_id: int):
    course = get_object_or_404(Course, id=course_id)
    if not is_course_owner_or_admin(request.user, course):
        raise HttpError(403, "Hanya owner course atau admin yang boleh export report")
    task = export_course_report.delay(course.id)
    return 202, {"task_id": task.id, "status": "queued", "message": "Export course report sedang diproses"}


@api.post("/tasks/update-course-statistics", auth=api_auth, response={202: TaskOut, 401: ErrorOut, 403: ErrorOut}, tags=["Async Tasks"])
@require_admin
def request_update_course_statistics(request):
    task = update_course_statistics_task.delay()
    return 202, {"task_id": task.id, "status": "queued", "message": "Update statistik course sedang diproses"}


@api.get("/tasks/{task_id}", auth=api_auth, response={200: TaskStatusOut, 401: ErrorOut}, tags=["Async Tasks"])
def task_status(request, task_id: str):
    task = AsyncResult(task_id)
    result = task.result if task.ready() and isinstance(task.result, dict) else None
    return {"task_id": task_id, "status": task.status, "result": result}


# 5.1 GENERATE COURSE REPORT (async) — trigger + status polling

@api.post("/reports/generate/{course_id}/", auth=api_auth, response={202: TaskOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut}, tags=["Async Tasks"])
def generate_report(request, course_id: int):
    course = get_object_or_404(Course, id=course_id)
    if not is_course_owner_or_admin(request.user, course):
        raise HttpError(403, "Hanya owner course atau admin yang boleh generate report")

    # Kirim task ke Celery queue (non-blocking)
    task = generate_course_report.delay(course_id)

    log_activity(request.user, "generate_report_triggered", {"course_id": course_id, "task_id": task.id})
    return 202, {
        "task_id": task.id,
        "status": "processing",
        "message": f"Report untuk course '{course.name}' sedang dibuat.",
    }


@api.get("/reports/status/{task_id}/", response={200: TaskStatusOut, 401: ErrorOut}, tags=["Async Tasks"])
def report_status(request, task_id: str):
    result = AsyncResult(task_id)
    response = {
        "task_id": task_id,
        "status": result.status,
        "result": None,
    }

    if result.ready():
        if isinstance(result.result, dict):
            response["result"] = result.result
        else:
            response["result"] = {"output": str(result.result)}

    return response


@api.get("/reports/activity", auth=api_auth, tags=["Reports"])
@require_admin
def activity_report(request, limit: int = 20):
    return get_activity_report(limit=limit)


@api.get("/reports/learning", auth=api_auth, tags=["Reports"])
@require_admin
def learning_report(request, limit: int = 20):
    return get_learning_report(limit=limit)


# 6. FILE UPLOAD / DOWNLOAD ENDPOINTS

_ALLOWED_EXTENSIONS = {".pdf"}
_MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB fallback; dioverride dari settings jika tersedia


def _validate_upload(uploaded_file: UploadedFile) -> None:
    from django.conf import settings as dj_settings
    max_size = getattr(dj_settings, "MAX_UPLOAD_SIZE_BYTES", _MAX_SIZE_BYTES)
    allowed_exts = set(getattr(dj_settings, "ALLOWED_UPLOAD_EXTENSIONS", list(_ALLOWED_EXTENSIONS)))

    # Ukuran
    uploaded_file.seek(0, 2)  # ke akhir file
    size = uploaded_file.tell()
    uploaded_file.seek(0)     # reset ke awal
    if size > max_size:
        raise HttpError(400, f"File terlalu besar. Maksimum {max_size // (1024*1024)} MB.")

    # Ekstensi
    _, ext = os.path.splitext(uploaded_file.name or "")
    if ext.lower() not in allowed_exts:
        raise HttpError(400, "Hanya file PDF yang diizinkan untuk materi kelas.")


@api.post(
    "/courses/{course_id}/content/{content_id}/upload",
    auth=api_auth,
    response={200: FileUploadOut, 400: ErrorOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    tags=["Files"],
)
@rate_limit(prefix="upload")
def upload_content_file(request, course_id: int, content_id: int, file: UploadedFile = File(...)):
    course = Course.objects.select_related("teacher").filter(id=course_id).first()
    if course is None:
        raise HttpError(404, "Course tidak ditemukan")
    if not is_course_owner_or_admin(request.user, course):
        raise HttpError(403, "Hanya owner course atau admin yang boleh upload file")

    content = get_object_or_404(CourseContent, id=content_id, course_id=course)

    _validate_upload(file)

    # Pastikan nama file yang diterima berekstensi .pdf
    original_name = file.name or "materi"
    base_name = os.path.splitext(original_name)[0]
    save_name = base_name + ".pdf"

    content.file_attachment.save(save_name, file, save=True)
    log_activity(request.user, "upload_content_file", {"course_id": course_id, "content_id": content_id})
    return {
        "content_id": content.id,
        "filename": os.path.basename(content.file_attachment.name),
        "url": request.build_absolute_uri(content.file_attachment.url),
        "size": file.size if hasattr(file, 'size') else None,
    }


@api.delete(
    "/courses/{course_id}/content/{content_id}/file",
    auth=api_auth,
    response={200: MessageOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    tags=["Files"],
    summary="Hapus file materi PDF dari lesson (Instructor/Admin)",
)
def delete_content_file(request, course_id: int, content_id: int):
    course = Course.objects.select_related("teacher").filter(id=course_id).first()
    if course is None:
        raise HttpError(404, "Course tidak ditemukan")
    if not is_course_owner_or_admin(request.user, course):
        raise HttpError(403, "Hanya owner course atau admin yang boleh menghapus file")

    content = get_object_or_404(CourseContent, id=content_id, course_id=course)

    if not content.file_attachment:
        raise HttpError(404, "Tidak ada file yang terpasang pada lesson ini")

    # Hapus file fisik dari disk
    file_path = content.file_attachment.path
    if os.path.exists(file_path):
        os.remove(file_path)

    # Kosongkan field di database
    content.file_attachment.delete(save=False)
    content.file_attachment = None
    content.save(update_fields=["file_attachment"])

    log_activity(
        request.user,
        "delete_content_file",
        {"course_id": course_id, "content_id": content_id},
    )
    return {"message": "File materi berhasil dihapus"}


@api.get(
    "/courses/{course_id}/content/{content_id}/download",
    auth=api_auth,
    tags=["Files"],
    response={401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
)
def download_content_file(request, course_id: int, content_id: int):
    course = get_object_or_404(Course, id=course_id)
    content = get_object_or_404(CourseContent, id=content_id, course_id=course)

    # Cek akses: owner/admin atau member yang sudah enroll
    if not is_course_owner_or_admin(request.user, course):
        is_enrolled = CourseMember.objects.filter(course_id=course, user_id=request.user).exists()
        if not is_enrolled:
            raise HttpError(403, "Anda harus enroll ke course ini untuk mengunduh file")

    if not content.file_attachment:
        raise HttpError(404, "File attachment tidak tersedia untuk konten ini")

    file_path = content.file_attachment.path
    if not os.path.exists(file_path):
        raise HttpError(404, "File tidak ditemukan di server")

    content_type, _ = mimetypes.guess_type(file_path)
    content_type = content_type or "application/octet-stream"
    filename = os.path.basename(file_path)

    log_activity(request.user, "download_content_file", {"course_id": course_id, "content_id": content_id})
    response = FileResponse(open(file_path, "rb"), content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# =============================================================================
# 7. PAKET 1 — LMS EXPERIENCE
# =============================================================================

# ── 7.1 SECTIONS (Curriculum) ────────────────────────────────────────────────

def _serialize_section(section: CourseSection) -> dict:
    return {
        "id": section.id,
        "course_id": section.course_id,
        "title": section.title,
        "order": section.order,
        "created_at": section.created_at,
    }


@api.post(
    "/courses/{course_id}/sections",
    auth=api_auth,
    response={201: SectionOut, 400: ErrorOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    tags=["Sections"],
    summary="Buat section baru di course (Owner/Admin)",
)
def create_section(request, course_id: int, data: SectionIn):
    course = Course.objects.select_related("teacher").filter(id=course_id).first()
    if course is None:
        raise HttpError(404, "Course tidak ditemukan")
    if not is_course_owner_or_admin(request.user, course):
        raise HttpError(403, "Hanya owner course atau admin yang boleh membuat section")

    # Auto-assign order jika tidak dikirim, atau validasi jika dikirim manual
    _validate_positive_order(data.order)
    if data.order is None:
        order = _next_section_order(course_id)
    else:
        _validate_section_order(course_id, data.order)
        order = data.order

    section = CourseSection.objects.create(
        course=course,
        title=data.title,
        order=order,
    )
    log_activity(request.user, "create_section", {"course_id": course_id, "section_id": section.id})
    return 201, _serialize_section(section)


@api.get(
    "/courses/{course_id}/sections",
    response={200: list[SectionWithLessonsOut], 404: ErrorOut},
    tags=["Sections"],
    summary="List sections beserta lessons (Public)",
)
def list_sections(request, course_id: int):
    course = get_object_or_404(Course, id=course_id)
    sections = CourseSection.objects.filter(course=course).order_by("order").prefetch_related("contents")

    result = []
    for section in sections:
        lessons = (
            section.contents
            .filter(parent_id__isnull=True)
            .order_by("order", "id")
        )
        result.append({
            "id": section.id,
            "course_id": section.course_id,
            "title": section.title,
            "order": section.order,
            "total_lessons": lessons.count(),
            "lessons": [
                {
                    "id": c.id,
                    "name": c.name,
                    "description": c.description,
                    "subject": c.subject,
                    "video_url": c.video_url,
                    "order": c.order,
                    "duration_minutes": c.duration_minutes,
                }
                for c in lessons
            ],
        })
    return result


@api.patch(
    "/courses/{course_id}/sections/{section_id}",
    auth=api_auth,
    response={200: SectionOut, 400: ErrorOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    tags=["Sections"],
    summary="Update section (Owner/Admin)",
)
def update_section(request, course_id: int, section_id: int, data: SectionUpdateIn):
    course = Course.objects.select_related("teacher").filter(id=course_id).first()
    if course is None:
        raise HttpError(404, "Course tidak ditemukan")
    if not is_course_owner_or_admin(request.user, course):
        raise HttpError(403, "Hanya owner course atau admin yang boleh mengupdate section")

    section = get_object_or_404(CourseSection, id=section_id, course=course)
    if data.title is not None:
        section.title = data.title
    if data.order is not None:
        _validate_positive_order(data.order)
        # Validasi: pastikan order baru tidak bentrok dengan section lain
        _validate_section_order(course_id, data.order, exclude_id=section_id)
        section.order = data.order
    section.save()

    log_activity(request.user, "update_section", {"course_id": course_id, "section_id": section_id})
    return _serialize_section(section)


@api.delete(
    "/courses/{course_id}/sections/{section_id}",
    auth=api_auth,
    response={200: MessageOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    tags=["Sections"],
    summary="Hapus section (Owner/Admin)",
)
def delete_section(request, course_id: int, section_id: int):
    course = Course.objects.select_related("teacher").filter(id=course_id).first()
    if course is None:
        raise HttpError(404, "Course tidak ditemukan")
    if not is_course_owner_or_admin(request.user, course):
        raise HttpError(403, "Hanya owner course atau admin yang boleh menghapus section")

    section = get_object_or_404(CourseSection, id=section_id, course=course)
    section.delete()
    log_activity(request.user, "delete_section", {"course_id": course_id, "section_id": section_id})
    return {"message": "Section berhasil dihapus"}


# ── 7.2 PROGRESS DETAIL ──────────────────────────────────────────────────────

@api.get(
    "/enrollments/{enrollment_id}/progress",
    auth=api_auth,
    response={200: EnrollmentProgressDetailOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    tags=["Enrollments"],
    summary="Detail progress belajar per section",
)
def enrollment_progress_detail(request, enrollment_id: int):
    member = CourseMember.objects.select_related("course_id", "user_id").filter(id=enrollment_id).first()
    if member is None:
        raise HttpError(404, "CourseMember tidak ditemukan")
    if member.user_id_id != request.user.id and not is_admin(request.user):
        raise HttpError(403, "Tidak boleh melihat progress enrollment milik user lain")

    course = member.course_id
    all_contents = list(CourseContent.objects.filter(course_id=course).select_related("section").order_by("order"))
    completed_ids = set(
        LessonProgress.objects.filter(member=member, is_completed=True)
        .values_list("content_id", flat=True)
    )

    total_lessons = len(all_contents)
    completed_lessons = len([c for c in all_contents if c.id in completed_ids])
    progress_percent = round((completed_lessons / total_lessons * 100), 2) if total_lessons > 0 else 0.0

    # Build per-section breakdown with per-lesson detail
    sections_map: dict = {}
    unsectioned_lessons = []

    for content in all_contents:
        if content.section_id:
            sid = content.section_id
            if sid not in sections_map:
                sections_map[sid] = {
                    "section_id": sid,
                    "section_title": content.section.title if content.section else "",
                    "total": 0,
                    "completed": 0,
                    "lessons": [],
                }
            sections_map[sid]["total"] += 1
            if content.id in completed_ids:
                sections_map[sid]["completed"] += 1
            sections_map[sid]["lessons"].append({
                "lesson_id": content.id,
                "title": content.name,
                "is_completed": content.id in completed_ids,
            })
        else:
            unsectioned_lessons.append(content)

    sections_out = [
        {
            "section_id": v["section_id"],
            "section_title": v["section_title"],
            "total_lessons": v["total"],
            "completed_lessons": v["completed"],
            "progress_percent": round(v["completed"] / v["total"] * 100, 2) if v["total"] > 0 else 0.0,
            "lessons": v["lessons"],
        }
        for v in sorted(sections_map.values(), key=lambda x: x["section_id"])
    ]

    # Append unsectioned lessons as a virtual section
    if unsectioned_lessons:
        unsectioned_completed = len([c for c in unsectioned_lessons if c.id in completed_ids])
        unsectioned_total = len(unsectioned_lessons)
        sections_out.append({
            "section_id": None,
            "section_title": "Tanpa Section",
            "total_lessons": unsectioned_total,
            "completed_lessons": unsectioned_completed,
            "progress_percent": round(unsectioned_completed / unsectioned_total * 100, 2) if unsectioned_total > 0 else 0.0,
            "lessons": [
                {
                    "lesson_id": c.id,
                    "title": c.name,
                    "is_completed": c.id in completed_ids,
                }
                for c in unsectioned_lessons
            ],
        })

    return {
        "total_lessons": total_lessons,
        "completed_lessons": completed_lessons,
        "progress_percent": progress_percent,
        "sections": sections_out,
    }


# ── 7.3 REVIEWS ──────────────────────────────────────────────────────────────

def _serialize_review(review: CourseReview) -> dict:
    return {
        "id": review.id,
        "course_id": review.course_id,
        "user_id": review.user_id,
        "username": review.user.username,
        "rating": review.rating,
        "review": review.review,
        "created_at": review.created_at,
        "updated_at": review.updated_at,
    }


@api.post(
    "/courses/{course_id}/reviews",
    auth=api_auth,
    response={201: ReviewOut, 400: ErrorOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    tags=["Reviews"],
    summary="Buat atau update review course (Student yang sudah enroll)",
)
def create_or_update_review(request, course_id: int, data: ReviewIn):
    course = get_object_or_404(Course, id=course_id)

    # Pastikan sudah enroll
    if not CourseMember.objects.filter(course_id=course, user_id=request.user).exists():
        raise HttpError(403, "Harus enroll ke course ini untuk memberikan review")

    if not (1 <= data.rating <= 5):
        raise HttpError(400, "Rating harus antara 1 dan 5")

    review, created = CourseReview.objects.update_or_create(
        course=course,
        user=request.user,
        defaults={"rating": data.rating, "review": data.review},
    )

    # Update rating_avg dan total_reviews di Course
    agg = CourseReview.objects.filter(course=course).aggregate(
        avg=Avg("rating"), total=Count("id")
    )
    course.rating_avg = round(agg["avg"] or 0, 2)
    course.total_reviews = agg["total"]
    course.save(update_fields=["rating_avg", "total_reviews"])
    invalidate_course_cache(course.id)

    log_activity(request.user, "create_review", {"course_id": course_id, "rating": data.rating})
    return 201, _serialize_review(review)


@api.get(
    "/courses/{course_id}/reviews",
    response={200: ReviewListOut, 404: ErrorOut},
    tags=["Reviews"],
    summary="List semua review dan rata-rata rating (Public)",
)
def list_reviews(request, course_id: int):
    course = get_object_or_404(Course, id=course_id)
    reviews = CourseReview.objects.filter(course=course).select_related("user").order_by("-created_at")
    return {
        "total": reviews.count(),
        "rating_avg": course.rating_avg,
        "data": [_serialize_review(r) for r in reviews],
    }


@api.delete(
    "/courses/{course_id}/reviews/{review_id}",
    auth=api_auth,
    response={200: MessageOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    tags=["Reviews"],
    summary="Hapus review (Owner review / Admin)",
)
def delete_review(request, course_id: int, review_id: int):
    course = get_object_or_404(Course, id=course_id)
    review = get_object_or_404(CourseReview, id=review_id, course=course)

    if review.user_id != request.user.id and not is_admin(request.user):
        raise HttpError(403, "Hanya pemilik review atau admin yang boleh menghapus")

    review.delete()

    # Recalculate rating
    agg = CourseReview.objects.filter(course=course).aggregate(
        avg=Avg("rating"), total=Count("id")
    )
    course.rating_avg = round(agg["avg"] or 0, 2)
    course.total_reviews = agg["total"]
    course.save(update_fields=["rating_avg", "total_reviews"])
    invalidate_course_cache(course.id)

    log_activity(request.user, "delete_review", {"course_id": course_id, "review_id": review_id})
    return {"message": "Review berhasil dihapus"}


# ── 7.4 WISHLIST ─────────────────────────────────────────────────────────────

def _serialize_wishlist(wl: Wishlist) -> dict:
    return {
        "id": wl.id,
        "course_id": wl.course_id,
        "course_name": wl.course.name,
        "rating_avg": wl.course.rating_avg,
        "created_at": wl.created_at,
    }


@api.post(
    "/wishlist",
    auth=api_auth,
    response={201: WishlistOut, 400: ErrorOut, 401: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    tags=["Wishlist"],
    summary="Tambah course ke wishlist",
)
def add_to_wishlist(request, data: WishlistIn):
    course = get_object_or_404(Course, id=data.course_id)
    if Wishlist.objects.filter(user=request.user, course=course).exists():
        raise HttpError(409, "Kamu sudah menambahkan course ini ke wishlist")

    wl = Wishlist.objects.create(user=request.user, course=course)
    invalidate_dashboard_cache(request.user.id)
    log_activity(request.user, "add_wishlist", {"course_id": data.course_id})
    return 201, _serialize_wishlist(wl)


@api.delete(
    "/wishlist/{course_id}",
    auth=api_auth,
    response={200: MessageOut, 401: ErrorOut, 404: ErrorOut},
    tags=["Wishlist"],
    summary="Hapus course dari wishlist",
)
def remove_from_wishlist(request, course_id: int):
    wl = get_object_or_404(Wishlist, user=request.user, course_id=course_id)
    wl.delete()
    invalidate_dashboard_cache(request.user.id)
    log_activity(request.user, "remove_wishlist", {"course_id": course_id})
    return {"message": "Course berhasil dihapus dari wishlist"}


@api.get(
    "/wishlist",
    auth=api_auth,
    response={200: PaginatedWishlistOut, 401: ErrorOut},
    tags=["Wishlist"],
    summary="Lihat semua wishlist milik user yang login",
)
def my_wishlist(request, page: int = 1, page_size: int = 10):
    page = max(page, 1)
    page_size = max(min(page_size, 100), 1)
    qs = Wishlist.objects.filter(user=request.user).select_related("course").order_by("-created_at")
    total = qs.count()
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "data": [_serialize_wishlist(wl) for wl in qs[start:end]],
    }


# ── 7.5 STUDENT DASHBOARD ────────────────────────────────────────────────────

@api.get(
    "/dashboard/student",
    auth=api_auth,
    response={200: StudentDashboardOut, 401: ErrorOut, 403: ErrorOut},
    tags=["Dashboard"],
    summary="Dashboard student: enrolled courses, progress, dan rekomendasi",
)
def student_dashboard(request):
    user = request.user

    # Cek cache terlebih dahulu
    cache_key = dashboard_cache_key(user.id)
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    # Ambil semua enrollment user
    enrollments = (
        CourseMember.objects.filter(user_id=user)
        .select_related("course_id", "course_id__teacher")
    )

    active_courses = []
    completed_courses = []
    enrolled_category_ids = set()

    for member in enrollments:
        course = member.course_id
        if course.category_id:
            enrolled_category_ids.add(course.category_id)

        all_contents_count = CourseContent.objects.filter(course_id=course).count()
        completed_count = LessonProgress.objects.filter(member=member, is_completed=True).count()
        progress_pct = round(completed_count / all_contents_count * 100, 2) if all_contents_count > 0 else 0.0

        course_entry = {
            "course_id": course.id,
            "course_name": course.name,
            "progress_percent": progress_pct,
            "total_lessons": all_contents_count,
            "completed_lessons": completed_count,
            "instructor_name": course.teacher.get_full_name() or course.teacher.username,
        }

        if all_contents_count > 0 and completed_count >= all_contents_count:
            completed_courses.append(course_entry)
        else:
            active_courses.append(course_entry)

    # Wishlist count + list
    wishlist_qs = Wishlist.objects.filter(user=user).select_related("course", "course__teacher").order_by("-created_at")[:10]
    wishlist_count = Wishlist.objects.filter(user=user).count()
    wishlist_list = [
        {
            "course_id": wl.course.id,
            "course_name": wl.course.name,
            "rating_avg": wl.course.rating_avg,
            "price": wl.course.price,
            "instructor_name": wl.course.teacher.get_full_name() or wl.course.teacher.username,
        }
        for wl in wishlist_qs
    ]

    # Recommended: top-5 rated courses, belum di-enroll, dari kategori yang sama
    enrolled_course_ids = set(enrollments.values_list("course_id_id", flat=True))
    recommended_qs = (
        Course.objects.filter(status="published")
        .exclude(id__in=enrolled_course_ids)
        .select_related("teacher")
        .order_by("-rating_avg")[:5]
    )
    reason = "Populer di platform"
    # Filter berdasarkan kategori yang sama jika ada
    if enrolled_category_ids:
        cat_qs = (
            Course.objects.filter(status="published", category_id__in=enrolled_category_ids)
            .exclude(id__in=enrolled_course_ids)
            .select_related("teacher")
            .order_by("-rating_avg")[:5]
        )
        if cat_qs.exists():
            recommended_qs = cat_qs
            reason = "Populer di kategori yang sama"

    recommended = [
        {
            "id": c.id,
            "name": c.name,
            "rating_avg": c.rating_avg,
            "total_reviews": c.total_reviews,
            "price": c.price,
            "instructor_name": c.teacher.get_full_name() or c.teacher.username,
            "reason": reason,
        }
        for c in recommended_qs
    ]

    response = {
        "active_courses": active_courses,
        "completed_courses": completed_courses,
        "total_enrolled": len(active_courses) + len(completed_courses),
        "total_completed": len(completed_courses),
        "wishlist_count": wishlist_count,
        "wishlist": wishlist_list,
        "recommended_courses": recommended,
    }

    # Cache selama 3 menit
    cache_set(cache_key, response, timeout=180)
    log_activity(user, "view_student_dashboard", {})
    return response


# =============================================================================
# 8. PUBLISHING WORKFLOW
# =============================================================================

def _serialize_publish_request(pr: CoursePublishRequest) -> dict:
    return {
        "id": pr.id,
        "course_id": pr.course_id,
        "course_name": pr.course.name,
        "requester_id": pr.requester_id,
        "requester_username": pr.requester.username,
        "status": pr.status,
        "reviewer_id": pr.reviewer_id,
        "reviewer_username": pr.reviewer.username if pr.reviewer else None,
        "rejection_reason": pr.rejection_reason,
        "requested_at": pr.requested_at,
        "reviewed_at": pr.reviewed_at,
    }


@api.post(
    "/courses/{course_id}/submit-for-review",
    auth=api_auth,
    response={200: PublishRequestOut, 400: ErrorOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    tags=["Publishing Workflow"],
    summary="Instructor mengajukan course untuk di-review admin (draft → pending_review)",
)
def submit_for_review(request, course_id: int):
    course = get_object_or_404(
        Course.objects.select_related("teacher"), id=course_id
    )
    if not is_course_owner_or_admin(request.user, course):
        raise HttpError(403, "Hanya owner course atau admin yang boleh mengajukan review")

    if course.status == "pending_review":
        raise HttpError(400, "Course sudah dalam status pending_review. Tunggu keputusan admin.")
    if course.status == "published":
        raise HttpError(400, "Course sudah dipublikasikan. Edit course terlebih dahulu jika ingin review ulang.")
    if course.status == "archived":
        raise HttpError(400, "Course yang diarsipkan tidak bisa diajukan untuk review. Ubah ke draft terlebih dahulu.")
    if course.status != "draft":
        raise HttpError(400, f"Course harus berstatus 'draft' untuk diajukan review. Status saat ini: {course.status}")

    # Batalkan semua pending request lama untuk course ini (seharusnya tidak ada, tapi untuk safety)
    CoursePublishRequest.objects.filter(course=course, status="pending").update(status="rejected")

    pr = CoursePublishRequest.objects.create(
        course=course,
        requester=request.user,
        status="pending",
    )
    course.status = "pending_review"
    course.save(update_fields=["status"])
    invalidate_course_cache(course.id)

    log_activity(request.user, "submit_course_for_review", {"course_id": course.id, "request_id": pr.id})
    return _serialize_publish_request(pr)


@api.get(
    "/courses/pending-review",
    auth=api_auth,
    response={200: list[PublishRequestOut], 401: ErrorOut, 403: ErrorOut},
    tags=["Publishing Workflow"],
    summary="Daftar semua course yang menunggu review (Admin only)",
)
@require_admin
def list_pending_reviews(request):
    prs = (
        CoursePublishRequest.objects
        .filter(status="pending")
        .select_related("course", "requester", "reviewer")
        .order_by("requested_at")
    )
    return [_serialize_publish_request(pr) for pr in prs]


@api.post(
    "/courses/{course_id}/approve",
    auth=api_auth,
    response={200: PublishRequestOut, 400: ErrorOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    tags=["Publishing Workflow"],
    summary="Admin menyetujui publish request (pending_review → published)",
)
@require_admin
def approve_course(request, course_id: int):
    course = get_object_or_404(Course, id=course_id)

    if course.status != "pending_review":
        raise HttpError(400, f"Course tidak sedang dalam status pending_review. Status saat ini: {course.status}")

    pr = (
        CoursePublishRequest.objects
        .filter(course=course, status="pending")
        .select_related("course", "requester", "reviewer")
        .first()
    )
    if pr is None:
        raise HttpError(404, "Tidak ada pending publish request untuk course ini")

    from django.utils import timezone
    pr.status = "approved"
    pr.reviewer = request.user
    pr.reviewed_at = timezone.now()
    pr.save()

    course.status = "published"
    course.save(update_fields=["status"])
    invalidate_course_cache(course.id)

    log_activity(request.user, "approve_course", {"course_id": course.id, "request_id": pr.id})
    return _serialize_publish_request(pr)


@api.post(
    "/courses/{course_id}/reject",
    auth=api_auth,
    response={200: PublishRequestOut, 400: ErrorOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    tags=["Publishing Workflow"],
    summary="Admin menolak publish request (pending_review → draft)",
)
@require_admin
def reject_course(request, course_id: int, data: PublishReviewIn):
    course = get_object_or_404(Course, id=course_id)

    if course.status != "pending_review":
        raise HttpError(400, f"Course tidak sedang dalam status pending_review. Status saat ini: {course.status}")

    pr = (
        CoursePublishRequest.objects
        .filter(course=course, status="pending")
        .select_related("course", "requester", "reviewer")
        .first()
    )
    if pr is None:
        raise HttpError(404, "Tidak ada pending publish request untuk course ini")

    from django.utils import timezone
    pr.status = "rejected"
    pr.reviewer = request.user
    pr.rejection_reason = data.reason
    pr.reviewed_at = timezone.now()
    pr.save()

    course.status = "draft"
    course.save(update_fields=["status"])
    invalidate_course_cache(course.id)

    log_activity(request.user, "reject_course", {"course_id": course.id, "request_id": pr.id, "reason": data.reason})
    return _serialize_publish_request(pr)


@api.get(
    "/courses/{course_id}/publish-history",
    auth=api_auth,
    response={200: list[PublishRequestOut], 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    tags=["Publishing Workflow"],
    summary="Riwayat semua publish request untuk sebuah course (Owner/Admin)",
)
def course_publish_history(request, course_id: int):
    course = get_object_or_404(Course, id=course_id)
    if not is_course_owner_or_admin(request.user, course):
        raise HttpError(403, "Hanya owner course atau admin yang bisa melihat riwayat publish")

    prs = (
        CoursePublishRequest.objects
        .filter(course=course)
        .select_related("course", "requester", "reviewer")
        .order_by("-requested_at")
    )
    return [_serialize_publish_request(pr) for pr in prs]


# =============================================================================
# 9. COURSE PREREQUISITES
# =============================================================================

def _serialize_prerequisite(prereq: CoursePrerequisite) -> dict:
    return {
        "id": prereq.id,
        "course_id": prereq.course_id,
        "required_course_id": prereq.required_course_id,
        "required_course_name": prereq.required_course.name,
        "created_at": prereq.created_at,
    }


def _has_circular_dependency(course_id: int, required_course_id: int) -> bool:
    """Check apakah menambah required_course_id sebagai prerequisite course_id akan membuat circular dependency."""
    # BFS/DFS: cari apakah course_id sudah merupakan (langsung/tidak langsung) prerequisite dari required_course_id
    visited = set()
    queue = [required_course_id]
    while queue:
        current = queue.pop(0)
        if current == course_id:
            return True  # Circular!
        if current in visited:
            continue
        visited.add(current)
        # Cari semua prerequisite dari current
        prereq_ids = list(
            CoursePrerequisite.objects.filter(course_id=current).values_list("required_course_id", flat=True)
        )
        queue.extend(prereq_ids)
    return False


@api.get(
    "/courses/{course_id}/prerequisites",
    response={200: list[PrerequisiteOut], 404: ErrorOut},
    tags=["Prerequisites"],
    summary="List semua prerequisite untuk sebuah course (Public)",
)
def list_prerequisites(request, course_id: int):
    course = get_object_or_404(Course, id=course_id)
    prereqs = (
        CoursePrerequisite.objects
        .filter(course=course)
        .select_related("required_course")
        .order_by("created_at")
    )
    return [_serialize_prerequisite(p) for p in prereqs]


@api.post(
    "/courses/{course_id}/prerequisites",
    auth=api_auth,
    response={201: PrerequisiteOut, 400: ErrorOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    tags=["Prerequisites"],
    summary="Tambah prerequisite ke course (Owner/Admin)",
)
def add_prerequisite(request, course_id: int, data: PrerequisiteIn):
    course = get_object_or_404(Course, id=course_id)
    if not is_course_owner_or_admin(request.user, course):
        raise HttpError(403, "Hanya owner course atau admin yang boleh menambah prerequisite")

    if data.required_course_id == course_id:
        raise HttpError(400, "Course tidak bisa menjadi prerequisite untuk dirinya sendiri")

    required_course = get_object_or_404(Course, id=data.required_course_id)

    # Cek duplikat
    if CoursePrerequisite.objects.filter(course=course, required_course=required_course).exists():
        raise HttpError(409, f"'{required_course.name}' sudah menjadi prerequisite course ini")

    # Cek circular dependency
    if _has_circular_dependency(course_id, data.required_course_id):
        raise HttpError(
            400,
            f"Menambah '{required_course.name}' sebagai prerequisite akan membuat circular dependency"
        )

    prereq = CoursePrerequisite.objects.create(course=course, required_course=required_course)
    log_activity(request.user, "add_prerequisite", {"course_id": course_id, "required_course_id": data.required_course_id})
    return 201, _serialize_prerequisite(prereq)


@api.delete(
    "/courses/{course_id}/prerequisites/{prereq_id}",
    auth=api_auth,
    response={200: MessageOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    tags=["Prerequisites"],
    summary="Hapus prerequisite dari course (Owner/Admin)",
)
def remove_prerequisite(request, course_id: int, prereq_id: int):
    course = get_object_or_404(Course, id=course_id)
    if not is_course_owner_or_admin(request.user, course):
        raise HttpError(403, "Hanya owner course atau admin yang boleh menghapus prerequisite")

    prereq = get_object_or_404(CoursePrerequisite, id=prereq_id, course=course)
    name = prereq.required_course.name
    prereq.delete()
    log_activity(request.user, "remove_prerequisite", {"course_id": course_id, "prereq_id": prereq_id})
    return {"message": f"Prerequisite '{name}' berhasil dihapus"}




# =============================================================================
# 10. COURSE READER, LOCKING, QUIZ, DAN QUESTION BANK
# =============================================================================

QUIZ_COOLDOWN_MINUTES = 10
QUIZ_MAX_FAILED_ATTEMPTS = 2


def _ordered_course_contents(course: Course):
    return (
        CourseContent.objects
        .filter(course_id=course, parent_id__isnull=True)
        .select_related("section")
        .order_by(
            db_models.F("section__order").asc(nulls_last=True),
            db_models.F("section_id").asc(nulls_last=True),
            "order",
            "id",
        )
    )


def _member_for_user(course: Course, user: User):
    if not getattr(user, "is_authenticated", False):
        return None
    return CourseMember.objects.filter(course_id=course, user_id=user).first()


def _completed_lesson_ids(member: CourseMember) -> set[int]:
    if member is None:
        return set()
    return set(
        LessonProgress.objects.filter(member=member, is_completed=True)
        .values_list("content_id", flat=True)
    )


def _passed_quiz_ids(member: CourseMember) -> set[int]:
    if member is None:
        return set()
    return set(
        QuizAttempt.objects.filter(member=member, passed=True, submitted_at__isnull=False)
        .values_list("quiz_id", flat=True)
    )


def _section_completed(course: Course, member: CourseMember, section: CourseSection | None) -> bool:
    if member is None:
        return False
    completed_ids = _completed_lesson_ids(member)
    passed_ids = _passed_quiz_ids(member)
    lessons = CourseContent.objects.filter(course_id=course, section=section, parent_id__isnull=True)
    quizzes = Quiz.objects.filter(course=course, section=section, is_active=True)
    lessons_done = all(lesson.id in completed_ids for lesson in lessons)
    quizzes_done = all(quiz.id in passed_ids for quiz in quizzes)
    return lessons_done and quizzes_done


def _section_unlocked(course: Course, member: CourseMember, section: CourseSection | None) -> bool:
    if member is None:
        return False
    if section is None:
        previous_sections = CourseSection.objects.filter(course=course).order_by("order", "id")
    else:
        previous_sections = CourseSection.objects.filter(course=course, order__lt=section.order).order_by("order", "id")
    return all(_section_completed(course, member, prev) for prev in previous_sections)


def _content_unlocked(course: Course, member: CourseMember, content: CourseContent) -> bool:
    if member is None:
        return False
    if not _section_unlocked(course, member, content.section):
        return False
    completed_ids = _completed_lesson_ids(member)
    previous_lessons = CourseContent.objects.filter(
        course_id=course,
        section=content.section,
        parent_id__isnull=True,
        order__lt=content.order,
    )
    return all(lesson.id in completed_ids for lesson in previous_lessons)


def _quiz_unlocked(course: Course, member: CourseMember, quiz: Quiz) -> bool:
    if member is None:
        return False
    if not _section_unlocked(course, member, quiz.section):
        return False
    completed_ids = _completed_lesson_ids(member)
    section_lessons = CourseContent.objects.filter(course_id=course, section=quiz.section, parent_id__isnull=True)
    return all(lesson.id in completed_ids for lesson in section_lessons)


def _course_completed_by_member(course: Course, member: CourseMember) -> bool:
    completed_ids = _completed_lesson_ids(member)
    passed_ids = _passed_quiz_ids(member)
    lessons = CourseContent.objects.filter(course_id=course, parent_id__isnull=True)
    quizzes = Quiz.objects.filter(course=course, is_active=True)
    return all(lesson.id in completed_ids for lesson in lessons) and all(quiz.id in passed_ids for quiz in quizzes)


def _quiz_attempt_status(quiz: Quiz, member: CourseMember | None) -> dict:
    now = timezone.now()
    if member is None:
        return {
            "passed": False,
            "can_attempt": False,
            "remaining_attempts": 0,
            "cooldown_until": None,
            "message": "Anda harus enroll ke course ini terlebih dahulu.",
        }

    if QuizAttempt.objects.filter(quiz=quiz, member=member, passed=True, submitted_at__isnull=False).exists():
        return {
            "passed": True,
            "can_attempt": False,
            "remaining_attempts": 0,
            "cooldown_until": None,
            "message": "Anda sudah lulus kuis ini.",
        }

    blocking = (
        QuizAttempt.objects
        .filter(quiz=quiz, member=member, passed=False, cooldown_until__gt=now)
        .order_by("-cooldown_until")
        .first()
    )
    if blocking:
        return {
            "passed": False,
            "can_attempt": False,
            "remaining_attempts": 0,
            "cooldown_until": blocking.cooldown_until,
            "message": "Anda bisa menelusuri ulang materi-materi sebelumnya sebelum memulai kembali.",
        }

    window_start = now - timedelta(minutes=QUIZ_COOLDOWN_MINUTES)
    failed_recent = QuizAttempt.objects.filter(
        quiz=quiz,
        member=member,
        passed=False,
        submitted_at__gte=window_start,
    ).count()
    remaining = max(0, QUIZ_MAX_FAILED_ATTEMPTS - failed_recent)
    return {
        "passed": False,
        "can_attempt": remaining > 0,
        "remaining_attempts": remaining,
        "cooldown_until": None,
        "message": "" if remaining > 0 else "Anda bisa menelusuri ulang materi-materi sebelumnya sebelum memulai kembali.",
    }


def _serialize_quiz(quiz: Quiz, member: CourseMember | None = None, locked: bool = False) -> dict:
    status = _quiz_attempt_status(quiz, member)
    total_questions = quiz.questions.count()
    can_attempt = status["can_attempt"] and not locked and quiz.is_active and total_questions > 0
    message = status["message"]
    if locked:
        message = "Selesaikan materi/section sebelumnya terlebih dahulu."
    elif total_questions == 0:
        message = "Question bank kuis ini masih kosong."
    return {
        "id": quiz.id,
        "course_id": quiz.course_id,
        "section_id": quiz.section_id,
        "title": quiz.title,
        "description": quiz.description,
        "order": quiz.order,
        "minimum_score": quiz.minimum_score,
        "question_count": quiz.question_count,
        "total_questions": total_questions,
        "is_active": quiz.is_active,
        "is_locked": locked,
        "passed": status["passed"],
        "can_attempt": can_attempt,
        "remaining_attempts": status["remaining_attempts"],
        "cooldown_until": status["cooldown_until"],
        "message": message,
        "created_at": quiz.created_at,
        "updated_at": quiz.updated_at,
    }


def _serialize_quiz_question(question: QuizQuestion, include_answer: bool = False) -> dict:
    data = {
        "id": question.id,
        "quiz_id": question.quiz_id,
        "question_text": question.question_text,
        "choices": question.choices or [],
        "explanation": question.explanation,
        "points": question.points,
        "created_at": question.created_at,
    }
    if include_answer:
        data["correct_answer"] = question.correct_answer
    return data


def _validate_question_payload(data):
    choices = [str(choice).strip() for choice in (data.choices or []) if str(choice).strip()]
    if len(choices) < 2:
        raise HttpError(400, "Minimal pilihan jawaban adalah 2")
    if data.correct_answer not in choices:
        raise HttpError(400, "correct_answer harus sama persis dengan salah satu choices")
    if data.points < 1:
        raise HttpError(400, "points minimal 1")
    return choices


def _require_course_learning_access(request, course: Course) -> CourseMember | None:
    if is_course_owner_or_admin(request.user, course):
        return _member_for_user(course, request.user)
    member = _member_for_user(course, request.user)
    if member is None:
        raise HttpError(403, "Anda harus enroll ke course ini terlebih dahulu")
    return member


@api.get(
    "/courses/{course_id}/learning-map",
    auth=api_auth,
    response={200: LearningMapOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    tags=["Learning"],
    summary="Struktur belajar course lengkap dengan status lock lesson dan kuis",
)
def course_learning_map(request, course_id: int):
    course = get_object_or_404(Course, id=course_id)
    member = _require_course_learning_access(request, course)
    can_manage = is_course_owner_or_admin(request.user, course)
    completed_ids = _completed_lesson_ids(member)
    passed_ids = _passed_quiz_ids(member)

    sections = list(CourseSection.objects.filter(course=course).order_by("order", "id"))
    section_payloads = []
    for section in sections:
        section_locked = False if can_manage else not _section_unlocked(course, member, section)
        lessons = list(CourseContent.objects.filter(course_id=course, section=section, parent_id__isnull=True).order_by("order", "id"))
        quizzes = list(Quiz.objects.filter(course=course, section=section).order_by("order", "id"))
        section_payloads.append({
            "id": section.id,
            "title": section.title,
            "order": section.order,
            "is_locked": section_locked,
            "completed_lessons": len([lesson for lesson in lessons if lesson.id in completed_ids]),
            "total_lessons": len(lessons),
            "passed_quizzes": len([quiz for quiz in quizzes if quiz.id in passed_ids]),
            "total_quizzes": len([quiz for quiz in quizzes if quiz.is_active]),
            "lessons": [
                {
                    "id": lesson.id,
                    "name": lesson.name,
                    "subject": lesson.subject,
                    "section_id": lesson.section_id,
                    "order": lesson.order,
                    "duration_minutes": lesson.duration_minutes,
                    "is_completed": lesson.id in completed_ids,
                    "is_locked": False if can_manage else not _content_unlocked(course, member, lesson),
                }
                for lesson in lessons
            ],
            "quizzes": [
                _serialize_quiz(quiz, member, locked=False if can_manage else not _quiz_unlocked(course, member, quiz))
                for quiz in quizzes
            ],
        })

    unsectioned_lessons = list(
        CourseContent.objects.filter(course_id=course, section__isnull=True, parent_id__isnull=True).order_by("order", "id")
    )
    unsectioned_quizzes = list(Quiz.objects.filter(course=course, section__isnull=True).order_by("order", "id"))
    if unsectioned_lessons or unsectioned_quizzes:
        section_payloads.append({
            "id": None,
            "title": "Materi Tambahan",
            "order": 9999,
            "is_locked": False if can_manage else not _section_unlocked(course, member, None),
            "completed_lessons": len([lesson for lesson in unsectioned_lessons if lesson.id in completed_ids]),
            "total_lessons": len(unsectioned_lessons),
            "passed_quizzes": len([quiz for quiz in unsectioned_quizzes if quiz.id in passed_ids]),
            "total_quizzes": len([quiz for quiz in unsectioned_quizzes if quiz.is_active]),
            "lessons": [
                {
                    "id": lesson.id,
                    "name": lesson.name,
                    "subject": lesson.subject,
                    "section_id": None,
                    "order": lesson.order,
                    "duration_minutes": lesson.duration_minutes,
                    "is_completed": lesson.id in completed_ids,
                    "is_locked": False if can_manage else not _content_unlocked(course, member, lesson),
                }
                for lesson in unsectioned_lessons
            ],
            "quizzes": [
                _serialize_quiz(quiz, member, locked=False if can_manage else not _quiz_unlocked(course, member, quiz))
                for quiz in unsectioned_quizzes
            ],
        })

    total_lessons = CourseContent.objects.filter(course_id=course, parent_id__isnull=True).count()
    completed_lessons = len(completed_ids.intersection(set(CourseContent.objects.filter(course_id=course).values_list("id", flat=True))))
    progress_percent = round(completed_lessons / total_lessons * 100, 2) if total_lessons else 0.0
    return {
        "course_id": course.id,
        "enrollment_id": member.id if member else None,
        "progress_percent": progress_percent,
        "sections": section_payloads,
    }


@api.get(
    "/courses/{course_id}/contents/{content_id}/learn",
    auth=api_auth,
    response={200: ContentOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    tags=["Learning"],
    summary="Detail lesson untuk reader student dengan validasi lock",
)
def learn_content_detail(request, course_id: int, content_id: int):
    course = get_object_or_404(Course, id=course_id)
    member = _require_course_learning_access(request, course)
    content = get_object_or_404(CourseContent, id=content_id, course_id=course)
    if not is_course_owner_or_admin(request.user, course) and not _content_unlocked(course, member, content):
        raise HttpError(403, "Selesaikan materi sebelumnya terlebih dahulu sebelum membuka lesson ini")
    log_learning_activity(request.user, course.id, "view_lesson", {"content_id": content.id})
    return serialize_content(content)


@api.get(
    "/courses/{course_id}/quizzes",
    auth=api_auth,
    response={200: list[QuizOut], 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    tags=["Quizzes"],
    summary="List kuis pada course",
)
def list_course_quizzes(request, course_id: int):
    course = get_object_or_404(Course, id=course_id)
    member = _require_course_learning_access(request, course)
    can_manage = is_course_owner_or_admin(request.user, course)
    quizzes = Quiz.objects.filter(course=course).order_by("section__order", "order", "id")
    return [
        _serialize_quiz(quiz, member, locked=False if can_manage else not _quiz_unlocked(course, member, quiz))
        for quiz in quizzes
    ]


@api.post(
    "/courses/{course_id}/quizzes",
    auth=api_auth,
    response={201: QuizOut, 400: ErrorOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    tags=["Quizzes"],
    summary="Buat kuis baru oleh instructor/admin",
)
def create_quiz(request, course_id: int, data: QuizIn):
    course = get_object_or_404(Course, id=course_id)
    if not is_course_owner_or_admin(request.user, course):
        raise HttpError(403, "Hanya owner course atau admin yang boleh membuat kuis")
    if data.minimum_score < 0 or data.minimum_score > 100:
        raise HttpError(400, "minimum_score harus 0-100")
    if data.question_count < 1:
        raise HttpError(400, "question_count minimal 1")
    section = None
    if data.section_id is not None:
        section = get_object_or_404(CourseSection, id=data.section_id, course=course)
    order = data.order or ((Quiz.objects.filter(course=course, section=section).count()) + 1)
    quiz = Quiz.objects.create(
        course=course,
        section=section,
        title=data.title,
        description=data.description,
        order=order,
        minimum_score=data.minimum_score,
        question_count=data.question_count,
        is_active=data.is_active,
        created_by=request.user,
    )
    log_activity(request.user, "create_quiz", {"course_id": course.id, "quiz_id": quiz.id})
    return 201, _serialize_quiz(quiz, _member_for_user(course, request.user))


@api.patch(
    "/courses/{course_id}/quizzes/{quiz_id}",
    auth=api_auth,
    response={200: QuizOut, 400: ErrorOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    tags=["Quizzes"],
    summary="Update kuis",
)
def update_quiz(request, course_id: int, quiz_id: int, data: QuizUpdateIn):
    course = get_object_or_404(Course, id=course_id)
    if not is_course_owner_or_admin(request.user, course):
        raise HttpError(403, "Hanya owner course atau admin yang boleh mengubah kuis")
    quiz = get_object_or_404(Quiz, id=quiz_id, course=course)
    if data.title is not None:
        quiz.title = data.title
    if data.description is not None:
        quiz.description = data.description
    if data.section_id is not None:
        quiz.section = get_object_or_404(CourseSection, id=data.section_id, course=course)
    if data.order is not None:
        if data.order < 1:
            raise HttpError(400, "order minimal 1")
        quiz.order = data.order
    if data.minimum_score is not None:
        if data.minimum_score < 0 or data.minimum_score > 100:
            raise HttpError(400, "minimum_score harus 0-100")
        quiz.minimum_score = data.minimum_score
    if data.question_count is not None:
        if data.question_count < 1:
            raise HttpError(400, "question_count minimal 1")
        quiz.question_count = data.question_count
    if data.is_active is not None:
        quiz.is_active = data.is_active
    quiz.save()
    log_activity(request.user, "update_quiz", {"course_id": course.id, "quiz_id": quiz.id})
    return _serialize_quiz(quiz, _member_for_user(course, request.user))


@api.delete(
    "/courses/{course_id}/quizzes/{quiz_id}",
    auth=api_auth,
    response={200: MessageOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    tags=["Quizzes"],
    summary="Hapus kuis",
)
def delete_quiz(request, course_id: int, quiz_id: int):
    course = get_object_or_404(Course, id=course_id)
    if not is_course_owner_or_admin(request.user, course):
        raise HttpError(403, "Hanya owner course atau admin yang boleh menghapus kuis")
    quiz = get_object_or_404(Quiz, id=quiz_id, course=course)
    quiz.delete()
    log_activity(request.user, "delete_quiz", {"course_id": course.id, "quiz_id": quiz_id})
    return {"message": "Kuis berhasil dihapus"}


@api.get(
    "/courses/{course_id}/quizzes/{quiz_id}/questions",
    auth=api_auth,
    response={200: list[QuizQuestionBankOut], 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    tags=["Question Bank"],
    summary="List question bank kuis beserta kunci jawaban",
)
def list_quiz_questions(request, course_id: int, quiz_id: int):
    course = get_object_or_404(Course, id=course_id)
    if not is_course_owner_or_admin(request.user, course):
        raise HttpError(403, "Hanya owner course atau admin yang boleh melihat question bank")
    quiz = get_object_or_404(Quiz, id=quiz_id, course=course)
    return [_serialize_quiz_question(q, include_answer=True) for q in quiz.questions.all()]


@api.post(
    "/courses/{course_id}/quizzes/{quiz_id}/questions",
    auth=api_auth,
    response={201: QuizQuestionBankOut, 400: ErrorOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    tags=["Question Bank"],
    summary="Tambah soal ke question bank kuis",
)
def create_quiz_question(request, course_id: int, quiz_id: int, data: QuizQuestionIn):
    course = get_object_or_404(Course, id=course_id)
    if not is_course_owner_or_admin(request.user, course):
        raise HttpError(403, "Hanya owner course atau admin yang boleh menambah soal")
    quiz = get_object_or_404(Quiz, id=quiz_id, course=course)
    choices = _validate_question_payload(data)
    question = QuizQuestion.objects.create(
        quiz=quiz,
        question_text=data.question_text,
        choices=choices,
        correct_answer=data.correct_answer,
        explanation=data.explanation,
        points=data.points,
    )
    log_activity(request.user, "create_quiz_question", {"course_id": course.id, "quiz_id": quiz.id, "question_id": question.id})
    return 201, _serialize_quiz_question(question, include_answer=True)


@api.patch(
    "/courses/{course_id}/quizzes/{quiz_id}/questions/{question_id}",
    auth=api_auth,
    response={200: QuizQuestionBankOut, 400: ErrorOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    tags=["Question Bank"],
    summary="Update soal question bank",
)
def update_quiz_question(request, course_id: int, quiz_id: int, question_id: int, data: QuizQuestionUpdateIn):
    course = get_object_or_404(Course, id=course_id)
    if not is_course_owner_or_admin(request.user, course):
        raise HttpError(403, "Hanya owner course atau admin yang boleh mengubah soal")
    quiz = get_object_or_404(Quiz, id=quiz_id, course=course)
    question = get_object_or_404(QuizQuestion, id=question_id, quiz=quiz)
    if data.question_text is not None:
        question.question_text = data.question_text
    if data.choices is not None:
        choices = [str(choice).strip() for choice in data.choices if str(choice).strip()]
        if len(choices) < 2:
            raise HttpError(400, "Minimal pilihan jawaban adalah 2")
        question.choices = choices
    if data.correct_answer is not None:
        question.correct_answer = data.correct_answer
    if question.correct_answer not in (question.choices or []):
        raise HttpError(400, "correct_answer harus sama persis dengan salah satu choices")
    if data.explanation is not None:
        question.explanation = data.explanation
    if data.points is not None:
        if data.points < 1:
            raise HttpError(400, "points minimal 1")
        question.points = data.points
    question.save()
    log_activity(request.user, "update_quiz_question", {"course_id": course.id, "quiz_id": quiz.id, "question_id": question.id})
    return _serialize_quiz_question(question, include_answer=True)


@api.delete(
    "/courses/{course_id}/quizzes/{quiz_id}/questions/{question_id}",
    auth=api_auth,
    response={200: MessageOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    tags=["Question Bank"],
    summary="Hapus soal dari question bank",
)
def delete_quiz_question(request, course_id: int, quiz_id: int, question_id: int):
    course = get_object_or_404(Course, id=course_id)
    if not is_course_owner_or_admin(request.user, course):
        raise HttpError(403, "Hanya owner course atau admin yang boleh menghapus soal")
    quiz = get_object_or_404(Quiz, id=quiz_id, course=course)
    question = get_object_or_404(QuizQuestion, id=question_id, quiz=quiz)
    question.delete()
    log_activity(request.user, "delete_quiz_question", {"course_id": course.id, "quiz_id": quiz.id, "question_id": question_id})
    return {"message": "Soal berhasil dihapus"}


@api.post(
    "/quizzes/{quiz_id}/start",
    auth=api_auth,
    response={201: QuizAttemptStartOut, 400: ErrorOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    tags=["Quiz Attempts"],
    summary="Student memulai kuis dengan soal acak dari question bank",
)
@require_student
def start_quiz_attempt(request, quiz_id: int):
    quiz = get_object_or_404(Quiz.objects.select_related("course", "section"), id=quiz_id, is_active=True)
    course = quiz.course
    member = _member_for_user(course, request.user)
    if member is None:
        raise HttpError(403, "Anda harus enroll ke course ini terlebih dahulu")
    if not _quiz_unlocked(course, member, quiz):
        raise HttpError(403, "Selesaikan materi/section sebelumnya terlebih dahulu sebelum membuka kuis ini")

    status = _quiz_attempt_status(quiz, member)
    if status["passed"]:
        raise HttpError(400, "Anda sudah lulus kuis ini")
    if not status["can_attempt"]:
        raise HttpError(403, status["message"] or "Anda belum bisa memulai kuis saat ini")

    questions = list(quiz.questions.all())
    if not questions:
        raise HttpError(400, "Question bank kuis ini masih kosong")
    random.shuffle(questions)
    selected_questions = questions[:min(quiz.question_count, len(questions))]

    with transaction.atomic():
        attempt_number = QuizAttempt.objects.filter(quiz=quiz, member=member).count() + 1
        attempt = QuizAttempt.objects.create(quiz=quiz, member=member, attempt_number=attempt_number)
        QuizAttemptAnswer.objects.bulk_create([
            QuizAttemptAnswer(attempt=attempt, question=question) for question in selected_questions
        ])

    log_learning_activity(request.user, course.id, "quiz_started", {"quiz_id": quiz.id, "attempt_id": attempt.id})
    return 201, {
        "attempt_id": attempt.id,
        "quiz_id": quiz.id,
        "quiz_title": quiz.title,
        "minimum_score": quiz.minimum_score,
        "attempt_number": attempt.attempt_number,
        "questions": [
            {
                "id": question.id,
                "question_text": question.question_text,
                "choices": question.choices or [],
                "points": question.points,
            }
            for question in selected_questions
        ],
    }


@api.post(
    "/quizzes/{quiz_id}/attempts/{attempt_id}/submit",
    auth=api_auth,
    response={200: QuizAttemptResultOut, 400: ErrorOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    tags=["Quiz Attempts"],
    summary="Submit jawaban kuis student",
)
@require_student
def submit_quiz_attempt(request, quiz_id: int, attempt_id: int, data: QuizSubmitIn):
    quiz = get_object_or_404(Quiz, id=quiz_id, is_active=True)
    member = _member_for_user(quiz.course, request.user)
    if member is None:
        raise HttpError(403, "Anda harus enroll ke course ini terlebih dahulu")
    attempt = get_object_or_404(QuizAttempt, id=attempt_id, quiz=quiz, member=member)
    if attempt.submitted_at is not None:
        raise HttpError(400, "Attempt ini sudah disubmit")

    answer_map = {item.question_id: item.selected_answer for item in data.answers}
    attempt_answers = list(attempt.answers.select_related("question"))
    if not attempt_answers:
        raise HttpError(400, "Attempt tidak memiliki soal")

    total_points = sum(answer.question.points for answer in attempt_answers)
    earned_points = 0
    correct_count = 0
    for answer in attempt_answers:
        selected = str(answer_map.get(answer.question_id, "")).strip()
        answer.selected_answer = selected
        answer.is_correct = selected == answer.question.correct_answer
        if answer.is_correct:
            earned_points += answer.question.points
            correct_count += 1

    QuizAttemptAnswer.objects.bulk_update(attempt_answers, ["selected_answer", "is_correct"])
    score = round((earned_points / total_points) * 100, 2) if total_points > 0 else 0
    passed = score >= quiz.minimum_score

    cooldown_until = None
    message = "Selamat, Anda lulus kuis ini." if passed else "Nilai belum mencapai batas minimum."
    if not passed:
        now = timezone.now()
        window_start = now - timedelta(minutes=QUIZ_COOLDOWN_MINUTES)
        failed_before = QuizAttempt.objects.filter(
            quiz=quiz,
            member=member,
            passed=False,
            submitted_at__gte=window_start,
        ).count()
        if failed_before + 1 >= QUIZ_MAX_FAILED_ATTEMPTS:
            cooldown_until = now + timedelta(minutes=QUIZ_COOLDOWN_MINUTES)
            message = "Anda bisa menelusuri ulang materi-materi sebelumnya sebelum memulai kembali."

    attempt.mark_submitted(score=score, passed=passed, cooldown_until=cooldown_until)
    invalidate_dashboard_cache(request.user.id)
    if passed and _course_completed_by_member(quiz.course, member):
        generate_certificate.delay(member.id)

    status = _quiz_attempt_status(quiz, member)
    log_learning_activity(request.user, quiz.course_id, "quiz_submitted", {"quiz_id": quiz.id, "attempt_id": attempt.id, "score": score, "passed": passed})
    return {
        "attempt_id": attempt.id,
        "quiz_id": quiz.id,
        "score": float(score),
        "correct_count": correct_count,
        "total_questions": len(attempt_answers),
        "passed": passed,
        "minimum_score": quiz.minimum_score,
        "remaining_attempts": status["remaining_attempts"],
        "cooldown_until": status["cooldown_until"],
        "message": message,
    }


# =============================================================================
# 11. CHATBOT ASSISTANT
# =============================================================================

@api.post(
    "/chatbot",
    auth=api_auth,
    response={200: ChatbotOut, 400: ErrorOut, 401: ErrorOut, 403: ErrorOut},
    tags=["Chatbot"],
    summary="AI Chatbot Assistant for Students",
)
@require_student
def chatbot_assistant(request, data: ChatbotIn):
    import json
    import urllib.request
    import urllib.error
    
    user_message = data.message.strip()
    if not user_message:
        raise HttpError(400, "Pesan tidak boleh kosong")
    
    # 1. Dapatkan daftar kursus yang aktif/published untuk context
    courses = Course.objects.filter(status="published").select_related("teacher", "category")
    course_list = []
    for c in courses:
        cat_name = c.category.name if c.category else "Tanpa Kategori"
        teacher_name = f"{c.teacher.first_name} {c.teacher.last_name}".strip() or c.teacher.username
        course_list.append(
            f"- {c.name} (Level: {c.level}) - Kategori: {cat_name} - Harga: Rp {c.price} - Instruktur: {teacher_name}. Deskripsi: {c.description}"
        )
    courses_context = "\n".join(course_list)
    
    # 2. Cek apakah GEMINI_API_KEY ada di environment
    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    
    if not gemini_api_key:
        # Fallback offline: Lakukan pencarian kata kunci sederhana dari database
        matching_courses = []
        words = user_message.lower().split()
        for word in words:
            if len(word) > 2:  # cari kata kunci yang cukup panjang
                # cari course yang memiliki kecocokan nama atau deskripsi
                matched = Course.objects.filter(
                    Q(name__icontains=word) | Q(description__icontains=word),
                    status="published"
                ).select_related("teacher")
                matching_courses.extend(matched)
        
        # Remove duplicates
        unique_matches = []
        seen_ids = set()
        for c in matching_courses:
            if c.id not in seen_ids:
                seen_ids.add(c.id)
                unique_matches.append(c)
                
        if unique_matches:
            recs = []
            for c in unique_matches[:3]:
                t_name = f"{c.teacher.first_name} {c.teacher.last_name}".strip() or c.teacher.username
                recs.append(f"- **{c.name}** (Level: {c.level}, Harga: Rp {c.price}) oleh {t_name}")
            course_recommendations = "\n".join(recs)
            
            response_text = (
                "[Demo Mode - GEMINI_API_KEY belum dikonfigurasi di file .env]\n\n"
                f"Halo! Saya mendeteksi Anda mencari kursus terkait. Berikut beberapa rekomendasi dari database kami:\n\n"
                f"{course_recommendations}\n\n"
                "Untuk mengaktifkan asisten AI pintar Gemini, silakan konfigurasikan kunci API `GEMINI_API_KEY` di file `.env` backend Anda."
            )
        else:
            response_text = (
                "[Demo Mode - GEMINI_API_KEY belum dikonfigurasi di file .env]\n\n"
                "Halo! Saya adalah asisten virtual Simple LMS. Untuk saat ini, kunci API Gemini belum dikonfigurasi. "
                "Namun, Anda dapat melihat daftar kursus secara lengkap di halaman utama (Dashboard/Course) atau "
                "mengonfigurasikan `GEMINI_API_KEY` pada file `.env` di backend untuk mengaktifkan AI."
            )
        return {"response": response_text}
        
    # 3. Request ke Gemini API
    # Kita akan mencoba beberapa model alternatif jika model utama sedang padat (high demand)
    candidate_models = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-flash-latest"]
    
    system_instruction = (
        "Anda adalah AI Chatbot Asisten untuk platform e-learning bernama Simple LMS. "
        "Tugas Anda adalah membantu siswa (Student) menemukan dan merekomendasikan kursus yang sesuai, "
        "serta menjawab pertanyaan seputar materi belajar secara ringkas, ramah, dan solutif.\n\n"
        "Berikut adalah daftar kursus yang tersedia saat ini di Simple LMS:\n"
        f"{courses_context}\n\n"
        "Instruksi tambahan:\n"
        "1. Jawablah menggunakan Bahasa Indonesia yang ramah dan interaktif.\n"
        "2. Jika pengguna mencari atau menanyakan tentang kursus/topik tertentu, rekomendasikan kursus yang paling relevan dari daftar di atas. Cantumkan nama kursus, harga, instruktur, dan deskripsi singkat mengapa cocok untuk mereka.\n"
        "3. Jika tidak ada kursus yang secara langsung cocok, katakan dengan ramah bahwa saat ini kursus tersebut belum tersedia, namun berikan saran kursus lain yang terdekat atau tawarkan bantuan belajar umum.\n"
        "4. Buat jawaban Anda ringkas, terstruktur (gunakan bullet points jika merekomendasikan beberapa), dan mudah dipahami."
    )
    
    prompt = f"{system_instruction}\n\nPertanyaan Pengguna: {user_message}\nJawaban:"
    
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }
        ]
    }
    
    response_text = None
    last_error_message = ""
    
    for model_name in candidate_models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_api_key}"
        
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        
        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                response_text = res_data["candidates"][0]["content"]["parts"][0]["text"]
                break  # Berhasil! Keluar dari loop
        except urllib.error.HTTPError as e:
            error_msg = e.read().decode("utf-8")
            try:
                error_json = json.loads(error_msg)
                last_error_message = error_json.get("error", {}).get("message", f"HTTP {e.code}")
            except Exception:
                last_error_message = f"Error HTTP {e.code}"
            
            # Jika API key tidak valid, langsung keluar agar tidak membuang waktu mencoba model lain
            if any(x in last_error_message.lower() for x in ["key", "api_key", "not valid", "unauthorized"]):
                break
            continue  # Coba model alternatif berikutnya
        except Exception as e:
            last_error_message = str(e)
            continue  # Coba model alternatif berikutnya

    if response_text:
        return {"response": response_text}
        
    # 4. Graceful Fallback ke Pencarian Database Lokal (jika semua request AI gagal / limit terlampaui)
    matching_courses = []
    STOP_WORDS = {
        "rekomendasi", "belajar", "kursus", "kelas", "saya", "ingin", "cari", "tahu", "tentang", 
        "materi", "dosen", "kuliah", "tanya", "bagaimana", "cara", "yang", "untuk", "adalah",
        "dengan", "pada", "oleh", "atau", "dan", "dari", "bisa", "dapat", "course", "apa", "itu",
        "tolong", "bantu", "halo", "hai", "selamat", "pagi", "siang", "sore", "malam"
    }
    words = [w for w in user_message.lower().split() if w not in STOP_WORDS and len(w) > 2]
    
    # Fallback jika kata kunci kosong setelah difilter stop words
    if not words:
        words = [w for w in user_message.lower().split() if len(w) > 2]
        
    for word in words:
        matched = Course.objects.filter(
            Q(name__icontains=word) | Q(description__icontains=word),
            status="published"
        ).select_related("teacher")
        matching_courses.extend(matched)
        
    # Remove duplicates
    unique_matches = []
    seen_ids = set()
    for c in matching_courses:
        if c.id not in seen_ids:
            seen_ids.add(c.id)
            unique_matches.append(c)
            
    # Cek tipe error
    is_key_invalid = any(x in last_error_message.lower() for x in ["key", "api_key", "not valid", "unauthorized"])
    
    if is_key_invalid:
        prefix = "[Error - Kunci API Gemini Tidak Valid]\n\n"
        suffix = "\n\n*(Silakan periksa kunci API `GEMINI_API_KEY` Anda di file `.env` backend)*"
    else:
        prefix = "[Layanan AI Padat - Hasil Pencarian Database]\n\n"
        suffix = f"\n\n*(Catatan: Asisten AI sedang padat. Menampilkan hasil database lokal. Error: {last_error_message})*"

    if unique_matches:
        recs = []
        for c in unique_matches[:3]:
            t_name = f"{c.teacher.first_name} {c.teacher.last_name}".strip() or c.teacher.username
            recs.append(f"- **{c.name}** (Level: {c.level}, Harga: Rp {c.price}) oleh {t_name}")
        course_recommendations = "\n".join(recs)
        
        response_text = (
            f"{prefix}"
            f"Halo! Layanan AI Gemini saat ini sedang mengalami lalu lintas tinggi (high demand). "
            f"Sebagai alternatif, berikut rekomendasi kursus yang relevan dari database kami:\n\n"
            f"{course_recommendations}"
            f"{suffix}"
        )
    else:
        response_text = (
            f"{prefix}"
            f"Halo! Layanan AI Gemini saat ini sedang mengalami lalu lintas tinggi (high demand). "
            f"Saya tidak menemukan kursus yang cocok secara spesifik dengan kata kunci Anda di database kami saat ini. "
            f"Silakan coba kirim pesan Anda beberapa saat lagi."
            f"{suffix}"
        )
        
    return {"response": response_text}


