import json
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import Group, User
from django.test import Client, TestCase

from courses.models import Category, Course, CourseMember


# Shared base class

def make_redis_mock():
    m = MagicMock()
    m.get.return_value = None
    m.incr.return_value = 1
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

        self._patch_cache_redis = patch("courses.cache.get_redis_client", return_value=redis_mock)
        self._patch_rate_redis = patch("courses.rate_limit.get_redis_client", return_value=redis_mock)
        self._patch_log = patch("courses.api.log_activity")
        self._patch_log_learn = patch("courses.api.log_learning_activity")
        self._patch_welcome = patch("courses.api.send_welcome_email")
        self._patch_enroll_email = patch("courses.api.send_enrollment_email")
        self._patch_cert = patch("courses.api.generate_certificate")

        self._patch_cache_redis.start()
        self._patch_rate_redis.start()
        self._patch_log.start()
        self._patch_log_learn.start()
        m_welcome = self._patch_welcome.start()
        m_welcome.delay = lambda *a, **kw: None
        m_enroll = self._patch_enroll_email.start()
        m_enroll.delay = lambda *a, **kw: None
        m_cert = self._patch_cert.start()
        m_cert.delay = lambda *a, **kw: None

    def tearDown(self):
        self._patch_cache_redis.stop()
        self._patch_rate_redis.stop()
        self._patch_log.stop()
        self._patch_log_learn.stop()
        self._patch_welcome.stop()
        self._patch_enroll_email.stop()
        self._patch_cert.stop()

    def get_token(self, username, password="pass123"):
        # Jika input berupa User object, ambil string username-nya
        uname = username.username if hasattr(username, "username") else username
        resp = self.client.post(
            "/api/v1/auth/login",
            data=json.dumps({"username": uname, "password": password}),
            content_type="application/json",
        )
        self.assertIn("access", resp.json(),
                      f"Login gagal untuk '{uname}': {resp.json()}")
        return resp.json()["access"]

    def auth_header(self, username, password="pass123"):
        return {"HTTP_AUTHORIZATION": f"Bearer {self.get_token(username, password)}"}

    def make_user(self, username, password="pass123", email=None, role=None):
        user = User.objects.create_user(
            username=username,
            password=password,
            email=email or f"{username}@test.com",
        )
        if role:
            g, _ = Group.objects.get_or_create(name=role)
            user.groups.add(g)
        return user

    def make_course(self, teacher, name="Test Course", status="published"):
        return Course.objects.create(
            name=name,
            description="Deskripsi",
            price=100000,
            teacher=teacher,
            status=status,
            level="beginner",
        )


# RBAC: Create Course

