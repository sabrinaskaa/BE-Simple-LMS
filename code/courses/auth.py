from datetime import datetime, timedelta, timezone

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


def create_token(user: User, token_type: str = "access") -> str:
    now = datetime.now(timezone.utc)
    algorithm = _get_jwt_algorithm()

    if token_type == "access":
        expire = now + timedelta(minutes=_get_access_expire_minutes())
    else:
        expire = now + timedelta(days=_get_refresh_expire_days())

    # Hanya simpan user_id di payload — tidak ada data PII seperti username/email.
    payload = {
        "token_type": token_type,
        "user_id": user.id,
        "exp": expire,
        "iat": now,
    }

    return jwt.encode(payload, settings.SECRET_KEY, algorithm=algorithm)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[_get_jwt_algorithm()])


class JWTAuth(HttpBearer):
    def authenticate(self, request, token):
        try:
            payload = decode_token(token)

            if payload.get("token_type") != "access":
                return None

            user = User.objects.filter(id=payload.get("user_id")).first()

            if user is None:
                return None

            request.user = user
            return user

        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None


api_auth = JWTAuth()