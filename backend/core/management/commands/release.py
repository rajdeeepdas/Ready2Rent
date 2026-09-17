"""
Release tasks, run by the start command before gunicorn on hosts without a pre-deploy step
(Render Free). One process keeps cold starts short: migrations, then refresh-token cleanup.
Both are idempotent, so running them on every start is safe.
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Apply database migrations and delete expired refresh tokens."

    def handle(self, *args, **options):
        verbosity = options.get("verbosity", 1)
        self.stdout.write("release: applying migrations")
        call_command("migrate", interactive=False, verbosity=verbosity)
        self.stdout.write("release: flushing expired refresh tokens")
        call_command("flushexpiredtokens", verbosity=verbosity)
        self.stdout.write(self.style.SUCCESS("release: done"))
