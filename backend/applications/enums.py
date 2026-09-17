"""Enumerations from docs/schema.md, as Django TextChoices. UserRole lives in accounts."""

from django.db import models


class SuiteType(models.TextChoices):
    NEW = "new", "New secondary suite"
    LEGALIZE_EXISTING = "legalize_existing", "Legalize existing suite"


class ApplicationStatus(models.TextChoices):
    INTAKE = "intake", "Intake"
    ELIGIBILITY_CHECK = "eligibility_check", "Eligibility check"
    DEVELOPMENT_PERMIT = "development_permit", "Development permit"
    PERMITS = "permits", "Building & trade permits"
    CONSTRUCTION = "construction", "Construction"
    INSPECTIONS = "inspections", "Inspections"
    REGISTERED = "registered", "Registered"
    COMPLETE = "complete", "Complete"
    ON_HOLD = "on_hold", "On hold"
    WITHDRAWN = "withdrawn", "Withdrawn"


class ComplianceItemType(models.TextChoices):
    EGRESS_WINDOW = "egress_window", "Egress window(s) in each bedroom"
    CEILING_HEIGHT = "ceiling_height", "Minimum ceiling height"
    FIRE_SEPARATION = "fire_separation", "Fire separation from main dwelling"
    SMOKE_CO_ALARMS = "smoke_co_alarms", "Interconnected smoke + CO alarms"
    SEPARATE_ENTRANCE = "separate_entrance", "Separate / dedicated entrance"
    MECHANICAL_SEPARATION = "mechanical_separation", "Mechanical / furnace room separation"
    PARKING = "parking", "On-property parking"
    AMENITY_SPACE = "amenity_space", "Outdoor amenity space"
    OTHER = "other", "Other"


class ComplianceStatus(models.TextChoices):
    NOT_ASSESSED = "not_assessed", "Not assessed"
    NEEDS_WORK = "needs_work", "Needs work"
    COMPLIANT = "compliant", "Compliant"
    NA = "na", "Not applicable"


class PermitType(models.TextChoices):
    DEVELOPMENT = "development", "Development permit"
    BUILDING = "building", "Building permit"
    ELECTRICAL = "electrical", "Electrical permit"
    PLUMBING = "plumbing", "Plumbing permit"
    GAS = "gas", "Gas permit"
    MECHANICAL = "mechanical", "Mechanical / HVAC permit"


class PermitStatus(models.TextChoices):
    NOT_REQUIRED = "not_required", "Not required"
    NOT_STARTED = "not_started", "Not started"
    APPLIED = "applied", "Applied"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    EXPIRED = "expired", "Expired"


class DocumentType(models.TextChoices):
    APPLICATION_FORM = "application_form", "Completed application form"
    SITE_PLAN = "site_plan", "Site plan"
    FLOOR_PLANS = "floor_plans", "Floor plans"
    ELEVATIONS = "elevations", "Elevations"
    ABANDONED_WELL_DECLARATION = "abandoned_well_declaration", "Abandoned Well Declaration"
    SITE_CONTAMINATION_STATEMENT = "site_contamination_statement", "Site Contamination Statement"
    PUBLIC_TREE_DISCLOSURE = "public_tree_disclosure", "Public Tree Disclosure Statement"
    ASBESTOS_ABATEMENT = "asbestos_abatement", "Asbestos abatement form (pre-1990 homes)"
    COLOUR_PHOTOS = "colour_photos", "Colour photos (existing suite)"
    LAND_TITLE = "land_title", "Proof of ownership (land title)"
    OTHER = "other", "Other"


class DocumentStatus(models.TextChoices):
    REQUIRED = "required", "Required"
    UPLOADED = "uploaded", "Uploaded"
    ACCEPTED = "accepted", "Accepted"
    REJECTED = "rejected", "Rejected"


class VisitType(models.TextChoices):
    SITE_ASSESSMENT = "site_assessment", "Site assessment"
    INSPECTION = "inspection", "City inspection"


class VisitStatus(models.TextChoices):
    SCHEDULED = "scheduled", "Scheduled"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"
    NO_SHOW = "no_show", "No-show"
