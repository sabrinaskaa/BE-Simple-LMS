import json
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import Group, User
from django.test import Client, TestCase

from courses.models import (
    Category,
    Course,
    CourseMember,
    CourseContent,
    CourseReview,
    CourseSection,
    LessonProgress,
    Wishlist,
)


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

    # Helpers

    def get_token(self, username, password="pass123"):
        resp = self.client.post(
            "/api/v1/auth/login",
            data=json.dumps({"username": username, "password": password}),
            content_type="application/json",
        )
        self.assertIn("access", resp.json(),
                      f"Login gagal untuk '{username}': {resp.json()}")
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

    def make_course(self, teacher, name="Test Course", status="published",
                    level="beginner", price=50000, category=None):
        return Course.objects.create(
            name=name,
            description="Deskripsi",
            price=price,
            teacher=teacher,
            status=status,
            level=level,
            category=category,
        )


# Search / Filter / Sorting

class CourseSearchFilterTest(LMSTestCase):
    URL = "/api/v1/courses"

    def setUp(self):
        super().setUp()
        self.instructor = self.make_user("inst01", role="Instructor")
        self.cat = Category.objects.create(name="Teknologi", description="TI")
        self.make_course(self.instructor, name="Belajar Python",
                         level="beginner", price=100000, category=self.cat)
        self.make_course(self.instructor, name="Java Lanjutan",
                         level="advanced", price=200000)
        self.make_course(self.instructor, name="Draft Course",
                         status="draft", level="beginner", price=50000)

    def test_list_courses_default(self):
        resp = self.client.get(self.URL)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(data["total"], 3)
        self.assertIn("data", data)

    def test_search_course_by_name(self):
        resp = self.client.get(self.URL, {"search": "python"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], 1)
        self.assertIn("Python", data["data"][0]["name"])

    def test_filter_by_level_beginner(self):
        resp = self.client.get(self.URL, {"level": "beginner", "status": "published"})
        self.assertEqual(resp.status_code, 200)
        for course in resp.json()["data"]:
            self.assertEqual(course["level"], "beginner")
            self.assertEqual(course["status"], "published")

    def test_filter_by_status_published(self):
        resp = self.client.get(self.URL, {"status": "published"})
        self.assertEqual(resp.status_code, 200)
        names = [c["name"] for c in resp.json()["data"]]
        self.assertNotIn("Draft Course", names)

    def test_filter_by_category_id(self):
        resp = self.client.get(self.URL, {"category_id": self.cat.id})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["data"][0]["name"], "Belajar Python")

    def test_filter_by_price_range(self):
        resp = self.client.get(self.URL, {"min_price": 100000, "max_price": 150000})
        self.assertEqual(resp.status_code, 200)
        for course in resp.json()["data"]:
            self.assertGreaterEqual(course["price"], 100000)
            self.assertLessEqual(course["price"], 150000)

    def test_sorting_by_price_ascending(self):
        resp = self.client.get(self.URL, {"ordering": "price"})
        self.assertEqual(resp.status_code, 200)
        prices = [c["price"] for c in resp.json()["data"]]
        self.assertEqual(prices, sorted(prices))

    def test_sorting_by_price_descending(self):
        resp = self.client.get(self.URL, {"ordering": "-price"})
        self.assertEqual(resp.status_code, 200)
        prices = [c["price"] for c in resp.json()["data"]]
        self.assertEqual(prices, sorted(prices, reverse=True))

    def test_filter_level_tidak_valid_return_400(self):
        resp = self.client.get(self.URL, {"level": "expert"})
        self.assertEqual(resp.status_code, 400)

    def test_pagination_page_dan_page_size(self):
        resp = self.client.get(self.URL, {"page": 1, "page_size": 1})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data["data"]), 1)
        self.assertEqual(data["page_size"], 1)


# Reviews

class CourseReviewTest(LMSTestCase):
    def setUp(self):
        super().setUp()
        self.instructor = self.make_user("inst02", role="Instructor")
        self.student = self.make_user("std02", role="Student")
        self.course = self.make_course(self.instructor, name="Course Review Test")
        CourseMember.objects.create(
            course_id=self.course, user_id=self.student, roles="std"
        )

    def test_buat_review_sukses(self):
        resp = self.client.post(
            f"/api/v1/courses/{self.course.id}/reviews",
            data=json.dumps({"rating": 5, "review": "Sangat bagus!"}),
            content_type="application/json",
            **self.auth_header("std02"),
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["rating"], 5)

    def test_review_update_rating_avg_course(self):
        self.client.post(
            f"/api/v1/courses/{self.course.id}/reviews",
            data=json.dumps({"rating": 4, "review": "Lumayan"}),
            content_type="application/json",
            **self.auth_header("std02"),
        )
        self.course.refresh_from_db()
        self.assertGreater(float(self.course.rating_avg), 0)

    def test_get_reviews_course(self):
        CourseReview.objects.create(
            course=self.course, user=self.student, rating=4, review="Bagus"
        )
        resp = self.client.get(f"/api/v1/courses/{self.course.id}/reviews")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("rating_avg", data)
        self.assertIn("data", data)
        self.assertGreaterEqual(len(data["data"]), 1)

    def test_review_tanpa_enroll_ditolak(self):
        self.make_user("notenrolled", role="Student")
        resp = self.client.post(
            f"/api/v1/courses/{self.course.id}/reviews",
            data=json.dumps({"rating": 3, "review": "Test"}),
            content_type="application/json",
            **self.auth_header("notenrolled"),
        )
        self.assertEqual(resp.status_code, 403)

    def test_rating_di_luar_range_ditolak(self):
        resp = self.client.post(
            f"/api/v1/courses/{self.course.id}/reviews",
            data=json.dumps({"rating": 6, "review": "Test"}),
            content_type="application/json",
            **self.auth_header("std02"),
        )
        self.assertEqual(resp.status_code, 400)


