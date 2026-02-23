#!/bin/sh
set -e

case "$1" in
'web-dev')
    python manage.py migrate
    python manage.py createcachetable
    python manage.py seed_help_pages
    echo ""
    echo "  Wiki running at: ${BASE_URL:-http://localhost:8001}"
    echo ""
    exec python manage.py runserver 0.0.0.0:8000
    ;;
'web-prod')
    exec gunicorn wiki.asgi:application \
        --chdir /opt/wiki/ \
        --user www-data \
        --group www-data \
        --workers ${NUM_WORKERS:-4} \
        --worker-class wiki.workers.UvicornWorker \
        --timeout 180 \
        --max-requests ${MAX_REQUESTS:-2500} \
        --max-requests-jitter 100 \
        --bind 0.0.0.0:8000
    ;;
*)
    # Pass through to manage.py for cron jobs, e.g.:
    #   docker exec wiki-django python manage.py sync_view_counts
    exec python manage.py "$@"
    ;;
esac
