import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class AnalyticsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "analytics"
    verbose_name = "Analytics (MongoDB)"

    def ready(self) -> None:
        try:
            from .mongo_service import ensure_indexes
            ensure_indexes()
        except Exception as e:
            logger.warning(
                f"[AnalyticsConfig] Gagal membuat MongoDB indexes saat startup: {e}. "
                "Server tetap berjalan, index akan dibuat saat koneksi tersedia."
            )
