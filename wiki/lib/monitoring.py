from http import HTTPStatus
from typing import NoReturn

from django.db import OperationalError, connections
from django.http import HttpRequest, HttpResponse, JsonResponse


def check_postgresql() -> bool:
    """Check if we can connect to PostgreSQL."""
    try:
        for alias in connections:
            with connections[alias].cursor() as c:
                c.execute("SELECT 1")
                c.fetchone()
    except OperationalError:
        return False
    return True


def heartbeat(request: HttpRequest) -> HttpResponse:
    return HttpResponse("OK", content_type="text/plain")


def health_check(request: HttpRequest) -> JsonResponse:
    """Check if we can connect to various services."""
    is_postgresql_up = check_postgresql()

    status = HTTPStatus.OK
    if not is_postgresql_up:
        status = HTTPStatus.INTERNAL_SERVER_ERROR

    return JsonResponse(
        {"is_postgresql_up": is_postgresql_up},
        status=status,
    )


def sentry_fail(request: HttpRequest) -> NoReturn:
    raise ZeroDivisionError("Intentional error for Sentry")
