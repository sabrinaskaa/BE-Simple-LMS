from .settings import *  # noqa: F401, F403

# Override database ke SQLite untuk testing lokal (tanpa Docker/PostgreSQL)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db_test.sqlite3",
    }
}
