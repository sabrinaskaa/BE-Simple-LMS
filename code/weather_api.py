# weather_api.py
import json
import os
import time
from typing import Any, Dict

import redis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

CACHE_TTL_SECONDS = 300

redis_client = redis.Redis.from_url(
    REDIS_URL,
    decode_responses=True
)


def make_cache_key(city: str) -> str:
    normalized_city = city.strip().lower()
    return f"weather:{normalized_city}"


def call_slow_weather_api(city: str) -> Dict[str, Any]:
    time.sleep(2)

    return {
        "city": city,
        "temperature": 30,
        "condition": "Cloudy",
        "source": "slow_api",
        "message": f"Weather data for {city}"
    }


def get_weather(city: str) -> Dict[str, Any]:
    cache_key = make_cache_key(city)

    cached_data = redis_client.get(cache_key)

    if cached_data is not None:
        data = json.loads(cached_data)
        data["cache_status"] = "HIT"
        return data

    data = call_slow_weather_api(city)
    data["cache_status"] = "MISS"

    redis_client.set(cache_key, json.dumps(data))

    redis_client.expire(cache_key, CACHE_TTL_SECONDS)

    return data


def clear_weather_cache(city: str) -> int:
    cache_key = make_cache_key(city)
    return redis_client.delete(cache_key)


def get_weather_cache_ttl(city: str) -> int:
    cache_key = make_cache_key(city)
    return redis_client.ttl(cache_key)