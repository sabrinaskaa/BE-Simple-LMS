import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lms.settings')

app = Celery('lms')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

app.conf.beat_schedule = {
    'update-course-statistics-every-hour': {
        'task': 'courses.tasks.update_course_statistics',
        'schedule': crontab(minute=0),
    },
}
