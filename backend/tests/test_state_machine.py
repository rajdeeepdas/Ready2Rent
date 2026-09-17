"""The transition map from docs/schema.md, exhaustively."""

import itertools

import pytest

from applications.enums import ApplicationStatus as S
from applications.state_machine import TRANSITIONS, InvalidTransition, validate_transition

ALLOWED = {
    (S.INTAKE, S.ELIGIBILITY_CHECK),
    (S.INTAKE, S.WITHDRAWN),
    (S.ELIGIBILITY_CHECK, S.DEVELOPMENT_PERMIT),
    (S.ELIGIBILITY_CHECK, S.PERMITS),
    (S.ELIGIBILITY_CHECK, S.ON_HOLD),
    (S.ELIGIBILITY_CHECK, S.WITHDRAWN),
    (S.DEVELOPMENT_PERMIT, S.PERMITS),
    (S.DEVELOPMENT_PERMIT, S.ON_HOLD),
    (S.DEVELOPMENT_PERMIT, S.WITHDRAWN),
    (S.PERMITS, S.CONSTRUCTION),
    (S.PERMITS, S.ON_HOLD),
    (S.PERMITS, S.WITHDRAWN),
    (S.CONSTRUCTION, S.INSPECTIONS),
    (S.CONSTRUCTION, S.ON_HOLD),
    (S.CONSTRUCTION, S.WITHDRAWN),
    (S.INSPECTIONS, S.REGISTERED),
    (S.INSPECTIONS, S.CONSTRUCTION),
    (S.INSPECTIONS, S.ON_HOLD),
    (S.INSPECTIONS, S.WITHDRAWN),
    (S.REGISTERED, S.COMPLETE),
    (S.ON_HOLD, S.WITHDRAWN),
}

ALL_PAIRS = [(a, b) for a, b in itertools.product(S.values, S.values)]


def test_transition_table_matches_spec():
    flattened = {(f, t) for f, targets in TRANSITIONS.items() for t in targets}
    assert flattened == ALLOWED


@pytest.mark.parametrize("frm,to", ALL_PAIRS, ids=[f"{a}->{b}" for a, b in ALL_PAIRS])
def test_every_pair(frm, to):
    """Allowed pairs pass; everything else (incl. self-transitions) raises.
    on_hold -> X (X != withdrawn) raises here because no prior_status is given;
    the resume path with a prior status is covered by TestResume."""
    if (frm, to) in ALLOWED:
        validate_transition(frm, to)
    else:
        with pytest.raises(InvalidTransition):
            validate_transition(frm, to)


class TestResume:
    def test_resume_to_prior_status(self):
        validate_transition(S.ON_HOLD, S.PERMITS, prior_status=S.PERMITS)

    def test_resume_to_other_status_rejected(self):
        with pytest.raises(InvalidTransition):
            validate_transition(S.ON_HOLD, S.CONSTRUCTION, prior_status=S.PERMITS)

    def test_resume_without_prior_rejected(self):
        with pytest.raises(InvalidTransition):
            validate_transition(S.ON_HOLD, S.PERMITS)

    def test_withdraw_from_hold_needs_no_prior(self):
        validate_transition(S.ON_HOLD, S.WITHDRAWN)


def test_terminal_states_have_no_exits():
    assert TRANSITIONS[S.COMPLETE] == frozenset()
    assert TRANSITIONS[S.WITHDRAWN] == frozenset()
