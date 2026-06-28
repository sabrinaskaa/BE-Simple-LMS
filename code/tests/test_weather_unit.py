import json
import unittest
from unittest.mock import patch


class TestGetWeatherUnit(unittest.TestCase):

    def setUp(self):
        self.city = "Jakarta"
        self.cache_key = f"weather:{self.city.strip().lower()}"
        self.fake_weather_data = {
            "city": "Jakarta",
            "temperature": 30,
            "condition": "Cloudy",
            "source": "slow_api",
            "message": "Weather data for Jakarta",
            "cache_status": "MISS",
        }

    def test_get_weather_returns_cached_data_when_cache_hit(self):
        with patch("weather_api.redis_client") as mock_redis:
            mock_redis.get.return_value = json.dumps(self.fake_weather_data)
            from weather_api import get_weather
            result = get_weather(self.city)

            self.assertEqual(result["city"], self.fake_weather_data["city"])
            self.assertEqual(result["temperature"], self.fake_weather_data["temperature"])
            mock_redis.get.assert_called_once_with(self.cache_key)
            mock_redis.setex.assert_not_called()

    def test_get_weather_marks_result_as_hit_when_served_from_cache(self):
        with patch("weather_api.redis_client") as mock_redis:
            mock_redis.get.return_value = json.dumps(self.fake_weather_data)
            from weather_api import get_weather
            result = get_weather(self.city)

            self.assertEqual(result["cache_status"], "HIT")

    def test_get_weather_calls_api_and_saves_to_cache_when_cache_miss(self):
        with patch("weather_api.redis_client") as mock_redis, \
             patch("weather_api.call_slow_weather_api") as mock_api, \
             patch("weather_api.time.sleep"):

            mock_redis.get.return_value = None
            mock_api.return_value = dict(self.fake_weather_data)

            from weather_api import get_weather
            result = get_weather(self.city)

            mock_api.assert_called_once_with(self.city)
            mock_redis.setex.assert_called_once()

            setex_args = mock_redis.setex.call_args[0]
            self.assertEqual(setex_args[0], self.cache_key)
            self.assertEqual(setex_args[1], 300)

            stored_data = json.loads(setex_args[2])
            self.assertEqual(stored_data["city"], self.fake_weather_data["city"])

    def test_get_weather_returns_correct_data_on_cache_miss(self):
        with patch("weather_api.redis_client") as mock_redis, \
             patch("weather_api.call_slow_weather_api") as mock_api, \
             patch("weather_api.time.sleep"):

            mock_redis.get.return_value = None
            mock_api.return_value = dict(self.fake_weather_data)

            from weather_api import get_weather
            result = get_weather(self.city)

            self.assertEqual(result["city"], self.fake_weather_data["city"])
            self.assertEqual(result["temperature"], self.fake_weather_data["temperature"])

    def test_cache_is_set_with_exactly_300_seconds_expiry(self):
        with patch("weather_api.redis_client") as mock_redis, \
             patch("weather_api.call_slow_weather_api") as mock_api, \
             patch("weather_api.time.sleep"):

            mock_redis.get.return_value = None
            mock_api.return_value = dict(self.fake_weather_data)

            from weather_api import get_weather
            get_weather(self.city)

            mock_redis.setex.assert_called_once()
            setex_args = mock_redis.setex.call_args[0]
            self.assertEqual(setex_args[1], 300)

    def tearDown(self):
        pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
