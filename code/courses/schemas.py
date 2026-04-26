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


class CourseUpdateIn(Schema):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[int] = None
    image: Optional[str] = None


class CourseOut(Schema):
    id: int
    name: str
    description: str
    price: int
    image: Optional[str] = None
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