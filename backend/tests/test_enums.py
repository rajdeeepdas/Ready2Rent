"""
Every enum in docs/schema.md, with exactly the specified values, in order.
The expected lists below are copied verbatim from the spec so any drift fails here.
"""

import pytest

from accounts.models import UserRole
from applications import enums

SPEC = {
    UserRole: ["homeowner", "staff", "admin"],
    enums.SuiteType: ["new", "legalize_existing"],
    enums.ApplicationStatus: [
        "intake", "eligibility_check", "development_permit", "permits", "construction",
        "inspections", "registered", "complete", "on_hold", "withdrawn",
    ],
    enums.ComplianceItemType: [
        "egress_window", "ceiling_height", "fire_separation", "smoke_co_alarms",
        "separate_entrance", "mechanical_separation", "parking", "amenity_space", "other",
    ],
    enums.ComplianceStatus: ["not_assessed", "needs_work", "compliant", "na"],
    enums.PermitType: ["development", "building", "electrical", "plumbing", "gas", "mechanical"],
    enums.PermitStatus: ["not_required", "not_started", "applied", "approved", "rejected", "expired"],
    enums.DocumentType: [
        "application_form", "site_plan", "floor_plans", "elevations", "abandoned_well_declaration",
        "site_contamination_statement", "public_tree_disclosure", "asbestos_abatement",
        "colour_photos", "land_title", "other",
    ],
    enums.DocumentStatus: ["required", "uploaded", "accepted", "rejected"],
    enums.VisitType: ["site_assessment", "inspection"],
    enums.VisitStatus: ["scheduled", "completed", "cancelled", "no_show"],
}


def test_schema_defines_eleven_enums():
    assert len(SPEC) == 11


@pytest.mark.parametrize("enum_cls", list(SPEC), ids=lambda e: e.__name__)
def test_enum_values_match_spec_exactly(enum_cls):
    assert list(enum_cls.values) == SPEC[enum_cls]
