import json
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import Group, User
from django.test import Client, TestCase

from courses.models import (
    Course,
    CourseContent,
    CourseSection,
)


# Base setup (sama dengan LMSTestCase di test_courses.py)

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


class OrderingTestCase(TestCase):

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
        resp = self.client.post(
            "/api/v1/auth/login",
            data=json.dumps({"username": username, "password": password}),
            content_type="application/json",
        )
        self.assertIn("access", resp.json(),
                      f"Login gagal untuk '{username}': {resp.json()}")
        return resp.json()["access"]

    def auth(self, username, password="pass123"):
        return {"HTTP_AUTHORIZATION": f"Bearer {self.get_token(username, password)}"}

    def make_user(self, username, password="pass123", role=None):
        user = User.objects.create_user(
            username=username,
            password=password,
            email=f"{username}@test.com",
        )
        if role:
            g, _ = Group.objects.get_or_create(name=role)
            user.groups.add(g)
        return user

    def make_course(self, teacher, name="Test Course"):
        return Course.objects.create(
            name=name,
            description="Deskripsi test",
            price=50000,
            teacher=teacher,
        )

    def make_section(self, course, title="Section A", order=None):
        kwargs = {"course": course, "title": title}
        if order is not None:
            kwargs["order"] = order
        else:
            # gunakan logic yang sama dengan API
            from django.db.models import Max
            agg = CourseSection.objects.filter(course=course).aggregate(Max("order"))
            kwargs["order"] = (agg["order__max"] or 0) + 1
        return CourseSection.objects.create(**kwargs)

    def make_content(self, course, name="Lesson A", section=None, order=None):
        from django.db.models import Max
        section_id = section.id if section else None
        if order is None:
            agg = CourseContent.objects.filter(
                course_id=course, section_id=section_id
            ).aggregate(Max("order"))
            order = (agg["order__max"] or 0) + 1
        return CourseContent.objects.create(
            name=name,
            description="desc",
            course_id=course,
            section=section,
            order=order,
        )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Section ordering tests
# ─────────────────────────────────────────────────────────────────────────────

class SectionOrderingTest(OrderingTestCase):

    def setUp(self):
        super().setUp()
        self.instructor = self.make_user("inst_order1", role="Instructor")
        self.course = self.make_course(self.instructor, "Course Ordering Test")

    def _post_section(self, payload):
        return self.client.post(
            f"/api/v1/courses/{self.course.id}/sections",
            data=json.dumps(payload),
            content_type="application/json",
            **self.auth("inst_order1"),
        )

    def test_create_section_tanpa_order_mendapat_order_1(self):
        resp = self._post_section({"title": "Pendahuluan"})
        self.assertEqual(resp.status_code, 201, resp.json())
        self.assertEqual(resp.json()["order"], 1)

    def test_create_section_kedua_tanpa_order_mendapat_order_2(self):
        self._post_section({"title": "Section 1"})
        resp = self._post_section({"title": "Section 2"})
        self.assertEqual(resp.status_code, 201, resp.json())
        self.assertEqual(resp.json()["order"], 2)

    def test_create_section_urutan_auto_increment(self):
        orders = []
        for i in range(3):
            resp = self._post_section({"title": f"Section {i+1}"})
            self.assertEqual(resp.status_code, 201, resp.json())
            orders.append(resp.json()["order"])
        self.assertEqual(orders, [1, 2, 3])

    def test_create_section_dengan_order_manual_sukses(self):
        resp = self._post_section({"title": "Section Manual", "order": 5})
        self.assertEqual(resp.status_code, 201, resp.json())
        self.assertEqual(resp.json()["order"], 5)

    def test_create_section_order_duplikat_ditolak_409(self):
        self._post_section({"title": "Section A", "order": 1})
        resp = self._post_section({"title": "Section B", "order": 1})
        self.assertEqual(resp.status_code, 409, resp.json())
        self.assertIn("order=1", resp.json().get("detail", ""))

    def test_create_section_order_nol_ditolak_400(self):
        resp = self._post_section({"title": "Bad Order", "order": 0})
        self.assertEqual(resp.status_code, 400, resp.json())

    def test_create_section_order_negatif_ditolak_400(self):
        resp = self._post_section({"title": "Bad Order", "order": -1})
        self.assertEqual(resp.status_code, 400, resp.json())

    def test_update_section_order_duplikat_ditolak_409(self):
        s1 = self.make_section(self.course, "Section 1", order=1)
        s2 = self.make_section(self.course, "Section 2", order=2)

        resp = self.client.patch(
            f"/api/v1/courses/{self.course.id}/sections/{s2.id}",
            data=json.dumps({"order": 1}),
            content_type="application/json",
            **self.auth("inst_order1"),
        )
        self.assertEqual(resp.status_code, 409, resp.json())

    def test_update_section_order_ke_nilai_sendiri_sukses(self):
        s1 = self.make_section(self.course, "Section 1", order=1)
        resp = self.client.patch(
            f"/api/v1/courses/{self.course.id}/sections/{s1.id}",
            data=json.dumps({"order": 1}),
            content_type="application/json",
            **self.auth("inst_order1"),
        )
        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual(resp.json()["order"], 1)

    def test_list_sections_terurut_berdasarkan_order(self):
        self.make_section(self.course, "Section 3", order=3)
        self.make_section(self.course, "Section 1", order=1)
        self.make_section(self.course, "Section 2", order=2)

        resp = self.client.get(f"/api/v1/courses/{self.course.id}/sections")
        self.assertEqual(resp.status_code, 200)
        orders = [s["order"] for s in resp.json()]
        self.assertEqual(orders, sorted(orders))
        self.assertEqual(orders, [1, 2, 3])


