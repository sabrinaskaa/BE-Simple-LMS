from typing import Optional

from django.db.models import Q
from ninja import NinjaAPI

from .models import Course
from .api import serialize_course
from .schemas import PaginatedCourseOut

api_v2 = NinjaAPI(
    title="Simple LMS API v2",
    version="2.0.0",
    description="Versi kedua API untuk demonstrasi API versioning. Endpoint utama v1 tetap dipertahankan.",
    docs_url="/docs",
    urls_namespace="api-v2",
)


@api_v2.get("/health", tags=["Versioning"])
def health_v2(request):
    return {"status": "ok", "version": "v2"}


@api_v2.get("/courses", response=PaginatedCourseOut, tags=["Courses"])
def list_courses_v2(
    request,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 10,
):
    page = max(page, 1)
    page_size = max(min(page_size, 100), 1)
    qs = Course.objects.select_related("teacher", "category").order_by("-created_at")
    if search:
        qs = qs.filter(Q(name__icontains=search) | Q(description__icontains=search))
    total = qs.count()
    start = (page - 1) * page_size
    end = start + page_size
    return {"total": total, "page": page, "page_size": page_size, "data": [serialize_course(c) for c in qs[start:end]]}
