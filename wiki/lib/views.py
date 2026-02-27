from django.conf import settings
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.urls import reverse


def ratelimited(request, exception=None):
    """Return a 429 Too Many Requests response."""
    html = render_to_string("429.html", request=request)
    return HttpResponse(html, status=429)


def robots_txt(request):
    """Serve robots.txt with crawl directives."""
    sitemap_url = f"{settings.BASE_URL}{reverse('django.contrib.sitemaps.views.sitemap')}"
    lines = [
        "User-agent: *",
        "Allow: /c/",
        "Disallow: /admin/",
        "Disallow: /api/",
        "Disallow: /u/",
        "Disallow: /search/",
        "Disallow: /files/",
        "Disallow: /unsubscribe/",
        "",
        f"Sitemap: {sitemap_url}",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")
