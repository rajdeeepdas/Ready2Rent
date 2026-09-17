"""
Release tasks, run by the start command before gunicorn on hosts without a pre-deploy step
(Render Free). One process keeps cold starts short: migrations, then refresh-token cleanup.
Both are idempotent, so running them on every start is safe.

If the database is unreachable, print a diagnosis (never the password) instead of only a
stack trace, because the platform's deploy view may not show the traceback.
"""

import socket
import sys

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db.utils import OperationalError


class Command(BaseCommand):
    help = "Apply database migrations and delete expired refresh tokens."

    def handle(self, *args, **options):
        verbosity = options.get("verbosity", 1)
        self.stdout.write("release: applying migrations")
        self.stdout.flush()
        try:
            call_command("migrate", interactive=False, verbosity=verbosity)
        except OperationalError as exc:
            self.report_database_problem(exc)
            sys.exit(1)
        self.stdout.write("release: flushing expired refresh tokens")
        self.stdout.flush()
        call_command("flushexpiredtokens", verbosity=verbosity)
        self.stdout.write(self.style.SUCCESS("release: done"))
        self.stdout.flush()

    # -- diagnostics ---------------------------------------------------------
    def report_database_problem(self, exc: Exception) -> None:
        db = settings.DATABASES["default"]
        host, port, user = db.get("HOST") or "", db.get("PORT") or "5432", db.get("USER") or ""
        self.stderr.write("release: DATABASE CONNECTION FAILED")
        self.stderr.write(f"  error: {exc}")
        self.stderr.write(f"  host={host or '(empty)'} port={port} user={user or '(empty)'} name={db.get('NAME') or '(empty)'}")
        for line in self.describe_host(host):
            self.stderr.write(f"  {line}")
        for hint in self.hints(str(exc), host, user):
            self.stderr.write(f"  hint: {hint}")
        self.stderr.flush()

    @staticmethod
    def describe_host(host: str) -> list[str]:
        if not host:
            return ["DATABASE_URL has no host: check the value is set and well formed."]
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError as exc:
            return [f"DNS lookup for {host} failed: {exc}"]
        families = {socket.AddressFamily(i[0]).name for i in infos}
        addresses = sorted({i[4][0] for i in infos})
        return [f"{host} resolves to {', '.join(addresses)} ({', '.join(sorted(families))})"]

    @staticmethod
    def hints(message: str, host: str, user: str) -> list[str]:
        lowered = message.lower()
        hints: list[str] = []
        if "network is unreachable" in lowered or "cannot assign requested address" in lowered:
            hints.append(
                "The host is only reachable over IPv6, which this platform does not support. "
                "Use the Supabase SESSION POOLER URI (host contains 'pooler.supabase.com')."
            )
        if host and ".pooler.supabase.com" in host and "." not in user:
            hints.append(
                "The pooler needs the username 'postgres.<project-ref>', not plain 'postgres'."
            )
        if "tenant or user not found" in lowered:
            hints.append("Username must be 'postgres.<project-ref>' exactly as the Session pooler tab shows it.")
        if "password authentication failed" in lowered or "sasl" in lowered:
            hints.append("Wrong database password, or brackets were left around it in DATABASE_URL.")
        if "timeout" in lowered or "timed out" in lowered:
            hints.append("The database did not answer: a paused Supabase project is the usual cause. Restore it and redeploy.")
        if "does not exist" in lowered and "database" in lowered:
            hints.append("Database name should be 'postgres' for Supabase.")
        if not hints:
            hints.append("Check DATABASE_URL: user, password, host, port 5432, and ?sslmode=require.")
        return hints
