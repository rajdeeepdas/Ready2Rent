"""
Cache invalidation hooks. Any save or delete on a row that feeds the ops queue
(application, documents, compliance items, permits, visits, history) invalidates it.
Signals are used here (and only here) because the goal is "never miss a write",
including writes made through Django admin.
"""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .cache import invalidate_queue
from .models import Application, ApplicationStatusHistory, ComplianceItem, Document, Permit, Visit

_MODELS = (Application, ApplicationStatusHistory, ComplianceItem, Document, Permit, Visit)


@receiver(post_save, sender=Application)
@receiver(post_save, sender=ApplicationStatusHistory)
@receiver(post_save, sender=ComplianceItem)
@receiver(post_save, sender=Document)
@receiver(post_save, sender=Permit)
@receiver(post_save, sender=Visit)
@receiver(post_delete, sender=Application)
@receiver(post_delete, sender=ApplicationStatusHistory)
@receiver(post_delete, sender=ComplianceItem)
@receiver(post_delete, sender=Document)
@receiver(post_delete, sender=Permit)
@receiver(post_delete, sender=Visit)
def _invalidate_ops_queue(sender, **kwargs):
    invalidate_queue()