# 2. Content ordering tests

class ContentOrderingTest(OrderingTestCase):

    def setUp(self):
        super().setUp()
        self.instructor = self.make_user("inst_order2", role="Instructor")
        self.course = self.make_course(self.instructor, "Content Ordering Course")
        self.section = self.make_section(self.course, "Section A", order=1)

    def _post_content(self, payload):
        return self.client.post(
            f"/api/v1/courses/{self.course.id}/contents",
            data=json.dumps(payload),
            content_type="application/json",
            **self.auth("inst_order2"),
        )

    def test_create_content_tanpa_section_tanpa_order_dapat_order_1(self):
        resp = self._post_content({"name": "Lesson Pertama", "description": "desc"})
        self.assertEqual(resp.status_code, 201, resp.json())
        self.assertEqual(resp.json()["order"], 1)
        self.assertIsNone(resp.json()["section_id"])

    def test_create_content_tanpa_section_urutan_auto_increment(self):
        orders = []
        for i in range(3):
            resp = self._post_content({"name": f"Lesson {i+1}", "description": "desc"})
            self.assertEqual(resp.status_code, 201, resp.json())
            orders.append(resp.json()["order"])
        self.assertEqual(orders, [1, 2, 3])

    def test_create_content_dalam_section_tanpa_order_dapat_order_1(self):
        resp = self._post_content({
            "name": "Lesson Dalam Section",
            "description": "desc",
            "section_id": self.section.id,
        })
        self.assertEqual(resp.status_code, 201, resp.json())
        self.assertEqual(resp.json()["order"], 1)
        self.assertEqual(resp.json()["section_id"], self.section.id)

    def test_create_content_dalam_section_urutan_auto_increment(self):
        orders = []
        for i in range(3):
            resp = self._post_content({
                "name": f"Lesson {i+1}",
                "description": "desc",
                "section_id": self.section.id,
            })
            self.assertEqual(resp.status_code, 201, resp.json())
            orders.append(resp.json()["order"])
        self.assertEqual(orders, [1, 2, 3])

    def test_scope_section_dan_tanpa_section_tidak_saling_mempengaruhi(self):
        # Buat 2 content dalam section
        for i in range(2):
            self._post_content({
                "name": f"Lesson Dalam Section {i+1}",
                "description": "desc",
                "section_id": self.section.id,
            })
        # Buat content tanpa section
        resp = self._post_content({"name": "Lesson Tanpa Section", "description": "desc"})
        self.assertEqual(resp.status_code, 201, resp.json())
        # Counter tanpa section mulai dari 1 (tidak dipengaruhi counter dalam section)
        self.assertEqual(resp.json()["order"], 1)

    def test_create_content_order_duplikat_dalam_section_ditolak_409(self):
        self._post_content({
            "name": "Lesson A", "description": "desc",
            "section_id": self.section.id, "order": 1,
        })
        resp = self._post_content({
            "name": "Lesson B", "description": "desc",
            "section_id": self.section.id, "order": 1,
        })
        self.assertEqual(resp.status_code, 409, resp.json())
        self.assertIn("order=1", resp.json().get("detail", ""))

    def test_create_content_order_duplikat_tanpa_section_ditolak_409(self):
        self._post_content({"name": "Lesson A", "description": "desc", "order": 1})
        resp = self._post_content({"name": "Lesson B", "description": "desc", "order": 1})
        self.assertEqual(resp.status_code, 409, resp.json())

    def test_order_sama_beda_section_diizinkan(self):
        section2 = self.make_section(self.course, "Section B", order=2)

        resp1 = self._post_content({
            "name": "Lesson A", "description": "desc",
            "section_id": self.section.id, "order": 1,
        })
        resp2 = self._post_content({
            "name": "Lesson B", "description": "desc",
            "section_id": section2.id, "order": 1,
        })
        self.assertEqual(resp1.status_code, 201, resp1.json())
        self.assertEqual(resp2.status_code, 201, resp2.json())

    def test_create_content_order_nol_ditolak_400(self):
        resp = self._post_content({
            "name": "Bad Order", "description": "desc", "order": 0
        })
        self.assertEqual(resp.status_code, 400, resp.json())

    def test_create_content_duration_negatif_ditolak_400(self):
        resp = self._post_content({
            "name": "Bad Duration", "description": "desc", "duration_minutes": -5
        })
        self.assertEqual(resp.status_code, 400, resp.json())

    def test_update_content_order_duplikat_ditolak_409(self):
        c1 = self.make_content(self.course, "Lesson 1", section=self.section, order=1)
        c2 = self.make_content(self.course, "Lesson 2", section=self.section, order=2)

        resp = self.client.patch(
            f"/api/v1/courses/{self.course.id}/contents/{c2.id}",
            data=json.dumps({"order": 1}),
            content_type="application/json",
            **self.auth("inst_order2"),
        )
        self.assertEqual(resp.status_code, 409, resp.json())

    def test_update_content_order_ke_nilai_sendiri_sukses(self):
        c1 = self.make_content(self.course, "Lesson 1", section=self.section, order=1)
        resp = self.client.patch(
            f"/api/v1/courses/{self.course.id}/contents/{c1.id}",
            data=json.dumps({"order": 1}),
            content_type="application/json",
            **self.auth("inst_order2"),
        )
        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual(resp.json()["order"], 1)

    def test_update_content_pindah_section_validasi_scope_baru(self):
        section2 = self.make_section(self.course, "Section B", order=2)
        self.make_content(self.course, "Lesson di Section2", section=section2, order=1)

        c1 = self.make_content(self.course, "Lesson di Section1", section=self.section, order=1)

        # Pindahkan c1 ke section2 dengan order=1 → harus 409
        resp = self.client.patch(
            f"/api/v1/courses/{self.course.id}/contents/{c1.id}",
            data=json.dumps({"section_id": section2.id, "order": 1}),
            content_type="application/json",
            **self.auth("inst_order2"),
        )
        self.assertEqual(resp.status_code, 409, resp.json())