# Wishlist

class WishlistTest(LMSTestCase):

    def setUp(self):
        super().setUp()
        self.student = self.make_user("std03", role="Student")
        inst = self.make_user("inst03", role="Instructor")
        self.course = self.make_course(inst, name="Wishlist Course Test")

    def test_tambah_ke_wishlist_sukses(self):
        resp = self.client.post(
            "/api/v1/wishlist",
            data=json.dumps({"course_id": self.course.id}),
            content_type="application/json",
            **self.auth_header("std03"),
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["course_id"], self.course.id)

    def test_tambah_wishlist_duplikat_return_409(self):
        Wishlist.objects.create(user=self.student, course=self.course)
        resp = self.client.post(
            "/api/v1/wishlist",
            data=json.dumps({"course_id": self.course.id}),
            content_type="application/json",
            **self.auth_header("std03"),
        )
        self.assertEqual(resp.status_code, 409)

    def test_list_wishlist(self):
        Wishlist.objects.create(user=self.student, course=self.course)
        resp = self.client.get("/api/v1/wishlist", **self.auth_header("std03"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("data", data)
        self.assertEqual(data["total"], 1)

    def test_hapus_dari_wishlist(self):
        Wishlist.objects.create(user=self.student, course=self.course)
        resp = self.client.delete(
            f"/api/v1/wishlist/{self.course.id}",
            **self.auth_header("std03"),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(
            Wishlist.objects.filter(user=self.student, course=self.course).exists()
        )

    def test_wishlist_butuh_login(self):
        resp = self.client.get("/api/v1/wishlist")
        self.assertEqual(resp.status_code, 401)


# Progress

class ProgressTest(LMSTestCase):
    def setUp(self):
        super().setUp()
        inst = self.make_user("inst04", role="Instructor")
        self.student = self.make_user("std04", role="Student")
        self.course = self.make_course(inst, name="Progress Test Course")
        self.membership = CourseMember.objects.create(
            course_id=self.course, user_id=self.student, roles="std"
        )
        section = CourseSection.objects.create(
            course=self.course, title="Section 1", order=1
        )
        self.lesson1 = CourseContent.objects.create(
            name="Lesson 1", description="desc",
            course_id=self.course, section=section, order=1
        )
        self.lesson2 = CourseContent.objects.create(
            name="Lesson 2", description="desc",
            course_id=self.course, section=section, order=2
        )

    def test_tandai_lesson_selesai(self):
        resp = self.client.post(
            f"/api/v1/enrollments/{self.membership.id}/progress",
            data=json.dumps({"content_id": self.lesson1.id}),
            content_type="application/json",
            **self.auth_header("std04"),
        )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(resp.json()["is_completed"])

    def test_get_progress_detail(self):
        LessonProgress.objects.create(
            member=self.membership, content=self.lesson1, is_completed=True
        )
        resp = self.client.get(
            f"/api/v1/enrollments/{self.membership.id}/progress",
            **self.auth_header("std04"),
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("total_lessons", data)
        self.assertIn("completed_lessons", data)
        self.assertIn("progress_percent", data)
        self.assertIn("sections", data)
        self.assertEqual(data["completed_lessons"], 1)
        self.assertIn("lessons", data["sections"][0])

    def test_progress_enrollment_orang_lain_ditolak(self):
        self.make_user("std04b", role="Student")
        resp = self.client.post(
            f"/api/v1/enrollments/{self.membership.id}/progress",
            data=json.dumps({"content_id": self.lesson1.id}),
            content_type="application/json",
            **self.auth_header("std04b"),
        )
        self.assertEqual(resp.status_code, 403)


# Dashboard

class StudentDashboardTest(LMSTestCase):

    def setUp(self):
        super().setUp()
        inst = self.make_user("inst05", role="Instructor")
        self.student = self.make_user("std05", role="Student")
        self.course = self.make_course(inst, name="Dashboard Course Test")
        CourseMember.objects.create(
            course_id=self.course, user_id=self.student, roles="std"
        )

    def test_dashboard_student_struktur_response(self):
        resp = self.client.get(
            "/api/v1/dashboard/student", **self.auth_header("std05")
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        required_keys = [
            "total_enrolled", "total_completed", "wishlist_count",
            "active_courses", "completed_courses", "wishlist", "recommended_courses",
        ]
        for key in required_keys:
            self.assertIn(key, data, f"Key '{key}' tidak ada di response dashboard")

    def test_dashboard_menampilkan_course_yang_diikuti(self):
        resp = self.client.get(
            "/api/v1/dashboard/student", **self.auth_header("std05")
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total_enrolled"], 1)
        all_courses = data["active_courses"] + data["completed_courses"]
        course_ids = [c["course_id"] for c in all_courses]
        self.assertIn(self.course.id, course_ids)

    def test_dashboard_tanpa_login_return_401(self):
        resp = self.client.get("/api/v1/dashboard/student")
        self.assertEqual(resp.status_code, 401)
