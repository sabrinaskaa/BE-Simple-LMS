import json
import os
import time
import unittest
from urllib.parse import urlparse

import redis


class TestWeatherCacheIntegration(unittest.TestCase):

    def setUp(self):
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        parsed = urlparse(redis_url)
        self.r = redis.Redis(
            host=parsed.hostname or "localhost",
            port=parsed.port or 6379,
            db=int(parsed.path.lstrip("/") or 0),
            decode_responses=True,
        )
        self.test_city = "TestCity"
        self.cache_key = f"weather:{self.test_city.strip().lower()}"
        self.r.delete(self.cache_key)

    def test_second_call_is_faster_than_first_call(self):
        from weather_api import get_weather

        start = time.time()
        get_weather(self.test_city)
        first_duration = time.time() - start

        start = time.time()
        get_weather(self.test_city)
        second_duration = time.time() - start

        self.assertGreater(first_duration, 1.0)
        self.assertLess(second_duration, 0.5)

    def test_cache_key_exists_in_redis_after_first_call(self):
        from weather_api import get_weather

        self.assertIsNone(self.r.get(self.cache_key))

        get_weather(self.test_city)

        self.assertIsNotNone(self.r.get(self.cache_key))

    def test_cached_data_is_valid_json(self):
        from weather_api import get_weather

        get_weather(self.test_city)

        raw = self.r.get(self.cache_key)
        self.assertIsNotNone(raw)
        try:
            parsed = json.loads(raw)
            self.assertIsInstance(parsed, dict)
        except json.JSONDecodeError:
            self.fail("Data di Redis bukan JSON valid")

    def test_cache_ttl_is_approximately_300_seconds(self):
        from weather_api import get_weather

        get_weather(self.test_city)

        ttl = self.r.ttl(self.cache_key)
        self.assertGreater(ttl, 290)
        self.assertLessEqual(ttl, 300)

    def tearDown(self):
        self.r.delete(self.cache_key)


if __name__ == "__main__":
    unittest.main(verbosity=2)
