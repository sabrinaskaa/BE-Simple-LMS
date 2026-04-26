import math
from typing import Optional

import jwt
from django.contrib.auth import authenticate
from django.contrib.auth.models import Group, User
from django.db import IntegrityError
from django.db.models import Q
from ninja import NinjaAPI
from ninja.errors import HttpError

from .auth import api_auth, create_token, decode_token
from .models import Course, CourseMember, CourseContent, LessonProgress
from .permissions import (
    require_admin,
    require_instructor,
    require_student,
    user_roles,
)
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
    TokenOut,
    UserOut,
    UserUpdateIn,
)


api = NinjaAPI(
    title="Simple LMS API",
    version="1.0.0",
    description="REST API Simple LMS dengan JWT Authentication dan RBAC",
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


# 1. AUTHENTICATION ENDPOINTS

@api.post(
    "/auth/register",
    response={201: UserOut, 400: ErrorOut},
    tags=["Authentication"],
)
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

    return 201, serialize_user(user)


@api.post(
    "/auth/login",
    response={200: TokenOut, 401: ErrorOut},
    tags=["Authentication"],
)
def login(request, data: LoginIn):
    user = authenticate(username=data.username, password=data.password)

    if user is None:
        raise HttpError(401, "Username atau password salah")

    return {
        "access": create_token(user, "access"),
        "refresh": create_token(user, "refresh"),
    }


@api.post(
    "/auth/refresh",
    response={200: AccessTokenOut, 401: ErrorOut},
    tags=["Authentication"],
)
def refresh_token(request, data: RefreshIn):
    try:
        payload = decode_token(data.refresh)

        if payload.get("token_type") != "refresh":
            raise HttpError(401, "Token bukan refresh token")

        user = User.objects.filter(id=payload.get("user_id")).first()

        if user is None:
            raise HttpError(401, "User tidak ditemukan")

        return {"access": create_token(user, "access")}

    except jwt.ExpiredSignatureError:
        raise HttpError(401, "Refresh token sudah expired")
    except jwt.InvalidTokenError:
        raise HttpError(401, "Refresh token tidak valid")


@api.get(
    "/auth/me",
    auth=api_auth,
    response={200: UserOut, 401: ErrorOut},
    tags=["Authentication"],
)
def get_me(request):
    return serialize_user(request.user)


@api.put(
    "/auth/me",
    auth=api_auth,
    response={200: UserOut, 401: ErrorOut},
    tags=["Authentication"],
)
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

    return serialize_user(user)


# 2. COURSES PUBLIC ENDPOINTS

@api.get(
    "/courses",
    response=PaginatedCourseOut,
    tags=["Courses"],
)
def list_courses(
    request,
    search: Optional[str] = None,
    min_price: Optional[int] = None,
    max_price: Optional[int] = None,
    page: int = 1,
    page_size: int = 10,
):
    qs = Course.objects.select_related("teacher").all().order_by("-created_at")

    if search:
        qs = qs.filter(
            Q(name__icontains=search)
            | Q(description__icontains=search)
        )

    if min_price is not None:
        qs = qs.filter(price__gte=min_price)

    if max_price is not None:
        qs = qs.filter(price__lte=max_price)

    total = qs.count()

    page = max(page, 1)
    page_size = max(min(page_size, 100), 1)

    start = (page - 1) * page_size
    end = start + page_size

    courses = qs[start:end]

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "data": [serialize_course(course) for course in courses],
    }


@api.get(
    "/courses/{course_id}",
    response={200: CourseOut, 404: ErrorOut},
    tags=["Courses"],
)
def detail_course(request, course_id: int):
    course = get_object_or_404(
        Course.objects.select_related("teacher"),
        id=course_id,
    )

    return serialize_course(course)


# 3. COURSES PROTECTED ENDPOINTS

@api.post(
    "/courses",
    auth=api_auth,
    response={201: CourseOut, 401: ErrorOut, 403: ErrorOut},
    tags=["Courses"],
)
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

    return 201, serialize_course(course)


@api.patch(
    "/courses/{course_id}",
    auth=api_auth,
    response={200: CourseOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    tags=["Courses"],
)
def update_course(request, course_id: int, data: CourseUpdateIn):
    course = get_object_or_404(
        Course.objects.select_related("teacher"),
        id=course_id,
    )

    is_owner = course.teacher_id == request.user.id
    is_admin_user = request.user.is_superuser or request.user.groups.filter(name="Admin").exists()

    if not (is_owner or is_admin_user):
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

    return serialize_course(course)


@api.delete(
    "/courses/{course_id}",
    auth=api_auth,
    response={200: MessageOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    tags=["Courses"],
)
@require_admin
def delete_course(request, course_id: int):
    course = get_object_or_404(Course, id=course_id)
    course.delete()

    return {"message": "Course berhasil dihapus"}


# 4. ENROLLMENTS ENDPOINTS

@api.post(
    "/enrollments",
    auth=api_auth,
    response={201: EnrollmentOut, 400: ErrorOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    tags=["Enrollments"],
)
@require_student
def enroll_to_course(request, data: EnrollmentIn):
    course = get_object_or_404(Course, id=data.course_id)

    if CourseMember.objects.filter(course_id=course, user_id=request.user).exists():
        raise HttpError(400, "Anda sudah terdaftar di course ini")

    member = CourseMember.objects.create(
        course_id=course,
        user_id=request.user,
        roles="std",
    )

    return 201, serialize_enrollment(member)


@api.get(
    "/enrollments/my-courses",
    auth=api_auth,
    response=list[EnrollmentOut],
    tags=["Enrollments"],
)
def my_courses(request):
    members = (
        CourseMember.objects
        .select_related("course_id", "user_id")
        .filter(user_id=request.user)
        .order_by("course_id__name")
    )

    return [serialize_enrollment(member) for member in members]


@api.post(
    "/enrollments/{enrollment_id}/progress",
    auth=api_auth,
    response={201: ProgressOut, 400: ErrorOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    tags=["Enrollments"],
)
def mark_lesson_complete(request, enrollment_id: int, data: ProgressIn):
    member = get_object_or_404(
        CourseMember.objects.select_related("course_id", "user_id"),
        id=enrollment_id,
    )

    if member.user_id_id != request.user.id:
        raise HttpError(403, "Anda tidak boleh mengubah progress enrollment milik user lain")

    content = get_object_or_404(
        CourseContent,
        id=data.content_id,
        course_id=member.course_id,
    )

    progress, created = LessonProgress.objects.get_or_create(
        member=member,
        content=content,
        defaults={"is_completed": True},
    )

    if not created:
        progress.is_completed = True
        progress.save()

    return 201, {
        "id": progress.id,
        "enrollment_id": member.id,
        "content_id": content.id,
        "content_name": content.name,
        "is_completed": progress.is_completed,
        "completed_at": progress.completed_at,
    }