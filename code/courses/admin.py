from django.contrib import admin

from .models import (
    Category,
    Comment,
    Course,
    CourseContent,
    CourseMember,
    CoursePrerequisite,
    CoursePublishRequest,
    CourseReview,
    CourseSection,
    LessonProgress,
    Quiz,
    QuizAttempt,
    QuizAttemptAnswer,
    QuizQuestion,
    Wishlist,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'description')
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'teacher', 'price', 'level', 'status', 'rating_avg', 'created_at')
    list_filter = ('category', 'teacher', 'level', 'status', 'created_at')
    search_fields = ('name', 'description')
    ordering = ('-created_at',)


@admin.register(CourseMember)
class CourseMemberAdmin(admin.ModelAdmin):
    list_display = ('course_id', 'user_id', 'roles')
    list_filter = ('roles', 'course_id')
    search_fields = ('course_id__name', 'user_id__username')


@admin.register(CourseSection)
class CourseSectionAdmin(admin.ModelAdmin):
    list_display = ('title', 'course', 'order', 'created_at')
    list_filter = ('course',)
    search_fields = ('title', 'course__name')
    ordering = ('course', 'order')


@admin.register(CourseContent)
class CourseContentAdmin(admin.ModelAdmin):
    list_display = ('name', 'subject', 'course_id', 'section', 'order', 'duration_minutes')
    list_filter = ('course_id', 'section')
    search_fields = ('name', 'subject', 'description', 'body')
    ordering = ('course_id', 'section__order', 'order')


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ('content_id', 'member_id', 'comment')
    list_filter = ('content_id',)
    search_fields = ('comment',)


@admin.register(LessonProgress)
class LessonProgressAdmin(admin.ModelAdmin):
    list_display = ('member', 'content', 'is_completed', 'completed_at')
    list_filter = ('is_completed', 'content__course_id')
    search_fields = ('member__user_id__username', 'content__name')


@admin.register(CourseReview)
class CourseReviewAdmin(admin.ModelAdmin):
    list_display = ('course', 'user', 'rating', 'created_at')
    list_filter = ('rating', 'course')
    search_fields = ('course__name', 'user__username', 'review')


@admin.register(Wishlist)
class WishlistAdmin(admin.ModelAdmin):
    list_display = ('user', 'course', 'created_at')
    list_filter = ('course',)
    search_fields = ('user__username', 'course__name')


@admin.register(CoursePublishRequest)
class CoursePublishRequestAdmin(admin.ModelAdmin):
    list_display = ('course', 'requester', 'status', 'reviewer', 'requested_at', 'reviewed_at')
    list_filter = ('status', 'requested_at')
    search_fields = ('course__name', 'requester__username', 'rejection_reason')


@admin.register(CoursePrerequisite)
class CoursePrerequisiteAdmin(admin.ModelAdmin):
    list_display = ('course', 'required_course', 'created_at')
    search_fields = ('course__name', 'required_course__name')


class QuizQuestionInline(admin.TabularInline):
    model = QuizQuestion
    extra = 1
    fields = ('question_text', 'choices', 'correct_answer', 'points', 'explanation')


@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
    list_display = ('title', 'course', 'section', 'minimum_score', 'question_count', 'is_active', 'created_at')
    list_filter = ('course', 'section', 'is_active')
    search_fields = ('title', 'description', 'course__name')
    inlines = [QuizQuestionInline]


@admin.register(QuizQuestion)
class QuizQuestionAdmin(admin.ModelAdmin):
    list_display = ('quiz', 'question_text', 'correct_answer', 'points', 'created_at')
    list_filter = ('quiz',)
    search_fields = ('question_text', 'correct_answer')


class QuizAttemptAnswerInline(admin.TabularInline):
    model = QuizAttemptAnswer
    extra = 0
    readonly_fields = ('question', 'selected_answer', 'is_correct')
    can_delete = False


@admin.register(QuizAttempt)
class QuizAttemptAdmin(admin.ModelAdmin):
    list_display = ('quiz', 'member', 'attempt_number', 'score', 'passed', 'cooldown_until', 'submitted_at')
    list_filter = ('passed', 'quiz', 'submitted_at')
    search_fields = ('quiz__title', 'member__user_id__username')
    inlines = [QuizAttemptAnswerInline]


@admin.register(QuizAttemptAnswer)
class QuizAttemptAnswerAdmin(admin.ModelAdmin):
    list_display = ('attempt', 'question', 'selected_answer', 'is_correct')
    list_filter = ('is_correct',)
