from datetime import datetime
from typing import Optional, List

from ninja import Schema


class MessageOut(Schema):
    message: str


class ErrorOut(Schema):
    detail: str


# AUTH SCHEMAS

class RegisterIn(Schema):
    username: str
    password: str
    email: str
    first_name: str = ""
    last_name: str = ""


class LoginIn(Schema):
    username: str
    password: str


class RefreshIn(Schema):
    refresh: str


class TokenOut(Schema):
    access: str
    refresh: str


class AccessTokenOut(Schema):
    access: str


class UserOut(Schema):
    id: int
    username: str
    email: str
    first_name: str
    last_name: str
    roles: List[str]


class UserUpdateIn(Schema):
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None


# CATEGORY SCHEMAS

class CategoryOut(Schema):
    id: int
    name: str
    description: str
    slug: str


class CategoryIn(Schema):
    name: str
    description: str = "-"
    slug: str = ""


class CategoryUpdateIn(Schema):
    name: Optional[str] = None
    description: Optional[str] = None
    slug: Optional[str] = None


class PaginatedCategoryOut(Schema):
    total: int
    page: int
    page_size: int
    data: List[CategoryOut]


# COURSE SCHEMAS

class TeacherOut(Schema):
    id: int
    username: str
    first_name: str
    last_name: str
    email: str


class CourseIn(Schema):
    name: str
    description: str = "-"
    price: int
    image: Optional[str] = ""
    category_id: Optional[int] = None


class CourseUpdateIn(Schema):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[int] = None
    image: Optional[str] = None
    category_id: Optional[int] = None


class CourseOut(Schema):
    id: int
    name: str
    description: str
    price: int
    image: Optional[str] = None
    category: Optional[CategoryOut] = None
    teacher: TeacherOut
    created_at: datetime
    updated_at: datetime


class PaginatedCourseOut(Schema):
    total: int
    page: int
    page_size: int
    data: List[CourseOut]


# ENROLLMENT SCHEMAS

class EnrollmentIn(Schema):
    course_id: int


class EnrollmentOut(Schema):
    id: int
    course_id: int
    course_name: str
    user_id: int
    username: str
    roles: str


class ProgressIn(Schema):
    content_id: int


class ProgressOut(Schema):
    id: int
    enrollment_id: int
    content_id: int
    content_name: str
    is_completed: bool
    completed_at: datetime


# CONTENT / LESSON SCHEMAS

class ContentIn(Schema):
    name: str
    description: str = "-"
    video_url: Optional[str] = None
    parent_id: Optional[int] = None


class ContentUpdateIn(Schema):
    name: Optional[str] = None
    description: Optional[str] = None
    video_url: Optional[str] = None
    parent_id: Optional[int] = None


class ContentOut(Schema):
    id: int
    name: str
    description: str
    video_url: Optional[str] = None
    file_attachment: Optional[str] = None
    course_id: int
    parent_id: Optional[int] = None


class PaginatedContentOut(Schema):
    total: int
    page: int
    page_size: int
    data: List[ContentOut]


# ASYNC / REPORT SCHEMAS

class TaskOut(Schema):
    task_id: str
    status: str
    message: str = ""


class TaskStatusOut(Schema):
    task_id: str
    status: str
    result: Optional[dict] = None


# PAGINATION SCHEMAS

class PaginatedEnrollmentOut(Schema):
    total: int
    page: int
    page_size: int
    data: List[EnrollmentOut]


# FILE UPLOAD SCHEMAS

class FileUploadOut(Schema):
    content_id: int
    filename: str
    url: str
    size: Optional[int] = None
