from datetime import date, datetime, time, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from ninja import Router, Schema
from ninja.errors import HttpError

from courses.auth import api_auth
from courses.permissions import require_admin

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


class ActivityLogUpdateIn(Schema):
    reviewed: Optional[bool] = None
    note: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


def _date_range_filter(start_date: Optional[date], end_date: Optional[date]) -> Dict[str, Any]:
    query: Dict[str, Any] = {}
    if start_date or end_date:
        ts: Dict[str, Any] = {}
        if start_date:
            ts["$gte"] = datetime.combine(start_date, time.min).replace(tzinfo=timezone.utc)
        if end_date:
            ts["$lte"] = datetime.combine(end_date, time.max).replace(tzinfo=timezone.utc)
        query["timestamp"] = ts
    return query


def _pagination(page: int, page_size: int) -> tuple[int, int, int]:
    page = max(page, 1)
    page_size = max(1, min(page_size, 100))
    skip = (page - 1) * page_size
    return page, page_size, skip


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

    start_dt = datetime.combine(start_date, time.min).replace(tzinfo=timezone.utc)
    end_dt = datetime.combine(end_date, time.max).replace(tzinfo=timezone.utc)

    return mongo_service.get_daily_activity_summary(
        start_date=start_dt,
        end_date=end_dt,
    )


@analytics_router.get(
    "/activity-logs/",
    auth=api_auth,
    summary="Lihat raw MongoDB activity logs dengan filter dan pagination (Admin)",
)
@require_admin
def activity_logs(
    request,
    user_id: Optional[int] = None,
    action: Optional[str] = None,
    course_name: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    page: int = 1,
    page_size: int = 20,
):
    query = _date_range_filter(start_date, end_date)
    if user_id is not None:
        query["user_id"] = user_id
    if action:
        query["action"] = action
    if course_name:
        query["course_name"] = course_name

    page, page_size, skip = _pagination(page, page_size)
    total = mongo_service.count_activity_logs(query)
    data = mongo_service.find_activity_logs(query, limit=page_size, skip=skip)
    return {"total": total, "page": page, "page_size": page_size, "data": data}


@analytics_router.patch(
    "/activity-logs/{log_id}/",
    auth=api_auth,
    summary="Update sebagian field raw activity log MongoDB untuk demo CRUD (Admin)",
)
@require_admin
def update_activity_log(request, log_id: str, data: ActivityLogUpdateIn):
    try:
        ObjectId(log_id)
    except Exception:
        raise HttpError(400, "log_id tidak valid")

    payload = data.dict(exclude_none=True)
    if not payload:
        raise HttpError(400, "Tidak ada field yang dikirim untuk diupdate")

    updated = mongo_service.update_activity_log(log_id, payload)
    if not updated:
        raise HttpError(404, "Activity log tidak ditemukan atau tidak berubah")
    return {"message": "Activity log berhasil diupdate", "log_id": log_id}


@analytics_router.delete(
    "/activity-logs/{log_id}/",
    auth=api_auth,
    summary="Hapus satu raw activity log MongoDB untuk demo CRUD (Admin)",
)
@require_admin
def delete_activity_log(request, log_id: str):
    try:
        ObjectId(log_id)
    except Exception:
        raise HttpError(400, "log_id tidak valid")

    deleted = mongo_service.delete_activity_log(log_id)
    if not deleted:
        raise HttpError(404, "Activity log tidak ditemukan")
    return {"message": "Activity log berhasil dihapus", "log_id": log_id}


@analytics_router.get(
    "/request-logs/",
    auth=api_auth,
    summary="Lihat raw MongoDB request logs dengan filter dan pagination (Admin)",
)
@require_admin
def request_logs(
    request,
    user_id: Optional[int] = None,
    path: Optional[str] = None,
    status_code: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    page: int = 1,
    page_size: int = 20,
):
    query = _date_range_filter(start_date, end_date)
    if user_id is not None:
        query["user_id"] = user_id
    if path:
        query["path"] = {"$regex": path, "$options": "i"}
    if status_code is not None:
        query["status_code"] = status_code

    page, page_size, skip = _pagination(page, page_size)
    total = mongo_service.count_request_logs(query)
    data = mongo_service.find_request_logs(query, limit=page_size, skip=skip)
    return {"total": total, "page": page, "page_size": page_size, "data": data}
