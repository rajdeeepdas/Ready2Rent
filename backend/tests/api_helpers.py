from rest_framework.test import APIClient


def client_for(user) -> APIClient:
    """An APIClient acting as `user`. JWT mechanics are covered in test_auth.py; here we
    only need the request to be authenticated as that user."""
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def intake_payload(**overrides) -> dict:
    payload = {
        "property": {
            "street_address": "1234 17 Ave SW",
            "postal_code": "T2T 0C3",
            "year_built": 1975,
        },
        "suite": {
            "suite_type": "legalize_existing",
            "has_separate_entrance": True,
            "description": "Existing 2-bedroom basement suite, built by previous owner.",
        },
        "compliance": {
            "egress_window": "needs_work",
            "ceiling_height": "compliant",
            "smoke_co_alarms": "not_assessed",
        },
        "other_issues": "Furnace room door does not close properly.",
        "goals": {
            "pursuing_incentive": True,
            "wants_financing_guidance": True,
            "notes": "Want to rent to a student by next fall.",
        },
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(payload.get(key), dict):
            payload[key] = {**payload[key], **value}
        else:
            payload[key] = value
    return payload
