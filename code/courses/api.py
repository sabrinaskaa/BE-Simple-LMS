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
    CourseSection, LessonProgress, Wishlist,
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
    LoginIn,
    MessageOut,
    PaginatedCategoryOut,
    PaginatedContentOut,
    PaginatedCourseOut,
    PaginatedEnrollmentOut,
    PaginatedWishlistOut,
    ProgressIn,
    ProgressOut,
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
    WishlistIn,
    WishlistOut,
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
    obj = model.objects.filter(**kwargs).first()
    if obj is None:
        raise HttpError(404, f"{model.__name__} tidak ditemukan")
    return obj


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

    allowed_statuses = {"draft", "published", "archived"}
    if data.status not in allowed_statuses:
        raise HttpError(400, "Status tidak valid")

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
        status=data.status,
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
        allowed_statuses = {"draft", "published", "archived"}
        if data.status not in allowed_statuses:
            raise HttpError(400, "Status tidak valid")
        course.status = data.status

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
        .order_by("id")
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
    course = get_object_or_404(Course.objects.select_related("teacher"), id=course_id)
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

    content = CourseContent.objects.create(
        name=data.name,
        description=data.description,
        video_url=data.video_url,
        course_id=course,
        parent_id=parent,
        section=section,
        order=data.order,
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
    course = get_object_or_404(Course.objects.select_related("teacher"), id=course_id)
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
    if data.section_id is not None:
        section = get_object_or_404(CourseSection, id=data.section_id, course=course)
        content.section = section
    if data.order is not None:
        content.order = data.order
    if data.duration_minutes is not None:
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
    course = get_object_or_404(Course.objects.select_related("teacher"), id=course_id)
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
    member = get_object_or_404(CourseMember.objects.select_related("course_id", "user_id"), id=enrollment_id)
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
    """
    Trigger pembuatan laporan statistik course secara async.
    Kembalikan task_id untuk polling status.
    """
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
    """
    Cek status task generate_course_report.
    Poll endpoint ini hingga status == 'SUCCESS', lalu baca field 'result'.
    """
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
    course = get_object_or_404(Course.objects.select_related("teacher"), id=course_id)
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
    course = get_object_or_404(Course.objects.select_related("teacher"), id=course_id)
    if not is_course_owner_or_admin(request.user, course):
        raise HttpError(403, "Hanya owner course atau admin yang boleh membuat section")

    section = CourseSection.objects.create(
        course=course,
        title=data.title,
        order=data.order,
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
        lessons = section.contents.filter(parent_id__isnull=True).order_by("order")
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
    course = get_object_or_404(Course.objects.select_related("teacher"), id=course_id)
    if not is_course_owner_or_admin(request.user, course):
        raise HttpError(403, "Hanya owner course atau admin yang boleh mengupdate section")

    section = get_object_or_404(CourseSection, id=section_id, course=course)
    if data.title is not None:
        section.title = data.title
    if data.order is not None:
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
    course = get_object_or_404(Course.objects.select_related("teacher"), id=course_id)
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
    member = get_object_or_404(
        CourseMember.objects.select_related("course_id", "user_id"), id=enrollment_id
    )
    if member.user_id_id != request.user.id and not is_admin(request.user):
        raise HttpError(403, "Tidak boleh melihat progress enrollment milik user lain")

    course = member.course_id
    all_contents = CourseContent.objects.filter(course_id=course).select_related("section")
    completed_ids = set(
        LessonProgress.objects.filter(member=member, is_completed=True)
        .values_list("content_id", flat=True)
    )

    total_lessons = all_contents.count()
    completed_lessons = len([c for c in all_contents if c.id in completed_ids])
    progress_percent = round((completed_lessons / total_lessons * 100), 2) if total_lessons > 0 else 0.0

    # Build per-section breakdown
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
                }
            sections_map[sid]["total"] += 1
            if content.id in completed_ids:
                sections_map[sid]["completed"] += 1
        else:
            unsectioned_lessons.append(content)

    sections_out = [
        {
            "section_id": v["section_id"],
            "section_title": v["section_title"],
            "total_lessons": v["total"],
            "completed_lessons": v["completed"],
        }
        for v in sorted(sections_map.values(), key=lambda x: x["section_id"])
    ]

    # Append unsectioned lessons as a virtual section
    if unsectioned_lessons:
        unsectioned_completed = len([c for c in unsectioned_lessons if c.id in completed_ids])
        sections_out.append({
            "section_id": None,
            "section_title": "Tanpa Section",
            "total_lessons": len(unsectioned_lessons),
            "completed_lessons": unsectioned_completed,
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
    response={201: WishlistOut, 400: ErrorOut, 401: ErrorOut, 404: ErrorOut},
    tags=["Wishlist"],
    summary="Tambah course ke wishlist",
)
def add_to_wishlist(request, data: WishlistIn):
    course = get_object_or_404(Course, id=data.course_id)
    if Wishlist.objects.filter(user=request.user, course=course).exists():
        raise HttpError(400, "Course sudah ada di wishlist")

    wl = Wishlist.objects.create(user=request.user, course=course)
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

    # Wishlist count
    wishlist_count = Wishlist.objects.filter(user=user).count()

    # Recommended: top-5 rated courses, belum di-enroll, dari kategori yang sama
    enrolled_course_ids = set(enrollments.values_list("course_id_id", flat=True))
    recommended_qs = (
        Course.objects.filter(status="published")
        .exclude(id__in=enrolled_course_ids)
        .select_related("teacher")
        .order_by("-rating_avg")[:5]
    )
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

    recommended = [
        {
            "id": c.id,
            "name": c.name,
            "rating_avg": c.rating_avg,
            "total_reviews": c.total_reviews,
            "price": c.price,
            "instructor_name": c.teacher.get_full_name() or c.teacher.username,
        }
        for c in recommended_qs
    ]

    response = {
        "active_courses": active_courses,
        "completed_courses": completed_courses,
        "total_enrolled": len(active_courses) + len(completed_courses),
        "total_completed": len(completed_courses),
        "wishlist_count": wishlist_count,
        "recommended_courses": recommended,
    }

    # Cache selama 5 menit
    cache_set(cache_key, response, timeout=300)
    log_activity(user, "view_student_dashboard", {})
    return response
