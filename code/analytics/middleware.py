import logging
import threading
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Path yang di-skip agar tidak membanjiri log dengan noise
_SKIP_PREFIXES = (
    "/static/",
    "/media/",
    "/favicon",
    "/admin/jsi18n/",
)


class ActivityLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Proses request → dapatkan response terlebih dahulu
        response = self.get_response(request)

        # Skip path yang tidak perlu di-log
        if any(request.path.startswith(prefix) for prefix in _SKIP_PREFIXES):
            return response

        # Spawn background thread — fire and forget
        thread = threading.Thread(
            target=self._log_request,
            args=(request, response),
            daemon=True,  # thread mati saat proses utama mati
        )
        thread.start()

        return response

    def _log_request(self, request, response) -> None:
        try:
            from .mongo_service import get_analytics_db

            user = getattr(request, "user", None)
            is_auth = user is not None and hasattr(user, "is_authenticated") and user.is_authenticated
            user_id = user.id if is_auth else None

            document = {
                "user_id": user_id,
                "method": request.method,
                "path": request.path,
                "status_code": response.status_code,
                "timestamp": datetime.now(timezone.utc),
                "metadata": {
                    "ip": self._get_client_ip(request),
                    "user_agent": request.META.get("HTTP_USER_AGENT", "")[:200],
                },
            }

            get_analytics_db().request_logs.insert_one(document)

        except Exception as e:
            # PENTING: jangan pernah raise di sini — middleware tidak boleh crash
            logger.warning(f"[ActivityLoggingMiddleware] Gagal log request ke MongoDB: {e}")

    @staticmethod
    def _get_client_ip(request) -> str:
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "unknown")
