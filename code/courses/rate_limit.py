from functools import wraps

from django.conf import settings
from ninja.errors import HttpError

from .cache import get_redis_client


def _client_identifier(request) -> str:
    user = getattr(request, 'user', None)
    if user is not None and getattr(user, 'is_authenticated', False):
        return f"user:{user.id}"
    forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded_for:
        ip_address = forwarded_for.split(',')[0].strip()
    else:
        ip_address = request.META.get('REMOTE_ADDR', 'unknown')
    return f"ip:{ip_address}"


def rate_limit(limit: int | None = None, window: int | None = None, prefix: str = 'api'):
    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            client = get_redis_client()
            identifier = _client_identifier(request)

            # Pilih limit sesuai status autentikasi kecuali override eksplisit diberikan.
            user = getattr(request, 'user', None)
            is_auth = user is not None and getattr(user, 'is_authenticated', False)

            effective_limit = limit
            effective_window = window

            if effective_limit is None:
                if is_auth:
                    effective_limit = getattr(settings, 'RATE_LIMIT_AUTH_LIMIT', 120)
                else:
                    effective_limit = getattr(settings, 'RATE_LIMIT_ANON_LIMIT', 60)

            if effective_window is None:
                effective_window = getattr(settings, 'RATE_LIMIT_WINDOW', 60)

            path = request.path.replace('/', ':')
            key = f"rate:{prefix}:{identifier}:{path}"

            current = client.incr(key)
            if current == 1:
                client.expire(key, effective_window)

            ttl = client.ttl(key)
            if ttl is None or ttl < 0:
                ttl = effective_window

            remaining = max(effective_limit - current, 0)
            request._rate_limit_info = {
                "limit": effective_limit,
                "remaining": remaining,
                "reset": ttl,
                "retry_after": ttl if current > effective_limit else None,
            }

            if current > effective_limit:
                raise HttpError(
                    429,
                    f"Terlalu banyak request. Coba lagi dalam {ttl} detik."
                )

            return func(request, *args, **kwargs)
        return wrapper
    return decorator


def rate_limit_login():
    limit = getattr(settings, 'RATE_LIMIT_LOGIN_LIMIT', 5)
    window = getattr(settings, 'RATE_LIMIT_LOGIN_WINDOW', 60)
    return rate_limit(limit=limit, window=window, prefix='login')

