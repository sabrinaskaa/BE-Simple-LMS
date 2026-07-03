import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from django.conf import settings
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure

logger = logging.getLogger(__name__)

_client: Optional[MongoClient] = None


# =============================================================================
# Connection Management — Singleton
# =============================================================================

def get_mongo_client() -> MongoClient:
    global _client
    if _client is None:
        try:
            _client = MongoClient(
                settings.MONGODB_URI,
                serverSelectionTimeoutMS=5000,
            )
        except Exception as e:
            logger.error(f"[MongoDB] Gagal membuat koneksi: {e}")
            raise
    return _client


def get_analytics_db():
    return get_mongo_client()[settings.MONGODB_ANALYTICS_DB]


def get_logs_db():
    return get_mongo_client()[settings.MONGODB_NAME]


# =============================================================================
# Step 8 — Indexing & Optimasi
# =============================================================================

def ensure_indexes() -> None:
    try:
        col = get_analytics_db().activity_logs

        # Single field indexes
        col.create_index("user_id", background=True)
        col.create_index("timestamp", background=True)
        col.create_index("action", background=True)

        # Compound indexes untuk query yang sering digunakan
        col.create_index(
            [("user_id", ASCENDING), ("timestamp", DESCENDING)],
            background=True,
        )
        col.create_index(
            [("action", ASCENDING), ("timestamp", DESCENDING)],
            background=True,
        )


        req = get_analytics_db().request_logs
        req.create_index("timestamp", background=True)
        req.create_index("user_id", background=True)
        req.create_index("path", background=True)
        req.create_index("status_code", background=True)
        req.create_index(
            [("path", ASCENDING), ("timestamp", DESCENDING)],
            background=True,
        )
        req.create_index(
            [("status_code", ASCENDING), ("timestamp", DESCENDING)],
            background=True,
        )

        logger.info("[MongoDB] Indexes berhasil dibuat/diverifikasi pada activity_logs dan request_logs")
    except (ConnectionFailure, OperationFailure) as e:
        logger.warning(f"[MongoDB] Gagal membuat indexes (MongoDB mungkin belum ready): {e}")
    except Exception as e:
        logger.warning(f"[MongoDB] ensure_indexes — error tak terduga: {e}")


# =============================================================================
# Step 5 — Document Schema Helpers (Embedding vs Referencing)
# =============================================================================

def build_activity_log(
    user_id: Optional[int],
    action: str,
    course_name: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "user_id": user_id,
        "action": action,
        "course_name": course_name,
        "timestamp": datetime.now(timezone.utc),
        "metadata": metadata or {},
    }


