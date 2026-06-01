from datetime import datetime, timezone
from typing import Any, Dict, Optional

from django.conf import settings
from pymongo import MongoClient

_client = None


def get_mongo_client():
    global _client
    if _client is None:
        _client = MongoClient(settings.MONGODB_URI)
    return _client


def get_mongo_db():
    return get_mongo_client()[settings.MONGODB_NAME]


def log_activity(user, action: str, metadata: Optional[Dict[str, Any]] = None):
    db = get_mongo_db()
    document = {
        'user_id': getattr(user, 'id', None),
        'username': getattr(user, 'username', 'anonymous') if user else 'anonymous',
        'action': action,
        'metadata': metadata or {},
        'created_at': datetime.now(timezone.utc),
    }
    return db.activity_logs.insert_one(document).inserted_id


def log_learning_activity(user, course_id: int, event: str, metadata: Optional[Dict[str, Any]] = None):
    db = get_mongo_db()
    document = {
        'user_id': getattr(user, 'id', None),
        'username': getattr(user, 'username', 'anonymous') if user else 'anonymous',
        'course_id': course_id,
        'event': event,
        'metadata': metadata or {},
        'created_at': datetime.now(timezone.utc),
    }
    return db.learning_analytics.insert_one(document).inserted_id


def get_activity_report(limit: int = 20):
    pipeline = [
        {'$group': {'_id': '$action', 'total': {'$sum': 1}}},
        {'$sort': {'total': -1}},
        {'$limit': limit},
    ]
    return [{ 'action': row['_id'], 'total': row['total'] } for row in get_mongo_db().activity_logs.aggregate(pipeline)]


def get_learning_report(limit: int = 20):
    pipeline = [
        {'$group': {'_id': {'course_id': '$course_id', 'event': '$event'}, 'total': {'$sum': 1}}},
        {'$sort': {'total': -1}},
        {'$limit': limit},
    ]
    return [
        {
            'course_id': row['_id'].get('course_id'),
            'event': row['_id'].get('event'),
            'total': row['total'],
        }
        for row in get_mongo_db().learning_analytics.aggregate(pipeline)
    ]
