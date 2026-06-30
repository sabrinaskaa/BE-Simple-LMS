from datetime import datetime
from decimal import Decimal
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
    level: str = "beginner"
    status: str = "published"


class CourseUpdateIn(Schema):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[int] = None
    image: Optional[str] = None
    category_id: Optional[int] = None
    level: Optional[str] = None
    status: Optional[str] = None


class CourseOut(Schema):
    id: int
    name: str
    description: str
    price: int
    level: str
    status: str
    image: Optional[str] = None
    category: Optional[CategoryOut] = None
    teacher: TeacherOut
    rating_avg: Decimal
    total_reviews: int
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
    section_id: Optional[int] = None
    # None = backend auto-assign order berikutnya dalam scope yang sama
    order: Optional[int] = None
    duration_minutes: Optional[int] = None


class ContentUpdateIn(Schema):
    name: Optional[str] = None
    description: Optional[str] = None
    video_url: Optional[str] = None
    parent_id: Optional[int] = None
    section_id: Optional[int] = None
    order: Optional[int] = None
    duration_minutes: Optional[int] = None


class ContentOut(Schema):
    id: int
    name: str
    description: str
    video_url: Optional[str] = None
    file_attachment: Optional[str] = None
    course_id: int
    parent_id: Optional[int] = None
    section_id: Optional[int] = None
    order: int
    duration_minutes: Optional[int] = None


class PaginatedContentOut(Schema):
    total: int
    page: int
    page_size: int
    data: List[ContentOut]


# SECTION SCHEMAS

class SectionIn(Schema):
    title: str
    # None = backend auto-assign order berikutnya dalam course
    order: Optional[int] = None


class SectionUpdateIn(Schema):
    title: Optional[str] = None
    order: Optional[int] = None


class SectionOut(Schema):
    id: int
    course_id: int
    title: str
    order: int
    created_at: datetime


class ContentInSectionOut(Schema):
    id: int
    name: str
    description: str
    video_url: Optional[str] = None
    order: int
    duration_minutes: Optional[int] = None


class SectionWithLessonsOut(Schema):
    id: int
    course_id: int
    title: str
    order: int
    total_lessons: int
    lessons: List[ContentInSectionOut]


# REVIEW SCHEMAS

class ReviewIn(Schema):
    rating: int
    review: str = ""


class ReviewOut(Schema):
    id: int
    course_id: int
    user_id: int
    username: str
    rating: int
    review: str
    created_at: datetime
    updated_at: datetime


class ReviewListOut(Schema):
    total: int
    rating_avg: Decimal
    data: List[ReviewOut]


# WISHLIST SCHEMAS

class WishlistIn(Schema):
    course_id: int


class WishlistOut(Schema):
    id: int
    course_id: int
    course_name: str
    rating_avg: Decimal
    created_at: datetime


class PaginatedWishlistOut(Schema):
    total: int
    page: int
    page_size: int
    data: List[WishlistOut]


# PROGRESS DETAIL SCHEMAS

class LessonProgressItemOut(Schema):
    lesson_id: int
    title: str
    is_completed: bool


class SectionProgressOut(Schema):
    section_id: Optional[int] = None
    section_title: str
    total_lessons: int
    completed_lessons: int
    progress_percent: float
    lessons: List[LessonProgressItemOut]


class EnrollmentProgressDetailOut(Schema):
    total_lessons: int
    completed_lessons: int
    progress_percent: float
    sections: List[SectionProgressOut]


# DASHBOARD SCHEMAS

class DashboardCourseOut(Schema):
    course_id: int
    course_name: str
    progress_percent: float
    total_lessons: int
    completed_lessons: int
    instructor_name: str


class RecommendedCourseOut(Schema):
    id: int
    name: str
    rating_avg: Decimal
    total_reviews: int
    price: int
    instructor_name: str
    reason: str = "Populer di kategori yang sama"


class WishlistDashboardOut(Schema):
    course_id: int
    course_name: str
    rating_avg: Decimal
    price: int
    instructor_name: str


class StudentDashboardOut(Schema):
    active_courses: List[DashboardCourseOut]
    completed_courses: List[DashboardCourseOut]
    total_enrolled: int
    total_completed: int
    wishlist_count: int
    wishlist: List[WishlistDashboardOut]
    recommended_courses: List[RecommendedCourseOut]


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


# PUBLISHING WORKFLOW SCHEMAS

class PublishRequestOut(Schema):
    id: int
    course_id: int
    course_name: str
    requester_id: int
    requester_username: str
    status: str
    reviewer_id: Optional[int] = None
    reviewer_username: Optional[str] = None
    rejection_reason: str
    requested_at: datetime
    reviewed_at: Optional[datetime] = None


class PublishReviewIn(Schema):
    reason: str = ""


# COURSE PREREQUISITE SCHEMAS

class PrerequisiteOut(Schema):
    id: int
    course_id: int
    required_course_id: int
    required_course_name: str
    created_at: datetime


class PrerequisiteIn(Schema):
    required_course_id: int


# CHATBOT SCHEMAS

class ChatbotIn(Schema):
    message: str


class ChatbotOut(Schema):
    response: str

