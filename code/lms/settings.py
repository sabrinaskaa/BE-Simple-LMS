import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# SECRET_KEY wajib di-set via environment variable di production.
# Untuk development lokal, gunakan nilai default hanya jika belum di-set.
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-lab05-db-optimization-simple-lms-key-2025",
)

# Baca DEBUG dari environment. Default False untuk keamanan production.
DEBUG = os.environ.get("DEBUG", "False").lower() in ("true", "1", "yes")

# Jika DEBUG aktif, izinkan semua host (development). Di production, isi dengan domain nyata.
if DEBUG:
    ALLOWED_HOSTS = ["*"]
else:
    ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")


# =============================================================================
# Aplikasi yang terdaftar
# =============================================================================

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # "silk",       # Django Silk - query profiling (Modul 05)
    "courses",    # Aplikasi Simple LMS kita
    "analytics",  # Analytics MongoDB - activity & request logs (Modul 11)
]


# =============================================================================
# Middleware
# =============================================================================

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # "silk.middleware.SilkyMiddleware",  # Silk harus di posisi awal (setelah Security)
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "analytics.middleware.ActivityLoggingMiddleware",  # Auto-log setiap request ke MongoDB
]

ROOT_URLCONF = "lms.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "lms.wsgi.application"


# =============================================================================
# Database - PostgreSQL (sesuai docker-compose.yml)
# =============================================================================
# Berbeda dengan Lab-compliance yang menggunakan SQLite,
# lab ini menggunakan PostgreSQL agar optimasi index terlihat nyata.

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "lms_db"),
        "USER": os.environ.get("POSTGRES_USER", "postgres"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "postgres"),
        "HOST": os.environ.get("POSTGRES_HOST", "database"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}


# =============================================================================
# Django Silk - Konfigurasi Profiling
# Akses dashboard di: http://localhost:8000/silk/
# =============================================================================

# SILKY_PYTHON_PROFILER = True   # Aktifkan function-level profiling
# SILKY_META = True              # Track query Silk sendiri (untuk transparansi)


# =============================================================================
# Password validation
# =============================================================================

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# =============================================================================
# Internationalization
# =============================================================================

LANGUAGE_CODE = "id"
TIME_ZONE = "Asia/Jakarta"
USE_I18N = True
USE_TZ = True


# =============================================================================
# Static dan Media files
# =============================================================================

STATIC_URL = "static/"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# =============================================================================
# JWT Settings (dipakai oleh courses/auth.py)
# =============================================================================
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
JWT_REFRESH_TOKEN_EXPIRE_DAYS = int(os.environ.get("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "7"))


# =============================================================================
# Rate Limit Settings (dipakai oleh courses/rate_limit.py)
# =============================================================================
RATE_LIMIT_LOGIN_LIMIT = int(os.environ.get("RATE_LIMIT_LOGIN_LIMIT", "5"))
RATE_LIMIT_LOGIN_WINDOW = int(os.environ.get("RATE_LIMIT_LOGIN_WINDOW", "60"))   # detik
RATE_LIMIT_ANON_LIMIT = int(os.environ.get("RATE_LIMIT_ANON_LIMIT", "60"))
RATE_LIMIT_AUTH_LIMIT = int(os.environ.get("RATE_LIMIT_AUTH_LIMIT", "120"))
RATE_LIMIT_WINDOW = int(os.environ.get("RATE_LIMIT_WINDOW", "60"))               # detik


# =============================================================================
# File Upload Settings
# =============================================================================
FILE_UPLOAD_MAX_MEMORY_SIZE = int(os.environ.get("FILE_UPLOAD_MAX_MEMORY_SIZE", str(10 * 1024 * 1024)))  # 10 MB
DATA_UPLOAD_MAX_MEMORY_SIZE = FILE_UPLOAD_MAX_MEMORY_SIZE
ALLOWED_UPLOAD_EXTENSIONS = [".pdf", ".doc", ".docx", ".ppt", ".pptx", ".mp4", ".png", ".jpg", ".jpeg"]
MAX_UPLOAD_SIZE_BYTES = int(os.environ.get("MAX_UPLOAD_SIZE_BYTES", str(10 * 1024 * 1024)))  # 10 MB


# =============================================================================
# Security headers (aktif di production / non-DEBUG)
# =============================================================================
if not DEBUG:
    SECURE_HSTS_SECONDS = 31536000          # 1 tahun
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"


# =============================================================================
# Redis, MongoDB, Celery, Email
# =============================================================================
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
MONGODB_URI = os.environ.get("MONGODB_URI", "mongodb://mongodb:27017/")
MONGODB_NAME = os.environ.get("MONGODB_NAME", "lms_logs")              # database untuk system/error logs
MONGODB_ANALYTICS_DB = os.environ.get("MONGODB_ANALYTICS_DB", "lms_analytics")  # database untuk analytics

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
    }
}

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "amqp://admin:password123@rabbitmq:5672//")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379/2")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = "noreply@simple-lms.local"


# =============================================================================
# Celery Beat Schedule — Periodic Tasks
# =============================================================================
from celery.schedules import crontab  # noqa: E402

CELERY_BEAT_SCHEDULE = {
    # Statistik harian LMS dijalankan setiap hari pukul 00:00 WIB
    'daily-course-stats': {
        'task': 'courses.tasks.generate_daily_stats',
        'schedule': crontab(hour=0, minute=0),
        'args': (),
    },
    # Hapus log lama (>30 hari) setiap hari pukul 02:00 WIB
    'cleanup-old-logs': {
        'task': 'courses.tasks.cleanup_old_logs',
        'schedule': crontab(hour=2, minute=0),
        'args': (),
    },
    # Update statistik course setiap jam (task existing)
    'update-course-statistics-every-hour': {
        'task': 'courses.tasks.update_course_statistics',
        'schedule': crontab(minute=0),
        'args': (),
    },
}
