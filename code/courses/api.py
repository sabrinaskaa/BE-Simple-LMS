import math
import mimetypes
import os
from typing import Optional

import jwt
from celery.result import AsyncResult
from django.contrib.auth import authenticate
from django.contrib.auth.models import Group, User
from django.db import models as db_models
from django.db.models import Avg, Count, Q
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
    LessonProgress, Wishlist,
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

    allowed_statuses = {"draft", "published", "archived", None}
    if status not in allowed_statuses:
        raise HttpError(400, "Status tidak valid. Pilih: draft, published, archived")

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

    # Cek apakah ada field konten yang diubah (bukan status)
    content_fields_changed = any([
        data.name is not None,
        data.description is not None,
        data.price is not None,
        data.image is not None,
        data.category_id is not None,
        data.level is not None,
    ])

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
    if data.category_id is not None:
        course.category = get_object_or_404(Category, id=data.category_id)
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

    total_content = CourseContent.objects.filter(course_id=member.course_id).count()
    completed_content = LessonProgress.objects.filter(member=member, is_completed=True).count()
    if total_content > 0 and completed_content >= total_content:
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

_ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".mp4", ".png", ".jpg", ".jpeg"}
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
        raise HttpError(400, f"Tipe file tidak diizinkan. Ekstensi yang boleh: {', '.join(sorted(allowed_exts))}")


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

    content.file_attachment.save(file.name, file, save=True)
    log_activity(request.user, "upload_content_file", {"course_id": course_id, "content_id": content_id})
    return {
        "content_id": content.id,
        "filename": os.path.basename(content.file_attachment.name),
        "url": request.build_absolute_uri(content.file_attachment.url),
        "size": file.size if hasattr(file, 'size') else None,
    }


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
# 10. CHATBOT ASSISTANT
# =============================================================================

CHATBOT_STOP_WORDS = {
    "aku", "saya", "gua", "gw", "ingin", "mau", "pengen", "cari", "carikan",
    "rekomendasi", "rekomendasikan", "kursus", "course", "kelas", "materi",
    "belajar", "tentang", "untuk", "yang", "dan", "atau", "dari", "dengan",
    "pada", "di", "ke", "apa", "itu", "ini", "adalah", "bisa", "dapat",
    "tolong", "bantu", "halo", "hai", "hello", "selamat", "pagi", "siang",
    "sore", "malam", "bagaimana", "gimana", "cara", "dong", "ya", "min",
    "admin", "asisten", "lms", "simple", "ada", "adakah", "punya", "tersedia",
    "termurah", "murah", "paling", "harga", "termahal", "mahal", "gratis",
    "free", "terbaik", "rating", "populer", "popular"
}


def _chatbot_normalize_text(text: str) -> str:
    import re
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _chatbot_extract_keywords(message: str):
    import re

    normalized = _chatbot_normalize_text(message)

    aliases = {
        "js": "javascript",
        "java script": "javascript",
        "py": "python",
        "database": "basis data",
        "db": "basis data",
        "html": "html",
        "css": "css",
    }

    keywords = []

    for alias, canonical in aliases.items():
        if alias in normalized and canonical not in keywords:
            keywords.append(canonical)

    words = re.findall(r"[a-zA-Z0-9+#.]+", normalized)

    for word in words:
        if len(word) <= 2:
            continue
        if word in CHATBOT_STOP_WORDS:
            continue
        if word not in keywords:
            keywords.append(word)

    return keywords[:10]


def _chatbot_detect_intent(message: str) -> str:
    normalized = _chatbot_normalize_text(message)

    if any(word in normalized for word in ["termurah", "paling murah", "harga murah", "murah", "budget"]):
        return "cheapest"

    if any(word in normalized for word in ["termahal", "paling mahal", "harga mahal"]):
        return "most_expensive"

    if any(word in normalized for word in ["gratis", "free", "tanpa bayar"]):
        return "free"

    if any(word in normalized for word in ["terbaik", "rating tertinggi", "rating terbaik", "paling bagus"]):
        return "best_rating"

    if any(word in normalized for word in ["pemula", "beginner", "dasar"]):
        return "beginner"

    if any(word in normalized for word in ["intermediate", "menengah", "lanjutan"]):
        return "intermediate"

    if any(word in normalized for word in ["advanced", "mahir"]):
        return "advanced"

    if any(word in normalized for word in ["rekomendasi", "rekomendasikan", "cocok", "belajar", "kursus", "course", "kelas"]):
        return "recommendation"

    return "general"


