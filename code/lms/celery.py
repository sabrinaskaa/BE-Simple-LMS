# lms/celery.py
import os

from celery import Celery

# Set default Django settings module so Celery can access Django config
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lms.settings')

# Create Celery app instance with project name
app = Celery('lms')

# Read all Celery config from Django settings (keys prefixed with CELERY_)
# This includes CELERY_BROKER_URL, CELERY_RESULT_BACKEND, CELERY_BEAT_SCHEDULE, etc.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks from all apps registered in INSTALLED_APPS
# Each app should have a tasks.py file
app.autodiscover_tasks()
