"""
Celery application. Broker and result backend are Redis (same instance as the cache,
different logical DB by default). Tasks are auto-discovered from each app's tasks.py.

Local run (Windows needs the solo pool; Linux hosts use the default prefork):
    celery -A config worker -l info --pool=solo
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("ready2rent")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
