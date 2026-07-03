import json
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import Group, User
from django.test import Client, TestCase


# ─── Base class with full Redis + external-service mocking ───────────────────

def make_redis_mock():
    m = MagicMock()
    m.get.return_value = None
    m.incr.return_value = 1        # selalu di bawah limit
    m.expire.return_value = True
    m.ttl.return_value = 60
    m.setex.return_value = True
    m.delete.return_value = 1
    m.scan_iter.return_value = iter([])
    return m


class LMSTestCase(TestCase):

    def setUp(self):
        self.client = Client()
        redis_mock = make_redis_mock()

        # Patch Redis di dua lokasi berbeda
        self._patch_cache_redis = patch(
            "courses.cache.get_redis_client", return_value=redis_mock
        )
        self._patch_rate_redis = patch(
            "courses.rate_limit.get_redis_client", return_value=redis_mock
        )
        # Patch is_token_blacklisted langsung agar token JWT di test tidak dianggap blacklisted
        # (is_token_blacklisted melakukan lazy import ke courses.cache yang tidak bisa dipatch via attr)
        self._patch_blacklist = patch(
            "courses.auth.is_token_blacklisted", return_value=False
        )
        # Patch MongoDB logging
        self._patch_log = patch("courses.api.log_activity")
        self._patch_log_learn = patch("courses.api.log_learning_activity")
        # Patch Celery tasks
        self._patch_welcome = patch("courses.api.send_welcome_email")
        self._patch_enroll_email = patch("courses.api.send_enrollment_email")
        self._patch_cert = patch("courses.api.generate_certificate")

        self.mock_redis = self._patch_cache_redis.start()
        self._patch_rate_redis.start()
        self._patch_blacklist.start()
        self.mock_log = self._patch_log.start()
        self.mock_log_learn = self._patch_log_learn.start()
        mock_welcome = self._patch_welcome.start()
        mock_welcome.delay = lambda *a, **kw: None
        mock_enroll = self._patch_enroll_email.start()
        mock_enroll.delay = lambda *a, **kw: None
        mock_cert = self._patch_cert.start()
        mock_cert.delay = lambda *a, **kw: None

    def tearDown(self):
        self._patch_cache_redis.stop()
        self._patch_rate_redis.stop()
        self._patch_blacklist.stop()
        self._patch_log.stop()
        self._patch_log_learn.stop()
        self._patch_welcome.stop()
        self._patch_enroll_email.stop()
        self._patch_cert.stop()

    def get_token(self, username, password="password123"):
        resp = self.client.post(
            "/api/v1/auth/login",
            data=json.dumps({"username": username, "password": password}),
            content_type="application/json",
        )
        self.assertIn(
            "access", resp.json(),
            f"Login gagal untuk '{username}': {resp.json()}"
        )
        return resp.json()["access"]

    def auth_header(self, username, password="password123"):
        return {"HTTP_AUTHORIZATION": f"Bearer {self.get_token(username, password)}"}

    def make_user(self, username, password="password123", email=None, role=None):
        user = User.objects.create_user(
            username=username,
            password=password,
            email=email or f"{username}@test.com",
        )
        if role:
            group, _ = Group.objects.get_or_create(name=role)
            user.groups.add(group)
        return user


# ─── Register ─────────────────────────────────────────────────────────────────

class AuthRegisterTest(LMSTestCase):

    URL = "/api/v1/auth/register"

    def _payload(self, **overrides):
        base = {
            "username": "newuser",
            "password": "password123",
            "email": "newuser@example.com",
            "first_name": "New",
            "last_name": "User",
        }
        base.update(overrides)
        return base

    def test_register_sukses(self):
        Group.objects.get_or_create(name="Student")
        resp = self.client.post(
            self.URL,
            data=json.dumps(self._payload()),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["username"], "newuser")
        self.assertIn("id", data)
        self.assertIn("roles", data)

    def test_register_username_duplikat(self):
        User.objects.create_user(username="newuser", password="x", email="a@b.com")
        resp = self.client.post(
            self.URL,
            data=json.dumps(self._payload()),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Username sudah digunakan", resp.json().get("detail", ""))

    def test_register_email_duplikat(self):
        User.objects.create_user(
            username="other", password="x", email="newuser@example.com"
        )
        resp = self.client.post(
            self.URL,
            data=json.dumps(self._payload()),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Email sudah digunakan", resp.json().get("detail", ""))

    def test_register_otomatis_jadi_student(self):
        Group.objects.get_or_create(name="Student")
        self.client.post(
            self.URL,
            data=json.dumps(self._payload()),
            content_type="application/json",
        )
        user = User.objects.get(username="newuser")
        self.assertTrue(user.groups.filter(name="Student").exists())


# ─── Login ────────────────────────────────────────────────────────────────────

class AuthLoginTest(LMSTestCase):
    URL = "/api/v1/auth/login"

    def setUp(self):
        super().setUp()
        self.user = self.make_user("loginuser", role="Student")

    def test_login_sukses(self):
        resp = self.client.post(
            self.URL,
            data=json.dumps({"username": "loginuser", "password": "password123"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("access", data)
        self.assertIn("refresh", data)
        self.assertTrue(len(data["access"]) > 10)

    def test_login_password_salah(self):
        resp = self.client.post(
            self.URL,
            data=json.dumps({"username": "loginuser", "password": "salah"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)

    def test_login_user_tidak_ada(self):
        resp = self.client.post(
            self.URL,
            data=json.dumps({"username": "tidakada", "password": "password123"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)


# ─── Refresh Token ────────────────────────────────────────────────────────────

class AuthRefreshTokenTest(LMSTestCase):
    REFRESH_URL = "/api/v1/auth/refresh"

    def setUp(self):
        super().setUp()
        self.make_user("refreshuser")
        tokens = self.client.post(
            "/api/v1/auth/login",
            data=json.dumps({"username": "refreshuser", "password": "password123"}),
            content_type="application/json",
        ).json()
        self.access_token = tokens["access"]
        self.refresh_token = tokens["refresh"]

    def test_refresh_menghasilkan_access_token_baru(self):
        resp = self.client.post(
            self.REFRESH_URL,
            data=json.dumps({"refresh": self.refresh_token}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("access", resp.json())

    def test_refresh_dengan_access_token_ditolak(self):
        resp = self.client.post(
            self.REFRESH_URL,
            data=json.dumps({"refresh": self.access_token}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)

    def test_refresh_dengan_token_tidak_valid(self):
        resp = self.client.post(
            self.REFRESH_URL,
            data=json.dumps({"refresh": "ini.bukan.token"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)


# Auth Me

class AuthMeTest(LMSTestCase):

    ME_URL = "/api/v1/auth/me"

    def setUp(self):
        super().setUp()
        self.make_user(
            "meuser", email="me@example.com"
        )
        self.headers = self.auth_header("meuser")

    def test_get_me_dengan_token_valid(self):
        resp = self.client.get(self.ME_URL, **self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["username"], "meuser")
        self.assertIn("roles", data)

    def test_get_me_tanpa_token(self):
        resp = self.client.get(self.ME_URL)
        self.assertEqual(resp.status_code, 401)

    def test_update_me_sukses(self):
        resp = self.client.put(
            self.ME_URL,
            data=json.dumps({"first_name": "Sabrina", "last_name": "Aska"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["first_name"], "Sabrina")

    def test_update_me_email_duplikat_ditolak(self):
        User.objects.create_user(
            username="other2", password="x", email="taken@example.com"
        )
        resp = self.client.put(
            self.ME_URL,
            data=json.dumps({"email": "taken@example.com"}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(resp.status_code, 400)
