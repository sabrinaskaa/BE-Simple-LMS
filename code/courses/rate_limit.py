from functools import wraps

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


def rate_limit(limit: int = 60, window: int = 60, prefix: str = 'api'):
    """Redis fixed-window rate limiter. Default: 60 request/menit."""
    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            client = get_redis_client()
            identifier = _client_identifier(request)
            path = request.path.replace('/', ':')
            key = f"rate:{prefix}:{identifier}:{path}"

            current = client.incr(key)
            if current == 1:
                client.expire(key, window)

            ttl = client.ttl(key)
            if current > limit:
                raise HttpError(429, f"Terlalu banyak request. Coba lagi dalam {ttl} detik.")

            return func(request, *args, **kwargs)
        return wrapper
    return decorator
