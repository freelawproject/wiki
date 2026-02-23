from django.http import HttpResponse
from django.template.loader import render_to_string


def ratelimited(request, exception=None):
    """Return a 429 Too Many Requests response."""
    html = render_to_string("429.html", request=request)
    return HttpResponse(html, status=429)
