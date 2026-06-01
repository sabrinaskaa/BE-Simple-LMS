import math
from typing import Optional

import jwt
from celery.result import AsyncResult
from django.contrib.auth import authenticate
from django.contrib.auth.models import Group, User
from django.db.models import Q
from ninja import NinjaAPI
from ninja.errors import HttpError

from .auth import api_auth, create_token, decode_token
from .cache import (
    cache_get,
    cache_set,
    course_detail_cache_key,
    course_list_cache_key,
    invalidate_course_cache,
)
from .models import Course, CourseMember, CourseContent, LessonProgress
from .mongo import get_activity_report, get_learning_report, log_activity, log_learning_activity
from .permissions import require_admin, require_instructor, require_student, is_admin, user_roles
from .rate_limit import rate_limit
from .schemas import (
    AccessTokenOut,
    CourseIn,
    CourseOut,
    CourseUpdateIn,
    EnrollmentIn,
    EnrollmentOut,
    ErrorOut,
    LoginIn,
    MessageOut,
    PaginatedCourseOut,
    ProgressIn,
    ProgressOut,
    RefreshIn,
    RegisterIn,
    TaskOut,
    TaskStatusOut,
    TokenOut,
    UserOut,
    UserUpdateIn,
)
from .tasks import (
    export_course_report,
    generate_certificate,
    send_enrollment_email,
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
    return {
        "id": course.id,
        "name": course.name,
        "description": course.description,
        "price": course.price,
        "image": course.image.url if course.image else None,
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
    return 201, serialize_user(user)


@api.post("/auth/login", response={200: TokenOut, 401: ErrorOut, 429: ErrorOut}, tags=["Authentication"])
@rate_limit(limit=60, window=60, prefix="login")
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
@rate_limit(limit=60, window=60, prefix="courses")
def list_courses(
    request,
    search: Optional[str] = None,
    min_price: Optional[int] = None,
    max_price: Optional[int] = None,
    ordering: str = "-created_at",
    page: int = 1,
    page_size: int = 10,
):
    allowed_ordering = {"name", "-name", "price", "-price", "created_at", "-created_at"}
    if ordering not in allowed_ordering:
        raise HttpError(400, "Parameter ordering tidak valid")

    page = max(page, 1)
    page_size = max(min(page_size, 100), 1)
    cache_key = course_list_cache_key(search, min_price, max_price, ordering, page, page_size)
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    qs = Course.objects.select_related("teacher").all()
    if search:
        qs = qs.filter(Q(name__icontains=search) | Q(description__icontains=search))
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

    course = get_object_or_404(Course.objects.select_related("teacher"), id=course_id)
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

    course = Course.objects.create(
        name=data.name,
        description=data.description,
        price=data.price,
        image=data.image or "",
        teacher=request.user,
    )
    invalidate_course_cache(course.id)
    log_activity(request.user, "create_course", {"course_id": course.id})
    return 201, serialize_course(course)


@api.patch("/courses/{course_id}", auth=api_auth, response={200: CourseOut, 400: ErrorOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut}, tags=["Courses"])
def update_course(request, course_id: int, data: CourseUpdateIn):
    course = get_object_or_404(Course.objects.select_related("teacher"), id=course_id)
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
    return 201, serialize_enrollment(member)


@api.get("/enrollments/my-courses", auth=api_auth, response=list[EnrollmentOut], tags=["Enrollments"])
def my_courses(request):
    members = (
        CourseMember.objects.select_related("course_id", "user_id")
        .filter(user_id=request.user)
        .order_by("course_id__name")
    )
    log_activity(request.user, "view_my_courses", {})
    return [serialize_enrollment(member) for member in members]


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


@api.get("/reports/activity", auth=api_auth, tags=["Reports"])
@require_admin
def activity_report(request, limit: int = 20):
    return get_activity_report(limit=limit)


@api.get("/reports/learning", auth=api_auth, tags=["Reports"])
@require_admin
def learning_report(request, limit: int = 20):
    return get_learning_report(limit=limit)