def build_course_progress(
    user_id: int,
    course_id: int,
    completed_contents: Optional[List[int]] = None,
    progress_percentage: float = 0.0,
    quiz_scores: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    
    return {
        "user_id": user_id,
        "course_id": course_id,
        "completed_contents": completed_contents or [],
        "progress_percentage": progress_percentage,
        "last_accessed": datetime.now(timezone.utc),
        "quiz_scores": quiz_scores or [],
    }


# =============================================================================
# Step 4 — Operasi CRUD via pymongo
# =============================================================================

# --- INSERT ---

def insert_activity_log(document: Dict[str, Any]) -> str:
    try:
        col = get_analytics_db().activity_logs
        result = col.insert_one(document)
        return str(result.inserted_id)
    except (ConnectionFailure, OperationFailure) as e:
        logger.error(f"[MongoDB] insert_activity_log gagal: {e}")
        raise


def insert_many_activity_logs(documents: List[Dict[str, Any]]) -> List[str]:
    try:
        col = get_analytics_db().activity_logs
        result = col.insert_many(documents)
        return [str(oid) for oid in result.inserted_ids]
    except (ConnectionFailure, OperationFailure) as e:
        logger.error(f"[MongoDB] insert_many_activity_logs gagal: {e}")
        raise


# --- READ / QUERY ---

def find_activity_logs(
    filter_query: Optional[Dict] = None,
    projection: Optional[Dict] = None,
    sort_field: str = "timestamp",
    sort_direction: int = DESCENDING,
    limit: int = 20,
    skip: int = 0,
) -> List[Dict]:
    try:
        col = get_analytics_db().activity_logs
        cursor = col.find(filter_query or {}, projection)
        cursor = cursor.sort(sort_field, sort_direction).skip(skip).limit(limit)

        docs = []
        for doc in cursor:
            doc["_id"] = str(doc["_id"])  # ObjectId → string untuk JSON
            docs.append(doc)
        return docs
    except (ConnectionFailure, OperationFailure) as e:
        logger.error(f"[MongoDB] find_activity_logs gagal: {e}")
        return []


def find_one_activity_log(filter_query: Dict) -> Optional[Dict]:
    try:
        col = get_analytics_db().activity_logs
        doc = col.find_one(filter_query)
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc
    except (ConnectionFailure, OperationFailure) as e:
        logger.error(f"[MongoDB] find_one_activity_log gagal: {e}")
        return None


def count_activity_logs(filter_query: Optional[Dict] = None) -> int:
    try:
        col = get_analytics_db().activity_logs
        return col.count_documents(filter_query or {})
    except (ConnectionFailure, OperationFailure) as e:
        logger.error(f"[MongoDB] count_activity_logs gagal: {e}")
        return 0


# --- UPDATE ---

def update_activity_log(log_id: str, update_data: Dict) -> bool:
    try:
        col = get_analytics_db().activity_logs
        result = col.update_one(
            {"_id": ObjectId(log_id)},
            {"$set": update_data},
        )
        return result.modified_count > 0
    except (ConnectionFailure, OperationFailure) as e:
        logger.error(f"[MongoDB] update_activity_log gagal: {e}")
        return False


def update_many_activity_logs(filter_query: Dict, update_data: Dict) -> int:
    try:
        col = get_analytics_db().activity_logs
        result = col.update_many(filter_query, {"$set": update_data})
        return result.modified_count
    except (ConnectionFailure, OperationFailure) as e:
        logger.error(f"[MongoDB] update_many_activity_logs gagal: {e}")
        return 0


def upsert_user_action(
    user_id: int,
    action: str,
    extra_data: Optional[Dict] = None,
) -> bool:
    try:
        col = get_analytics_db().activity_logs
        update = {
            "$set": {
                "last_activity": datetime.now(timezone.utc),
                **(extra_data or {}),
            },
            "$inc": {"count": 1},
        }
        col.update_one(
            {"user_id": user_id, "action": action},
            update,
            upsert=True,
        )
        return True
    except (ConnectionFailure, OperationFailure) as e:
        logger.error(f"[MongoDB] upsert_user_action gagal: {e}")
        return False


# --- DELETE ---

def delete_activity_log(log_id: str) -> bool:
    try:
        col = get_analytics_db().activity_logs
        result = col.delete_one({"_id": ObjectId(log_id)})
        return result.deleted_count > 0
    except (ConnectionFailure, OperationFailure) as e:
        logger.error(f"[MongoDB] delete_activity_log gagal: {e}")
        return False


def delete_many_activity_logs(filter_query: Dict) -> int:
    try:
        col = get_analytics_db().activity_logs
        result = col.delete_many(filter_query)
        return result.deleted_count
    except (ConnectionFailure, OperationFailure) as e:
        logger.error(f"[MongoDB] delete_many_activity_logs gagal: {e}")
        return 0


# =============================================================================
# Step 7.2 — Fungsi Publik untuk API & Middleware
# =============================================================================

def log_activity(
    user_id: Optional[int],
    action: str,
    course_name: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    document = build_activity_log(user_id, action, course_name, metadata)
    return insert_activity_log(document)


# =============================================================================
# Step 6 — Aggregation Pipelines
# =============================================================================

def get_popular_courses(limit: int = 10) -> List[Dict]:
    try:
        pipeline = [
            # Stage 1: hanya ambil event "view_course"
            {"$match": {"action": "view_course"}},
            # Stage 2: group by course_name, hitung total view
            {
                "$group": {
                    "_id": "$course_name",
                    "total_views": {"$sum": 1},
                }
            },
            # Stage 3: urutkan dari yang terbanyak
            {"$sort": {"total_views": DESCENDING}},
            # Stage 4: reshape output agar rapi
            {
                "$project": {
                    "_id": 0,
                    "course_name": "$_id",
                    "total_views": 1,
                }
            },
            # Stage 5: batasi jumlah hasil
            {"$limit": limit},
        ]
        col = get_analytics_db().activity_logs
        return list(col.aggregate(pipeline))
    except (ConnectionFailure, OperationFailure) as e:
        logger.error(f"[MongoDB] get_popular_courses gagal: {e}")
        return []


def get_user_activity_summary(user_id: int) -> List[Dict]:
    try:
        pipeline = [
            # Stage 1: filter hanya log milik user ini
            {"$match": {"user_id": user_id}},
            # Stage 2: group by action type
            {
                "$group": {
                    "_id": "$action",
                    "count": {"$sum": 1},
                    "last_activity": {"$max": "$timestamp"},
                }
            },
            # Stage 3: urutkan dari yang paling sering
            {"$sort": {"count": DESCENDING}},
            # Stage 4: reshape output
            {
                "$project": {
                    "_id": 0,
                    "action": "$_id",
                    "count": 1,
                    "last_activity": 1,
                }
            },
        ]
        col = get_analytics_db().activity_logs
        return list(col.aggregate(pipeline))
    except (ConnectionFailure, OperationFailure) as e:
        logger.error(f"[MongoDB] get_user_activity_summary gagal: {e}")
        return []


def get_daily_activity_summary(
    start_date: datetime,
    end_date: datetime,
) -> List[Dict]:
    try:
        pipeline = [
            # Stage 1: filter berdasarkan rentang tanggal
            {
                "$match": {
                    "timestamp": {
                        "$gte": start_date,
                        "$lte": end_date,
                    }
                }
            },
            # Stage 2: group by tanggal (format YYYY-MM-DD)
            {
                "$group": {
                    "_id": {
                        "$dateToString": {
                            "format": "%Y-%m-%d",
                            "date": "$timestamp",
                        }
                    },
                    "total_activities": {"$sum": 1},
                    "unique_users": {"$addToSet": "$user_id"},  # set → unik
                }
            },
            # Stage 3: hitung ukuran set unique_users
            {
                "$project": {
                    "_id": 0,
                    "date": "$_id",
                    "total_activities": 1,
                    "unique_users_count": {"$size": "$unique_users"},
                }
            },
            # Stage 4: urutkan kronologis
            {"$sort": {"date": ASCENDING}},
        ]
        col = get_analytics_db().activity_logs
        return list(col.aggregate(pipeline))
    except (ConnectionFailure, OperationFailure) as e:
        logger.error(f"[MongoDB] get_daily_activity_summary gagal: {e}")
        return []


# =============================================================================
# Request Logs — raw log admin endpoint helpers
# =============================================================================

def find_request_logs(
    filter_query: Optional[Dict] = None,
    projection: Optional[Dict] = None,
    sort_field: str = "timestamp",
    sort_direction: int = DESCENDING,
    limit: int = 20,
    skip: int = 0,
) -> List[Dict]:
    try:
        col = get_analytics_db().request_logs
        cursor = col.find(filter_query or {}, projection)
        cursor = cursor.sort(sort_field, sort_direction).skip(skip).limit(limit)
        docs = []
        for doc in cursor:
            doc["_id"] = str(doc["_id"])
            docs.append(doc)
        return docs
    except (ConnectionFailure, OperationFailure) as e:
        logger.error(f"[MongoDB] find_request_logs gagal: {e}")
        return []


def count_request_logs(filter_query: Optional[Dict] = None) -> int:
    try:
        col = get_analytics_db().request_logs
        return col.count_documents(filter_query or {})
    except (ConnectionFailure, OperationFailure) as e:
        logger.error(f"[MongoDB] count_request_logs gagal: {e}")
        return 0
