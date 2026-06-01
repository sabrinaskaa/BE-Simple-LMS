import csv
from datetime import datetime
from pathlib import Path

from celery import shared_task
from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.db.models import Count

from .models import Course, CourseContent, CourseMember, LessonProgress
from .mongo import log_activity, log_learning_activity, get_mongo_db


@shared_task(bind=True, max_retries=3)
def send_enrollment_email(self, enrollment_id: int):
    member = CourseMember.objects.select_related('user_id', 'course_id').get(id=enrollment_id)
    user = member.user_id
    course = member.course_id

    send_mail(
        subject=f"Enrollment berhasil: {course.name}",
        message=f"Halo {user.first_name or user.username}, Anda berhasil enroll ke course {course.name}.",
        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@simple-lms.local'),
        recipient_list=[user.email] if user.email else [],
        fail_silently=True,
    )
    log_activity(user, 'send_enrollment_email', {'course_id': course.id, 'enrollment_id': enrollment_id})
    return {'status': 'sent', 'enrollment_id': enrollment_id}


@shared_task
def generate_certificate(enrollment_id: int):
    member = CourseMember.objects.select_related('user_id', 'course_id').get(id=enrollment_id)
    total_contents = CourseContent.objects.filter(course_id=member.course_id).count()
    completed_contents = LessonProgress.objects.filter(member=member, is_completed=True).count()

    if total_contents == 0 or completed_contents < total_contents:
        return {
            'status': 'not_ready',
            'message': 'Course belum selesai atau belum memiliki content.',
            'total_contents': total_contents,
            'completed_contents': completed_contents,
        }

    certificate_dir = Path(settings.MEDIA_ROOT) / 'certificates'
    certificate_dir.mkdir(parents=True, exist_ok=True)
    filename = f"certificate_course_{member.course_id_id}_user_{member.user_id_id}.txt"
    path = certificate_dir / filename
    path.write_text(
        f"CERTIFICATE OF COMPLETION\n"
        f"Student: {member.user_id.get_full_name() or member.user_id.username}\n"
        f"Course: {member.course_id.name}\n"
        f"Generated at: {datetime.now().isoformat()}\n"
    )

    log_learning_activity(member.user_id, member.course_id_id, 'certificate_generated', {'file': str(path)})
    return {'status': 'generated', 'file': str(path)}


@shared_task
def update_course_statistics():
    db = get_mongo_db()
    courses = Course.objects.annotate(
        member_count=Count('coursemember', distinct=True),
        content_count=Count('coursecontent', distinct=True),
    ).select_related('teacher')

    updated = 0
    for course in courses:
        completed_count = LessonProgress.objects.filter(member__course_id=course, is_completed=True).count()
        db.course_statistics.update_one(
            {'course_id': course.id},
            {
                '$set': {
                    'course_id': course.id,
                    'course_name': course.name,
                    'teacher_id': course.teacher_id,
                    'teacher_username': course.teacher.username,
                    'member_count': course.member_count,
                    'content_count': course.content_count,
                    'completed_lesson_count': completed_count,
                    'updated_at': datetime.utcnow(),
                }
            },
            upsert=True,
        )
        updated += 1

    return {'status': 'ok', 'updated_courses': updated}


@shared_task
def export_course_report(course_id: int):
    course = Course.objects.select_related('teacher').get(id=course_id)
    report_dir = Path(settings.MEDIA_ROOT) / 'reports'
    report_dir.mkdir(parents=True, exist_ok=True)
    filename = f"course_report_{course.id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.csv"
    path = report_dir / filename

    members = CourseMember.objects.select_related('user_id').filter(course_id=course).order_by('user_id__username')
    with path.open('w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['course_id', 'course_name', 'teacher', 'member_id', 'username', 'email', 'role'])
        for member in members:
            writer.writerow([
                course.id,
                course.name,
                course.teacher.username,
                member.id,
                member.user_id.username,
                member.user_id.email,
                member.roles,
            ])

    log_activity(course.teacher, 'export_course_report', {'course_id': course.id, 'file': str(path)})
    return {'status': 'generated', 'file': str(path)}