def _chatbot_base_courses():
    return (
        Course.objects
        .filter(status="published")
        .select_related("teacher", "category")
    )


def _chatbot_teacher_name(course):
    teacher = getattr(course, "teacher", None)

    if not teacher:
        return "-"

    full_name = f"{teacher.first_name} {teacher.last_name}".strip()
    return full_name or teacher.username


def _chatbot_format_price(price):
    try:
        return f"Rp {int(price):,}".replace(",", ".")
    except Exception:
        return f"Rp {price}"


def _chatbot_level_label(level: str) -> str:
    labels = {
        "beginner": "Beginner",
        "intermediate": "Intermediate",
        "advanced": "Advanced",
    }

    return labels.get(level, level or "-")


def _chatbot_add_course(course_map: dict, course, match_note: str = ""):
    if not course:
        return

    course_id = course.id

    if course_id not in course_map:
        course_map[course_id] = {
            "course": course,
            "notes": [],
            "lessons": [],
            "sections": [],
        }

    if match_note and match_note not in course_map[course_id]["notes"]:
        course_map[course_id]["notes"].append(match_note)


def _chatbot_find_courses_by_keywords(keywords):
    course_map = {}

    if not keywords:
        return []

    course_query = Q()

    for keyword in keywords:
        course_query |= (
            Q(name__icontains=keyword)
            | Q(description__icontains=keyword)
            | Q(level__icontains=keyword)
            | Q(category__name__icontains=keyword)
            | Q(teacher__username__icontains=keyword)
            | Q(teacher__first_name__icontains=keyword)
            | Q(teacher__last_name__icontains=keyword)
        )

    direct_courses = (
        _chatbot_base_courses()
        .filter(course_query)
        .distinct()
        .order_by("price", "-rating_avg", "id")[:8]
    )

    for course in direct_courses:
        _chatbot_add_course(course_map, course, "Cocok dari nama/deskripsi/kategori course")

    content_query = Q()

    for keyword in keywords:
        content_query |= (
            Q(name__icontains=keyword)
            | Q(description__icontains=keyword)
            | Q(section__title__icontains=keyword)
        )

    matched_contents = (
        CourseContent.objects
        .filter(course_id__status="published")
        .filter(content_query)
        .select_related("course_id", "course_id__teacher", "course_id__category", "section")
        .order_by("course_id__price", "course_id__id", "section__order", "order", "id")[:20]
    )

    for content in matched_contents:
        course = content.course_id
        _chatbot_add_course(course_map, course, "Cocok dari section/lesson di dalam course")

        lesson_name = content.name
        section_title = content.section.title if content.section else "Tanpa section"
        lesson_text = f"{section_title} → {lesson_name}"

        if lesson_text not in course_map[course.id]["lessons"]:
            course_map[course.id]["lessons"].append(lesson_text)

    section_query = Q()

    for keyword in keywords:
        section_query |= Q(title__icontains=keyword)

    matched_sections = (
        CourseSection.objects
        .filter(course__status="published")
        .filter(section_query)
        .select_related("course", "course__teacher", "course__category")
        .order_by("course__price", "course__id", "order", "id")[:20]
    )

    for section in matched_sections:
        course = section.course
        _chatbot_add_course(course_map, course, "Cocok dari nama section")

        if section.title not in course_map[course.id]["sections"]:
            course_map[course.id]["sections"].append(section.title)

    results = list(course_map.values())
    results.sort(
        key=lambda item: (
            item["course"].price,
            -float(item["course"].rating_avg),
            item["course"].id,
        )
    )

    return results[:6]


