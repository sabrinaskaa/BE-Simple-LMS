from datetime import date, datetime, time, timezone
from typing import Any, Dict, List, Optional

from ninja import Router, Schema
from ninja.errors import HttpError

from courses.auth import api_auth

from . import mongo_service

analytics_router = Router(tags=["Analytics"])


# =============================================================================
# Schemas I/O
# =============================================================================

class LogActivityIn(Schema):
    action: str
    course_name: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class LogActivityOut(Schema):
    status: str
    log_id: str


class PopularCourseOut(Schema):
    course_name: Optional[str] = None
    total_views: int


class UserActivitySummaryOut(Schema):
    action: str
    count: int
    last_activity: Optional[datetime] = None


class DailySummaryOut(Schema):
    date: str
    total_activities: int
    unique_users_count: int


# =============================================================================
# Endpoints
# =============================================================================

@analytics_router.post(
    "/log/",
    auth=api_auth,
    response=LogActivityOut,
    summary="Log aktivitas user ke MongoDB",
)
def log_activity(request, data: LogActivityIn):
    try:
        log_id = mongo_service.log_activity(
            user_id=request.user.id,
            action=data.action,
            course_name=data.course_name,
            metadata=data.metadata,
        )
        return {"status": "logged", "log_id": log_id}
    except Exception as e:
        raise HttpError(500, f"Gagal mencatat aktivitas: {str(e)}")


@analytics_router.get(
    "/popular-courses/",
    response=List[PopularCourseOut],
    summary="Kursus paling populer berdasarkan jumlah view",
)
def popular_courses(request, limit: int = 10):
    limit = max(1, min(limit, 100))
    return mongo_service.get_popular_courses(limit=limit)


@analytics_router.get(
    "/user/{user_id}/summary/",
    auth=api_auth,
    response=List[UserActivitySummaryOut],
    summary="Ringkasan aktivitas per user",
)
def user_activity_summary(request, user_id: int):
    return mongo_service.get_user_activity_summary(user_id=user_id)


@analytics_router.get(
    "/daily-summary/",
    auth=api_auth,
    response=List[DailySummaryOut],
    summary="Aktivitas harian dalam rentang tanggal",
)
def daily_summary(request, start_date: date, end_date: date):
    if start_date > end_date:
        raise HttpError(400, "start_date harus sebelum atau sama dengan end_date")

    # Konversi date → datetime aware (UTC) untuk query MongoDB
    start_dt = datetime.combine(start_date, time.min).replace(tzinfo=timezone.utc)
    end_dt = datetime.combine(end_date, time.max).replace(tzinfo=timezone.utc)

    return mongo_service.get_daily_activity_summary(
        start_date=start_dt,
        end_date=end_dt,
    )
