import csv
from datetime import datetime, timedelta
from pathlib import Path

from celery import chain, group, shared_task
from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.db.models import Count


# =============================================================================
# Task 1: Enrollment Notification (integrasi di POST /enrollments)
# =============================================================================

@shared_task(bind=True, max_retries=3)
def send_enrollment_email(self, enrollment_id: int):
    from courses.models import CourseMember  # import di dalam task → hindari circular import

    member = CourseMember.objects.select_related('user_id', 'course_id').get(id=enrollment_id)
    user = member.user_id
    course = member.course_id

    send_mail(
        subject=f"Enrollment berhasil: {course.name}",
        message=(
            f"Halo {user.first_name or user.username},\n\n"
            f"Anda berhasil mendaftar di course '{course.name}'.\n"
            f"Selamat belajar!\n\n"
            f"— Tim Simple LMS"
        ),
        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@simple-lms.local'),
        recipient_list=[user.email] if user.email else [],
        fail_silently=True,
    )

    # Log ke MongoDB (opsional, gunakan try/except agar tidak gagal jika Mongo down)
    try:
        from courses.mongo import log_activity
        log_activity(user, 'send_enrollment_email', {
            'course_id': course.id,
            'enrollment_id': enrollment_id,
        })
    except Exception:
        pass

    return {'status': 'sent', 'enrollment_id': enrollment_id}


# =============================================================================
# Task 2: Generate Course Report (integrasi di POST /reports/generate/{id}/)
# =============================================================================

@shared_task
def generate_course_report(course_id: int):
    from courses.models import Course, CourseMember, CourseContent, Comment

    course = Course.objects.get(pk=course_id)
    members = CourseMember.objects.filter(course_id=course).count()
    contents = CourseContent.objects.filter(course_id=course).count()
    comments = Comment.objects.filter(content_id__course_id=course).count()

    report = {
        "course_id": course.id,
        "course": course.name,
        "total_members": members,
        "total_contents": contents,
        "total_comments": comments,
        "generated_at": str(datetime.now()),
    }

    # Simpan ke MongoDB untuk histori laporan
    try:
        from courses.mongo import get_mongo_db
        db = get_mongo_db()
        db.course_reports.insert_one({**report})
    except Exception:
        pass

    print(f"[generate_course_report] Report untuk '{course.name}': {report}")
    return report


# =============================================================================
# Task 3: Welcome Email (integrasi di POST /auth/register)
# =============================================================================

@shared_task
def send_welcome_email(user_id: int):
    user = User.objects.get(pk=user_id)

    print(f"[{datetime.now()}] Sending welcome email to {user.email}")
    print(f"Subject: Selamat datang di Simple LMS!")
    print(f"Body: Halo {user.first_name or user.username}, selamat bergabung!")

    send_mail(
        subject="Selamat datang di Simple LMS!",
        message=(
            f"Halo {user.first_name or user.username},\n\n"
            f"Akun Anda berhasil dibuat. Selamat bergabung di Simple LMS!\n\n"
            f"Username: {user.username}\n"
            f"Email: {user.email}\n\n"
            f"— Tim Simple LMS"
        ),
        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@simple-lms.local'),
        recipient_list=[user.email] if user.email else [],
        fail_silently=True,
    )

    return f"Welcome email sent to {user.email}"


# =============================================================================
# Task 4: Certificate Generator
# =============================================================================

@shared_task
def generate_certificate(enrollment_id: int):
    from courses.models import CourseMember, CourseContent, LessonProgress

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

    try:
        from courses.mongo import log_learning_activity
        log_learning_activity(member.user_id, member.course_id_id, 'certificate_generated', {'file': str(path)})
    except Exception:
        pass

    return {'status': 'generated', 'file': str(path)}


# =============================================================================
# Task 5: Export Course Report ke CSV (integrasi di POST /courses/{id}/export-report)
# =============================================================================

@shared_task
def export_course_report(course_id: int):
    from courses.models import Course, CourseMember

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

    try:
        from courses.mongo import log_activity
        log_activity(course.teacher, 'export_course_report', {'course_id': course.id, 'file': str(path)})
    except Exception:
        pass

    return {'status': 'generated', 'file': str(path)}


# =============================================================================
# Task 6: Update Course Statistics (Periodic — setiap jam)
# =============================================================================

@shared_task
def update_course_statistics():
    from courses.models import Course, LessonProgress
    from courses.mongo import get_mongo_db

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


# =============================================================================
# Task 7: Daily Stats (Periodic — setiap hari pukul 00:00)
# =============================================================================