def _chatbot_get_db_results(user_message: str):
    intent = _chatbot_detect_intent(user_message)
    keywords = _chatbot_extract_keywords(user_message)
    base_qs = _chatbot_base_courses()

    keyword_results = _chatbot_find_courses_by_keywords(keywords)
    keyword_course_ids = [item["course"].id for item in keyword_results]

    if intent == "cheapest":
        qs = base_qs

        if keyword_course_ids:
            qs = qs.filter(id__in=keyword_course_ids)

        courses = qs.order_by("price", "-rating_avg", "id")[:5]

        return intent, keywords, [
            {
                "course": course,
                "notes": ["Diurutkan dari harga termurah"],
                "lessons": [],
                "sections": [],
            }
            for course in courses
        ]

    if intent == "most_expensive":
        qs = base_qs

        if keyword_course_ids:
            qs = qs.filter(id__in=keyword_course_ids)

        courses = qs.order_by("-price", "-rating_avg", "id")[:5]

        return intent, keywords, [
            {
                "course": course,
                "notes": ["Diurutkan dari harga termahal"],
                "lessons": [],
                "sections": [],
            }
            for course in courses
        ]

    if intent == "free":
        qs = base_qs.filter(price=0)

        if keyword_course_ids:
            qs = qs.filter(id__in=keyword_course_ids)

        courses = qs.order_by("-rating_avg", "id")[:5]

        return intent, keywords, [
            {
                "course": course,
                "notes": ["Course gratis"],
                "lessons": [],
                "sections": [],
            }
            for course in courses
        ]

    if intent == "best_rating":
        qs = base_qs

        if keyword_course_ids:
            qs = qs.filter(id__in=keyword_course_ids)

        courses = qs.order_by("-rating_avg", "-total_reviews", "price", "id")[:5]

        return intent, keywords, [
            {
                "course": course,
                "notes": ["Diurutkan dari rating tertinggi"],
                "lessons": [],
                "sections": [],
            }
            for course in courses
        ]

    if intent in {"beginner", "intermediate", "advanced"}:
        level_map = {
            "beginner": "beginner",
            "intermediate": "intermediate",
            "advanced": "advanced",
        }

        qs = base_qs.filter(level=level_map[intent])

        if keyword_course_ids:
            qs = qs.filter(id__in=keyword_course_ids)

        courses = qs.order_by("price", "-rating_avg", "id")[:5]

        return intent, keywords, [
            {
                "course": course,
                "notes": [f"Level {_chatbot_level_label(course.level)}"],
                "lessons": [],
                "sections": [],
            }
            for course in courses
        ]

    if keyword_results:
        return intent, keywords, keyword_results

    courses = base_qs.order_by("price", "-rating_avg", "id")[:5]

    return intent, keywords, [
        {
            "course": course,
            "notes": ["Course published dari database"],
            "lessons": [],
            "sections": [],
        }
        for course in courses
    ]


def _chatbot_format_course_item(item, index: int = 1):
    course = item["course"]
    category_name = course.category.name if course.category else "Tanpa kategori"
    teacher_name = _chatbot_teacher_name(course)
    description = (course.description or "-").replace("\n", " ").strip()

    if len(description) > 140:
        description = description[:140] + "..."

    text = (
        f"{index}. **{course.name}**\n"
        f"   - Level: {_chatbot_level_label(course.level)}\n"
        f"   - Kategori: {category_name}\n"
        f"   - Harga: {_chatbot_format_price(course.price)}\n"
        f"   - Instruktur: {teacher_name}\n"
        f"   - Rating: {course.rating_avg} / 5.0 dari {course.total_reviews} review\n"
        f"   - Deskripsi: {description}"
    )

    if item.get("sections"):
        text += f"\n   - Section terkait: {', '.join(item['sections'][:3])}"

    if item.get("lessons"):
        text += f"\n   - Materi/lesson terkait: {', '.join(item['lessons'][:4])}"

    if item.get("notes"):
        text += f"\n   - Alasan cocok: {', '.join(item['notes'][:2])}"

    return text


