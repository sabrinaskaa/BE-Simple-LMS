from functools import wraps

from ninja.errors import HttpError


def user_roles(user):
    roles = list(user.groups.values_list("name", flat=True))

    if user.is_superuser:
        roles.append("Admin")

    return roles


def is_admin(user):
    return user.is_superuser or user.groups.filter(name="Admin").exists()


def is_instructor(user):
    return (
        user.is_superuser
        or user.groups.filter(name="Admin").exists()
        or user.groups.filter(name="Instructor").exists()
    )


def is_student(user):
    return (
        user.groups.filter(name="Student").exists()
        or user.groups.filter(name="Instructor").exists()
        or user.groups.filter(name="Admin").exists()
        or user.is_superuser
    )


def require_admin(func):
    @wraps(func)
    def wrapper(request, *args, **kwargs):
        if not is_admin(request.user):
            raise HttpError(403, "Hanya admin yang boleh mengakses endpoint ini")
        return func(request, *args, **kwargs)
    return wrapper


def require_instructor(func):
    @wraps(func)
    def wrapper(request, *args, **kwargs):
        if not is_instructor(request.user):
            raise HttpError(403, "Hanya instructor yang boleh mengakses endpoint ini")
        return func(request, *args, **kwargs)
    return wrapper


def require_student(func):
    @wraps(func)
    def wrapper(request, *args, **kwargs):
        if not is_student(request.user):
            raise HttpError(403, "Hanya student yang boleh mengakses endpoint ini")
        return func(request, *args, **kwargs)
    return wrapper