@shared_task
def generate_daily_stats():
    from courses.models import Course, CourseMember

    total_courses = Course.objects.count()
    total_users = User.objects.count()
    total_enrollments = CourseMember.objects.count()

    stats = {
        "date": str(datetime.now().date()),
        "total_courses": total_courses,
        "total_users": total_users,
        "total_enrollments": total_enrollments,
        "generated_at": str(datetime.now()),
    }

    # Simpan ke MongoDB untuk histori statistik harian
    try:
        from courses.mongo import get_mongo_db
        db = get_mongo_db()
        db.daily_stats.insert_one({**stats})
    except Exception:
        pass

    print(f"[Daily Stats] {stats}")
    return stats


# =============================================================================
# Task 8: Cleanup Old Logs (Periodic — setiap hari pukul 02:00)
# =============================================================================

@shared_task
def cleanup_old_logs():
    threshold = datetime.now() - timedelta(days=30)

    # Hapus dokumen log dari MongoDB yang sudah > 30 hari
    deleted_count = 0
    try:
        from courses.mongo import get_mongo_db
        db = get_mongo_db()
        result = db.activity_logs.delete_many({"timestamp": {"$lt": threshold}})
        deleted_count = result.deleted_count
    except Exception:
        pass

    print(f"[Cleanup] Old logs before {threshold} cleaned up. Deleted: {deleted_count} records.")
    return {"cleaned_before": str(threshold), "deleted_count": deleted_count}


# =============================================================================
# Task 9: Email with Retry (Error Handling — bind=True, max_retries=3)
# =============================================================================

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,  # Tunggu 60 detik sebelum retry
)
def send_email_task(self, email: str, subject: str, body: str):
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@simple-lms.local'),
            recipient_list=[email],
            fail_silently=False,
        )
        return f"Email sent to {email}"
    except ConnectionError as exc:
        # Retry jika terjadi connection error
        print(f"[send_email_task] Retry {self.request.retries}/{self.max_retries}: {exc}")
        raise self.retry(exc=exc)
    except Exception as exc:
        # Log error lain tanpa retry
        print(f"[send_email_task] Failed permanently: {exc}")
        raise exc


# =============================================================================
# Task 10: Reliable Task with Exponential Backoff
# =============================================================================

@shared_task(bind=True, max_retries=5)
def reliable_task(self, data: dict):
    try:
        # Simulasi pemrosesan data
        print(f"[reliable_task] Processing data: {data}")
        result = {"processed": True, "data": data, "timestamp": str(datetime.now())}
        return result
    except Exception as exc:
        retry_delay = 2 ** self.request.retries
        print(f"[reliable_task] Retry {self.request.retries + 1}/{self.max_retries} in {retry_delay}s: {exc}")
        raise self.retry(exc=exc, countdown=retry_delay)


# =============================================================================
# Task Chaining: fetch → format → save (Chain & Group)
# =============================================================================

@shared_task
def fetch_course_data(course_id: int):
    from courses.models import Course, CourseMember

    course = Course.objects.get(pk=course_id)
    members = CourseMember.objects.filter(course_id=course).count()
    return {"course_id": course.id, "course_name": course.name, "members": members}


@shared_task
def format_report(data: dict):
    report = (
        f"=== COURSE REPORT ===\n"
        f"Course: {data.get('course_name', 'N/A')}\n"
        f"Members: {data.get('members', 0)}\n"
        f"Generated at: {datetime.now().isoformat()}"
    )
    return report


@shared_task
def save_report(report_text: str):
    report_dir = Path(settings.MEDIA_ROOT) / 'chain_reports'
    report_dir.mkdir(parents=True, exist_ok=True)
    filename = f"chain_report_{datetime.now().strftime('%Y%m%d%H%M%S')}.txt"
    path = report_dir / filename
    path.write_text(report_text, encoding='utf-8')

    print(f"[save_report] Report saved to {path}")
    return {"status": "saved", "file": str(path)}


def run_course_report_chain(course_id: int):
    return chain(
        fetch_course_data.s(course_id),
        format_report.s(),
        save_report.s(),
    )()


def run_bulk_reports(course_ids: list):
    return group(
        generate_course_report.s(course_id)
        for course_id in course_ids
    )()

# =============================================================================
# Task 11: Async File Processing (upload metadata / future conversion hook)
# =============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def process_uploaded_material(self, content_id: int):
    try:
        from courses.models import CourseContent
        from courses.mongo import log_activity

        content = CourseContent.objects.select_related("course_id", "course_id__teacher").get(id=content_id)
        if not content.file_attachment:
            return {"status": "skipped", "reason": "no_file", "content_id": content_id}

        file_path = Path(content.file_attachment.path)
        metadata = {
            "content_id": content.id,
            "course_id": content.course_id_id,
            "filename": file_path.name,
            "extension": file_path.suffix.lower(),
            "size_bytes": file_path.stat().st_size if file_path.exists() else None,
            "processed_at": datetime.now().isoformat(),
        }

        try:
            log_activity(content.course_id.teacher, "process_uploaded_material", metadata)
        except Exception:
            pass

        return {"status": "processed", "metadata": metadata}
    except Exception as exc:
        raise self.retry(exc=exc)