# 3. List ordering test

class ListOrderingTest(OrderingTestCase):

    def setUp(self):
        super().setUp()
        self.instructor = self.make_user("inst_order3", role="Instructor")
        self.course = self.make_course(self.instructor, "List Ordering Course")

    def test_list_contents_diurutkan_section_order_lalu_content_order(self):
        section_a = self.make_section(self.course, "Section A", order=1)
        section_b = self.make_section(self.course, "Section B", order=2)

        c_b1 = self.make_content(self.course, "B-Lesson-1", section=section_b, order=1)
        c_b2 = self.make_content(self.course, "B-Lesson-2", section=section_b, order=2)
        # Content dalam section_a (order 1) — Section A lebih kecil, harus duluan
        c_a2 = self.make_content(self.course, "A-Lesson-2", section=section_a, order=2)
        c_a1 = self.make_content(self.course, "A-Lesson-1", section=section_a, order=1)
        # Content tanpa section — muncul paling akhir
        c_none = self.make_content(self.course, "No-Section", section=None, order=1)

        resp = self.client.get(
            f"/api/v1/courses/{self.course.id}/contents",
            {"page_size": 10},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        ids = [d["id"] for d in data]

        expected_ids = [c_a1.id, c_a2.id, c_b1.id, c_b2.id, c_none.id]
        self.assertEqual(ids, expected_ids,
            f"Urutan salah. Expected: {expected_ids}, Got: {ids}")

    def test_list_contents_tanpa_section_urut_berdasarkan_order(self):
        c3 = self.make_content(self.course, "Lesson-3", section=None, order=3)
        c1 = self.make_content(self.course, "Lesson-1", section=None, order=1)
        c2 = self.make_content(self.course, "Lesson-2", section=None, order=2)

        resp = self.client.get(
            f"/api/v1/courses/{self.course.id}/contents",
            {"page_size": 10},
        )
        self.assertEqual(resp.status_code, 200)
        ids = [d["id"] for d in resp.json()["data"]]
        self.assertEqual(ids, [c1.id, c2.id, c3.id])


# 4. Seed data ordering test

class SeedOrderingTest(OrderingTestCase):

    def setUp(self):
        super().setUp()
        self.instructor = self.make_user("inst_seed", role="Instructor")

    def test_seed_section_tidak_ada_duplikat_order_dalam_course(self):
        import random
        random.seed(42)

        courses = [self.make_course(self.instructor, f"Course {i}") for i in range(5)]
        SECTION_TITLES = ['Pendahuluan', 'Materi Dasar', 'Konsep Inti', 'Proyek Akhir']

        sections_to_create = []
        for course in courses:
            num_sections = random.randint(2, 4)
            for j in range(num_sections):
                sections_to_create.append(CourseSection(
                    course=course,
                    title=SECTION_TITLES[j % len(SECTION_TITLES)],
                    order=j + 1,  # 1-based
                ))
        CourseSection.objects.bulk_create(sections_to_create)

        from django.db.models import Count
        dups = (
            CourseSection.objects
            .values("course_id", "order")
            .annotate(cnt=Count("id"))
            .filter(cnt__gt=1)
        )
        self.assertEqual(
            dups.count(), 0,
            f"Ditemukan duplikat section order: {list(dups)}"
        )

    def test_seed_content_tidak_ada_duplikat_order_dalam_scope(self):
        import random
        random.seed(42)

        courses = [self.make_course(self.instructor, f"SeedCourse {i}") for i in range(3)]

        course_order_counters = {}
        contents_to_create = []
        for i in range(30):
            course = courses[i % len(courses)]
            cid = course.id
            course_order_counters[cid] = course_order_counters.get(cid, 0) + 1
            order = course_order_counters[cid]
            contents_to_create.append(CourseContent(
                name=f"Content {i}",
                description="desc",
                course_id=course,
                order=order,
            ))

        CourseContent.objects.bulk_create(contents_to_create)

        from django.db.models import Count
        dups = (
            CourseContent.objects
            .filter(section__isnull=True)
            .values("course_id", "order")
            .annotate(cnt=Count("id"))
            .filter(cnt__gt=1)
        )
        self.assertEqual(
            dups.count(), 0,
            f"Ditemukan duplikat content order: {list(dups)}"
        )

    def test_seed_content_dalam_section_tidak_ada_duplikat_order(self):
        import random
        random.seed(42)

        courses = [self.make_course(self.instructor, f"SecCourse {i}") for i in range(2)]
        sections = []
        for course in courses:
            for j in range(3):
                sections.append(CourseSection.objects.create(
                    course=course, title=f"Section {j+1}", order=j + 1
                ))

        section_order_counters = {}
        contents_to_create = []
        for i in range(30):
            section = random.choice(sections)
            key = (section.course_id, section.id)
            section_order_counters[key] = section_order_counters.get(key, 0) + 1
            contents_to_create.append(CourseContent(
                name=f"SectionContent {i}",
                description="desc",
                course_id=section.course,
                section=section,
                order=section_order_counters[key],
            ))

        CourseContent.objects.bulk_create(contents_to_create)

        from django.db.models import Count
        dups = (
            CourseContent.objects
            .filter(section__isnull=False)
            .values("course_id", "section_id", "order")
            .annotate(cnt=Count("id"))
            .filter(cnt__gt=1)
        )
        self.assertEqual(
            dups.count(), 0,
            f"Ditemukan duplikat content order dalam section: {list(dups)}"
        )
