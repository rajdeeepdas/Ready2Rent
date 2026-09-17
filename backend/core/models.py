"""
Abstract base models shared by every table.

docs/schema.md: "All PKs are UUIDs. All tables have created_at; mutable tables
also have updated_at."
"""

import uuid

from django.db import models


class UUIDModel(models.Model):
    """UUID primary key. Prevents ID enumeration on homeowner-facing URLs."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class CreatedModel(UUIDModel):
    """UUID PK + created_at. For append-only tables (no updated_at)."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        abstract = True


class TimeStampedModel(CreatedModel):
    """UUID PK + created_at + updated_at. For mutable tables."""

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
