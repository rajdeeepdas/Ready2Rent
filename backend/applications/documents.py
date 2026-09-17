"""
Document rules from docs/domain-research.md §4 and docs/schema.md "Document".

  - Common set for every application.
  - Elevations: "mainly new builds / exterior changes" -> required for suite_type=new.
  - Colour photos: required when legalizing an existing suite.
  - Asbestos abatement form: required when the home predates 1990.

Upload validation is deliberately conservative: extension allow-list, size cap, and a
magic-byte check so a renamed executable cannot be stored as a "PDF".
"""

from django.conf import settings
from rest_framework.exceptions import ValidationError

from .enums import DocumentType as D
from .enums import SuiteType

COMMON_REQUIRED = [
    D.APPLICATION_FORM,
    D.SITE_PLAN,
    D.FLOOR_PLANS,
    D.ABANDONED_WELL_DECLARATION,
    D.SITE_CONTAMINATION_STATEMENT,
    D.PUBLIC_TREE_DISCLOSURE,
    D.LAND_TITLE,
]

ASBESTOS_YEAR_THRESHOLD = 1990


def required_document_types(suite_type: str, year_built: int | None) -> list[str]:
    types = list(COMMON_REQUIRED)
    if suite_type == SuiteType.NEW:
        types.insert(3, D.ELEVATIONS)  # keep plan-set documents together
    if suite_type == SuiteType.LEGALIZE_EXISTING:
        types.append(D.COLOUR_PHOTOS)
    if year_built is not None and year_built < ASBESTOS_YEAR_THRESHOLD:
        types.append(D.ASBESTOS_ABATEMENT)
    return types


# extension -> accepted leading bytes (any match)
ALLOWED_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    ".pdf": (b"%PDF",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
}
ALLOWED_EXTENSIONS = sorted(ALLOWED_SIGNATURES)


def validate_upload(uploaded_file) -> None:
    """Raise DRF ValidationError unless the file is an allowed type within the size cap."""
    name = (uploaded_file.name or "").lower()
    ext = name[name.rfind(".") :] if "." in name else ""
    if ext not in ALLOWED_SIGNATURES:
        raise ValidationError(
            {"file": f"Unsupported file type '{ext or 'none'}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}."}
        )

    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    if uploaded_file.size > max_bytes:
        raise ValidationError({"file": f"File is larger than {settings.MAX_UPLOAD_MB} MB."})
    if uploaded_file.size == 0:
        raise ValidationError({"file": "File is empty."})

    head = uploaded_file.read(16)
    uploaded_file.seek(0)
    if not any(head.startswith(sig) for sig in ALLOWED_SIGNATURES[ext]):
        raise ValidationError({"file": f"File content does not look like a {ext[1:].upper()} file."})
