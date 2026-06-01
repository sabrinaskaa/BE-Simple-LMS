import json
from typing import Any, Optional

import redis
from django.conf import settings


def get_redis_client():
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


def cache_get(key: str) -> Optional[Any]:
    value = get_redis_client().get(key)
    if value is None:
        return None
    return json.loads(value)


def cache_set(key: str, value: Any, timeout: int = 300) -> None:
    payload = json.dumps(value, default=str)
    get_redis_client().setex(key, timeout, payload)


def cache_delete_pattern(pattern: str) -> int:
    client = get_redis_client()
    keys = list(client.scan_iter(pattern))
    if not keys:
        return 0
    return client.delete(*keys)


def course_list_cache_key(search=None, min_price=None, max_price=None, ordering='-created_at', page=1, page_size=10) -> str:
    return f"course:list:search={search}:min={min_price}:max={max_price}:ordering={ordering}:page={page}:size={page_size}"


def course_detail_cache_key(course_id: int) -> str:
    return f"course:detail:{course_id}"


def invalidate_course_cache(course_id: int | None = None) -> None:
    cache_delete_pattern('course:list:*')
    if course_id is not None:
        get_redis_client().delete(course_detail_cache_key(course_id))
