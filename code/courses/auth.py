import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
from django.conf import settings
from django.contrib.auth.models import User
from ninja.security import HttpBearer


def _get_jwt_algorithm() -> str:
    return getattr(settings, "JWT_ALGORITHM", "HS256")


def _get_access_expire_minutes() -> int:
    return getattr(settings, "JWT_ACCESS_TOKEN_EXPIRE_MINUTES", 30)


def _get_refresh_expire_days() -> int:
    return getattr(settings, "JWT_REFRESH_TOKEN_EXPIRE_DAYS", 7)


def _read_key(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def _get_signing_key() -> str:
    algorithm = _get_jwt_algorithm().upper()
    if algorithm.startswith("RS"):
        key = _read_key(getattr(settings, "JWT_PRIVATE_KEY_PATH", ""))
        if key:
            return key
    return settings.SECRET_KEY


def _get_verification_key() -> str:
    algorithm = _get_jwt_algorithm().upper()
    if algorithm.startswith("RS"):
        key = _read_key(getattr(settings, "JWT_PUBLIC_KEY_PATH", ""))
        if key:
            return key
    return settings.SECRET_KEY


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _blacklist_key(token: str) -> str:
    return f"jwt:blacklist:{_token_hash(token)}"


def blacklist_token(token: str) -> bool:
    try:
        from courses.cache import get_redis_client

        payload = jwt.decode(token, _get_verification_key(), algorithms=[_get_jwt_algorithm()])
        exp = payload.get("exp")
        now_ts = int(datetime.now(timezone.utc).timestamp())
        ttl = max(int(exp) - now_ts, 1) if exp else _get_refresh_expire_days() * 24 * 3600
        get_redis_client().setex(_blacklist_key(token), ttl, "1")
        return True
    except Exception:
        return False


def is_token_blacklisted(token: str) -> bool:
    try:
        from courses.cache import get_redis_client
        return bool(get_redis_client().exists(_blacklist_key(token)))
    except Exception:
        return False


def create_token(user: User, token_type: str = "access") -> str:
    now = datetime.now(timezone.utc)
    algorithm = _get_jwt_algorithm()

    if token_type == "access":
        expire = now + timedelta(minutes=_get_access_expire_minutes())
    else:
        expire = now + timedelta(days=_get_refresh_expire_days())

    payload = {
        "token_type": token_type,
        "user_id": user.id,
        "jti": str(uuid4()),
        "exp": expire,
        "iat": now,
    }

    return jwt.encode(payload, _get_signing_key(), algorithm=algorithm)


def decode_token(token: str) -> dict:
    if is_token_blacklisted(token):
        raise jwt.InvalidTokenError("Token sudah dicabut/logout")
    return jwt.decode(token, _get_verification_key(), algorithms=[_get_jwt_algorithm()])


class JWTAuth(HttpBearer):
    def authenticate(self, request, token):
        try:
            payload = decode_token(token)

            if payload.get("token_type") != "access":
                return None

            user = User.objects.filter(id=payload.get("user_id")).first()

            if user is None:
                return None

            request.auth_token = token
            request.user = user
            return user

        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None


api_auth = JWTAuth()
