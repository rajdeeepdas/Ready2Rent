"""
Application status state machine (docs/schema.md "Status state machine").

Pure data + a validation function. The transactional transition service that
locks the row and writes history arrives in Milestone 4; this module is the
single source of truth it will consult.
"""

from .enums import ApplicationStatus as S

# from_status -> set of allowed to_status
TRANSITIONS: dict[str, frozenset[str]] = {
    S.INTAKE: frozenset({S.ELIGIBILITY_CHECK, S.WITHDRAWN}),
    S.ELIGIBILITY_CHECK: frozenset({S.DEVELOPMENT_PERMIT, S.PERMITS, S.ON_HOLD, S.WITHDRAWN}),
    S.DEVELOPMENT_PERMIT: frozenset({S.PERMITS, S.ON_HOLD, S.WITHDRAWN}),
    S.PERMITS: frozenset({S.CONSTRUCTION, S.ON_HOLD, S.WITHDRAWN}),
    S.CONSTRUCTION: frozenset({S.INSPECTIONS, S.ON_HOLD, S.WITHDRAWN}),
    S.INSPECTIONS: frozenset({S.REGISTERED, S.CONSTRUCTION, S.ON_HOLD, S.WITHDRAWN}),
    S.REGISTERED: frozenset({S.COMPLETE}),
    # on_hold may return to the status it came from (checked against history) or be withdrawn.
    S.ON_HOLD: frozenset({S.WITHDRAWN}),
    S.COMPLETE: frozenset(),
    S.WITHDRAWN: frozenset(),
}

# Statuses an application may be placed on hold from (and therefore resume to).
RESUMABLE_STATUSES: frozenset[str] = frozenset(
    {
        S.ELIGIBILITY_CHECK,
        S.DEVELOPMENT_PERMIT,
        S.PERMITS,
        S.CONSTRUCTION,
        S.INSPECTIONS,
    }
)

TERMINAL_STATUSES: frozenset[str] = frozenset({S.COMPLETE, S.WITHDRAWN})


class InvalidTransition(Exception):
    def __init__(self, from_status: str, to_status: str, reason: str = ""):
        self.from_status = from_status
        self.to_status = to_status
        msg = f"Cannot move application from '{from_status}' to '{to_status}'."
        if reason:
            msg += f" {reason}"
        super().__init__(msg)


def validate_transition(from_status: str, to_status: str, *, prior_status: str | None = None) -> None:
    """
    Raise InvalidTransition unless from_status -> to_status is allowed.

    `prior_status` is the status the application held before going on hold. It is
    required to validate on_hold -> (resume). Callers obtain it from the latest
    history row whose to_status == on_hold.
    """
    if from_status == to_status:
        raise InvalidTransition(from_status, to_status, "Already in that status.")

    if from_status == S.ON_HOLD and to_status != S.WITHDRAWN:
        if prior_status is None:
            raise InvalidTransition(from_status, to_status, "No prior status recorded to resume to.")
        if to_status != prior_status:
            raise InvalidTransition(
                from_status, to_status, f"An on-hold application may only resume to '{prior_status}'."
            )
        return

    allowed = TRANSITIONS.get(from_status, frozenset())
    if to_status not in allowed:
        raise InvalidTransition(from_status, to_status)