def _chatbot_build_db_answer(user_message: str, intent: str, keywords, results):
    if not results:
        if intent == "free":
            return "Saat ini belum ada course gratis yang berstatus **published** di database."

        return "Saat ini belum ada course published yang cocok di database LMS."

    course_lines = [
        _chatbot_format_course_item(item, index=i + 1)
        for i, item in enumerate(results[:5])
    ]

    course_text = "\n\n".join(course_lines)

    if intent == "cheapest":
        first = results[0]["course"]

        opening = (
            "Berdasarkan data course **published** di database, course termurah saat ini adalah "
            f"**{first.name}** dengan harga **{_chatbot_format_price(first.price)}**."
        )

        if len(results) > 1:
            opening += "\n\nBerikut urutan course dari yang paling murah:"

        return f"{opening}\n\n{course_text}"

    if intent == "most_expensive":
        first = results[0]["course"]

        return (
            "Berdasarkan data course **published** di database, course termahal saat ini adalah "
            f"**{first.name}** dengan harga **{_chatbot_format_price(first.price)}**.\n\n"
            f"{course_text}"
        )

    if intent == "free":
        return f"Saya menemukan course gratis berikut dari database:\n\n{course_text}"

    if intent == "best_rating":
        return f"Berikut course dengan rating terbaik berdasarkan database:\n\n{course_text}"

    if intent in {"beginner", "intermediate", "advanced"}:
        return (
            f"Berikut course level {_chatbot_level_label(results[0]['course'].level)} "
            f"yang tersedia di database:\n\n{course_text}"
        )

    if keywords:
        keyword_text = ", ".join(keywords[:5])

        return (
            f"Saya mencocokkan pertanyaan Anda dengan database menggunakan kata kunci "
            f"**{keyword_text}**.\n\n"
            f"Hasil yang paling relevan:\n\n{course_text}"
        )

    return f"Berikut beberapa course published yang tersedia di database LMS:\n\n{course_text}"


def _chatbot_course_context_for_ai(results):
    if not results:
        return "Tidak ada course published yang cocok."

    lines = []

    for item in results[:6]:
        course = item["course"]
        category_name = course.category.name if course.category else "Tanpa kategori"
        teacher_name = _chatbot_teacher_name(course)
        lessons = "; ".join(item.get("lessons", [])[:5]) or "-"
        sections = "; ".join(item.get("sections", [])[:5]) or "-"
        description = (course.description or "-").replace("\n", " ")[:220]

        lines.append(
            f"- {course.name} | Level: {_chatbot_level_label(course.level)} | "
            f"Kategori: {category_name} | Harga: {_chatbot_format_price(course.price)} | "
            f"Instruktur: {teacher_name} | Rating: {course.rating_avg} | "
            f"Review: {course.total_reviews} | Section cocok: {sections} | "
            f"Lesson cocok: {lessons} | Deskripsi: {description}"
        )

    return "\n".join(lines)


