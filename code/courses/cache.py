import json
from typing import Any, Optional

import redis
from django.conf import settings

CACHE_HIT_KEY = "cache:metrics:hits"
CACHE_MISS_KEY = "cache:metrics:misses"


def get_redis_client():
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


def _increment_metric(metric_key: str) -> None:
    try:
        get_redis_client().incr(metric_key)
    except Exception:
        # Cache metrics tidak boleh membuat request utama gagal jika Redis belum ready.
        pass


def cache_get(key: str) -> Optional[Any]:
    value = get_redis_client().get(key)
    if value is None:
        _increment_metric(CACHE_MISS_KEY)
        return None
    _increment_metric(CACHE_HIT_KEY)
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


def get_cache_metrics() -> dict:
    client = get_redis_client()
    hits = int(client.get(CACHE_HIT_KEY) or 0)
    misses = int(client.get(CACHE_MISS_KEY) or 0)
    total = hits + misses
    hit_rate = round((hits / total) * 100, 2) if total else 0.0
    return {
        "hits": hits,
        "misses": misses,
        "total": total,
        "hit_rate_percent": hit_rate,
    }


def reset_cache_metrics() -> dict:
    client = get_redis_client()
    client.delete(CACHE_HIT_KEY, CACHE_MISS_KEY)
    return get_cache_metrics()


def course_list_cache_key(
    search=None,
    min_price=None,
    max_price=None,
    ordering='-created_at',
    page=1,
    page_size=10,
    category_id=None,
    level=None,
    status=None,
    instructor_id=None,
) -> str:
    return (
        f"course:list:search={search}:min={min_price}:max={max_price}"
        f":cat={category_id}:level={level}:status={status}"
        f":instructor={instructor_id}:ordering={ordering}:page={page}:size={page_size}"
    )


def course_detail_cache_key(course_id: int) -> str:
    return f"course:detail:{course_id}"


def invalidate_course_cache(course_id: int | None = None) -> None:
    cache_delete_pattern('course:list:*')
    if course_id is not None:
        get_redis_client().delete(course_detail_cache_key(course_id))


def dashboard_cache_key(user_id: int) -> str:
    return f"dashboard:student:{user_id}"


def invalidate_dashboard_cache(user_id: int) -> None:
    get_redis_client().delete(dashboard_cache_key(user_id))


def write_through_course_detail_cache(course_id: int, payload: Any, timeout: int = 300) -> None:
    cache_delete_pattern('course:list:*')
    cache_set(course_detail_cache_key(course_id), payload, timeout=timeout)
