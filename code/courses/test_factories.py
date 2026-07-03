from django.test import TestCase

from .factories import CourseFactory, CourseMemberFactory, CourseReviewFactory


class FactorySmokeTest(TestCase):
    def test_factories_create_core_lms_objects(self):
        course = CourseFactory()
        member = CourseMemberFactory(course_id=course)
        review = CourseReviewFactory(course=course, user=member.user_id)

        self.assertEqual(member.course_id_id, course.id)
        self.assertEqual(review.course_id, course.id)
        self.assertEqual(review.user_id, member.user_id_id)