def _chatbot_call_gemini(user_message: str, db_answer: str, db_context: str):
    import json
    import socket
    import urllib.error
    import urllib.request

    gemini_api_key = os.environ.get("GEMINI_API_KEY", "").strip()

    if not gemini_api_key:
        return None, "GEMINI_API_KEY belum dikonfigurasi"

    if gemini_api_key.lower() in {
        "none",
        "null",
        "changeme",
        "your-api-key",
        "isi-api-key-di-sini",
    }:
        return None, "GEMINI_API_KEY masih placeholder"

    model_names = []
    primary_model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()
    fallback_models = os.environ.get(
        "GEMINI_FALLBACK_MODELS",
        "gemini-2.5-flash,gemini-2.5-flash-lite,gemini-2.0-flash",
    )

    if primary_model:
        model_names.append(primary_model)

    model_names.extend([
        model.strip()
        for model in fallback_models.split(",")
        if model.strip()
    ])

    unique_models = []

    for model_name in model_names:
        if model_name not in unique_models:
            unique_models.append(model_name)

    system_instruction = (
        "Anda adalah asisten Simple LMS. Jawab dalam Bahasa Indonesia. "
        "Jawaban utama HARUS mengikuti hasil query database yang diberikan backend. "
        "Jangan mengganti nama course, harga, instruktur, level, section, atau lesson. "
        "Jangan mengarang course yang tidak ada pada DATABASE_CONTEXT. "
        "Jika DATABASE_ANSWER sudah cukup, cukup rapikan bahasanya tanpa mengubah fakta.\n\n"
        f"DATABASE_CONTEXT:\n{db_context}\n\n"
        f"DATABASE_ANSWER:\n{db_answer}"
    )

    payload = {
        "systemInstruction": {
            "parts": [
                {
                    "text": system_instruction
                }
            ]
        },
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": user_message
                    }
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "topP": 0.8,
            "maxOutputTokens": 700,
        },
    }

    timeout_seconds = int(os.environ.get("GEMINI_TIMEOUT_SECONDS", "15"))
    last_error = ""

    for model_name in unique_models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": gemini_api_key,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))

            candidates = data.get("candidates") or []

            for candidate in candidates:
                parts = (candidate.get("content") or {}).get("parts") or []
                text = "\n".join([
                    part.get("text", "")
                    for part in parts
                ]).strip()

                if text:
                    return text, ""

            last_error = f"Model {model_name} tidak mengembalikan teks"

        except urllib.error.HTTPError as error:
            raw = error.read().decode("utf-8", errors="ignore")
            last_error = f"HTTP {error.code}: {raw[:300]}"

            if error.code in [401, 403]:
                return None, "GEMINI_API_KEY tidak valid atau tidak punya izin"

            continue

        except (urllib.error.URLError, socket.timeout) as error:
            last_error = f"Koneksi/timeout Gemini: {error}"
            continue

        except Exception as error:
            last_error = f"Error Gemini: {error}"
            continue

    return None, last_error or "Gemini tidak mengembalikan jawaban"


@api.post(
    "/chatbot",
    auth=api_auth,
    response={200: ChatbotOut, 400: ErrorOut, 401: ErrorOut, 403: ErrorOut},
    tags=["Chatbot"],
    summary="AI Chatbot Assistant for Students",
)
@require_student
def chatbot_assistant(request, data: ChatbotIn):
    user_message = (data.message or "").strip()

    if not user_message:
        raise HttpError(400, "Pesan tidak boleh kosong")

    intent, keywords, results = _chatbot_get_db_results(user_message)
    db_answer = _chatbot_build_db_answer(user_message, intent, keywords, results)
    db_context = _chatbot_course_context_for_ai(results)

    # Untuk pertanyaan yang sifatnya data pasti dari database,
    # langsung return hasil DB agar Gemini tidak mengarang data.
    deterministic_intents = {
        "cheapest",
        "most_expensive",
        "free",
        "best_rating",
        "beginner",
        "intermediate",
        "advanced",
        "recommendation",
    }

    if intent in deterministic_intents or keywords:
        try:
            log_activity(
                request.user,
                "chatbot_db_first_response",
                {
                    "message": user_message[:200],
                    "intent": intent,
                    "keywords": keywords,
                    "result_count": len(results),
                },
            )
        except Exception:
            pass

        return {"response": db_answer}

    ai_response, ai_error = _chatbot_call_gemini(
        user_message=user_message,
        db_answer=db_answer,
        db_context=db_context,
    )

    if ai_response:
        try:
            log_activity(
                request.user,
                "chatbot_ai_response",
                {
                    "message": user_message[:200],
                    "intent": intent,
                    "keywords": keywords,
                    "result_count": len(results),
                },
            )
        except Exception:
            pass

        return {"response": ai_response}

    try:
        log_activity(
            request.user,
            "chatbot_db_fallback_response",
            {
                "message": user_message[:200],
                "intent": intent,
                "keywords": keywords,
                "result_count": len(results),
                "ai_error": ai_error[:300] if ai_error else "",
            },
        )
    except Exception:
        pass

    return {"response": db_answer}