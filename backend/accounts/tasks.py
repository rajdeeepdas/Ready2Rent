from celery import shared_task
from django.core.management import call_command


@shared_task(name="accounts.flush_expired_tokens")
def flush_expired_tokens() -> None:
    """Delete expired refresh-token records (simplejwt outstanding + blacklist tables).
    Scheduled daily by Celery beat; also run on every deploy by the pre-deploy command."""
    call_command("flushexpiredtokens")