class RBACCreateCourseTest(LMSTestCase):
    def setUp(self):
        super().setUp()
        self.url = "/api/v1/courses"
        self.instructor = self.make_user("rbac_inst", role="Instructor")
        self.student = self.make_user("rbac_std", role="Student")
        self.admin = self.make_user("rbac_admin")
        self.admin.is_superuser = True
        self.admin.save()
        self.course_data = {
            "name": "RBAC Test Course",
            "description": "Deskripsi",
            "price": 50000,
            "level": "beginner",
            "status": "published",
        }

    def test_instructor_bisa_buat_course(self):
        token = self.get_token(self.instructor)
        response = self.client.post(
            self.url,
            data=json.dumps(self.course_data),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 201)

    def test_student_tidak_bisa_buat_course(self):
        token = self.get_token(self.student)
        response = self.client.post(
            self.url,
            data=json.dumps(self.course_data),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_tidak_bisa_buat_course(self):
        response = self.client.post(
            self.url,
            data=json.dumps(self.course_data),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_admin_bisa_buat_course(self):
        token = self.get_token(self.admin)
        response = self.client.post(
            self.url,
            data=json.dumps(self.course_data),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 201)


# RBAC: Update / Delete Course

class RBACUpdateDeleteCourseTest(LMSTestCase):

    def setUp(self):
        super().setUp()
        self.owner = self.make_user("owner_inst", role="Instructor")
        self.other_inst = self.make_user("other_inst", role="Instructor")
        self.student = self.make_user("rbac_std2", role="Student")
        self.admin = self.make_user("rbac_admin2")
        self.admin.is_superuser = True
        self.admin.save()
        self.course = self.make_course(self.owner, name="Owner Course")

    def test_owner_bisa_update_course_sendiri(self):
        token = self.get_token(self.owner)
        response = self.client.patch(
            f"/api/v1/courses/{self.course.id}",
            data=json.dumps({"name": "Updated Name"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Updated Name")

    def test_instructor_lain_tidak_bisa_update_course(self):
        token = self.get_token(self.other_inst)
        response = self.client.patch(
            f"/api/v1/courses/{self.course.id}",
            data=json.dumps({"name": "Hacked Name"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 403)

    def test_student_tidak_bisa_update_course(self):
        token = self.get_token(self.student)
        response = self.client.patch(
            f"/api/v1/courses/{self.course.id}",
            data=json.dumps({"name": "Student Hack"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_bisa_update_course_manapun(self):
        token = self.get_token(self.admin)
        response = self.client.patch(
            f"/api/v1/courses/{self.course.id}",
            data=json.dumps({"name": "Admin Updated"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 200)


# RBAC: Category

class RBACCategoryTest(LMSTestCase):

    def setUp(self):
        super().setUp()
        self.admin = self.make_user("cat_admin")
        self.admin.is_superuser = True
        self.admin.save()
        self.instructor = self.make_user("cat_inst", role="Instructor")
        self.student = self.make_user("cat_std", role="Student")

    def test_admin_bisa_buat_kategori(self):
        token = self.get_token(self.admin)
        response = self.client.post(
            "/api/v1/categories",
            data=json.dumps({"name": "Kategori Baru", "description": "Deskripsi"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 201)

    def test_instructor_tidak_bisa_buat_kategori(self):
        token = self.get_token(self.instructor)
        response = self.client.post(
            "/api/v1/categories",
            data=json.dumps({"name": "Kategori Hack", "description": "Coba"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 403)

    def test_student_tidak_bisa_buat_kategori(self):
        token = self.get_token(self.student)
        response = self.client.post(
            "/api/v1/categories",
            data=json.dumps({"name": "Kategori Student", "description": "Coba"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_tidak_bisa_buat_kategori(self):
        response = self.client.post(
            "/api/v1/categories",
            data=json.dumps({"name": "Anon Kategori", "description": "Anon"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)


# RBAC: Enrollment

class RBACEnrollmentTest(LMSTestCase):

    def setUp(self):
        super().setUp()
        self.instructor = self.make_user("enroll_inst", role="Instructor")
        self.student = self.make_user("enroll_std", role="Student")
        self.course = self.make_course(self.instructor, name="Enroll RBAC Course")

    def test_student_bisa_enroll(self):
        token = self.get_token(self.student)
        response = self.client.post(
            "/api/v1/enrollments",
            data=json.dumps({"course_id": self.course.id}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 201)

    def test_unauthenticated_tidak_bisa_enroll(self):
        response = self.client.post(
            "/api/v1/enrollments",
            data=json.dumps({"course_id": self.course.id}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_enroll_dua_kali_return_400(self):
        token = self.get_token(self.student)
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        self.client.post(
            "/api/v1/enrollments",
            data=json.dumps({"course_id": self.course.id}),
            content_type="application/json",
            **headers,
        )
        response = self.client.post(
            "/api/v1/enrollments",
            data=json.dumps({"course_id": self.course.id}),
            content_type="application/json",
            **headers,
        )
        self.assertEqual(response.status_code, 400)


# RBAC: Section

class RBACSectionTest(LMSTestCase):

    def setUp(self):
        super().setUp()
        self.owner = self.make_user("sec_owner", role="Instructor")
        self.student = self.make_user("sec_std", role="Student")
        self.other_inst = self.make_user("sec_other", role="Instructor")
        self.course = self.make_course(self.owner, name="Section RBAC Course")

    def test_owner_bisa_buat_section(self):
        token = self.get_token(self.owner)
        response = self.client.post(
            f"/api/v1/courses/{self.course.id}/sections",
            data=json.dumps({"title": "Section Baru", "order": 1}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 201)

    def test_student_tidak_bisa_buat_section(self):
        token = self.get_token(self.student)
        response = self.client.post(
            f"/api/v1/courses/{self.course.id}/sections",
            data=json.dumps({"title": "Section Student", "order": 1}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 403)

    def test_instructor_lain_tidak_bisa_buat_section(self):
        token = self.get_token(self.other_inst)
        response = self.client.post(
            f"/api/v1/courses/{self.course.id}/sections",
            data=json.dumps({"title": "Section Hack", "order": 1}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_tidak_bisa_buat_section(self):
        response = self.client.post(
            f"/api/v1/courses/{self.course.id}/sections",
            data=json.dumps({"title": "Anon Section", "order": 1}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)
