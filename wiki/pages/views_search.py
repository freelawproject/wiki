from django.shortcuts import render

from .search import search_pages


def search_view(request):
    """Full-text search across wiki pages."""
    query = request.GET.get("q", "").strip()
    results = []
    if query:
        results = search_pages(query, user=request.user)

    return render(
        request,
        "pages/search.html",
        {"query": query, "results": results},
    )
