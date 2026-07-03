import factory
from django.contrib.auth.models import Group, User

from .models import Category, Course, CourseContent, CourseMember, CourseReview, CourseSection


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        django_get_or_create = ("username",)

    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.LazyAttribute(lambda obj: f"{obj.username}@example.com")
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")

    @factory.post_generation
    def password(self, create, extracted, **kwargs):
        self.set_password(extracted or "password123")
        if create:
            self.save()

    @factory.post_generation
    def groups(self, create, extracted, **kwargs):
        if not create:
            return
        if extracted:
            for group_name in extracted:
                group, _ = Group.objects.get_or_create(name=group_name)
                self.groups.add(group)


class CategoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Category
        django_get_or_create = ("name",)

    name = factory.Sequence(lambda n: f"Category {n}")
    description = factory.Faker("sentence")


class CourseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Course

    name = factory.Sequence(lambda n: f"Course {n}")
    description = factory.Faker("paragraph")
    price = 100000
    teacher = factory.SubFactory(UserFactory, groups=["Instructor"])
    category = factory.SubFactory(CategoryFactory)
    level = "beginner"
    status = "published"


class CourseSectionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CourseSection

    course = factory.SubFactory(CourseFactory)
    title = factory.Sequence(lambda n: f"Section {n}")
    order = factory.Sequence(lambda n: n + 1)


class CourseContentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CourseContent

    course_id = factory.SubFactory(CourseFactory)
    section = factory.SubFactory(CourseSectionFactory)
    name = factory.Sequence(lambda n: f"Lesson {n}")
    description = factory.Faker("sentence")
    body = factory.Faker("paragraph")
    order = factory.Sequence(lambda n: n + 1)


class CourseMemberFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CourseMember

    course_id = factory.SubFactory(CourseFactory)
    user_id = factory.SubFactory(UserFactory, groups=["Student"])
    roles = "std"


class CourseReviewFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CourseReview

    course = factory.SubFactory(CourseFactory)
    user = factory.SubFactory(UserFactory, groups=["Student"])
    rating = 5
    review = factory.Faker("sentence")
