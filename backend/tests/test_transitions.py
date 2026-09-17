"""
Transaction boundary 2: transition_application() locks the row, validates against the
state machine, updates status, and appends history atomically.
"""

import threading

import pytest
from django.db import connection

from applications.enums import ApplicationStatus as S
from applications.models import Application, ApplicationStatusHistory
from applications.services import transition_application
from applications.state_machine import InvalidTransition
from tests.factories import ApplicationFactory, StatusHistoryFactory


@pytest.mark.django_db
class TestTransitionService:
    def test_valid_transition_updates_and_logs(self, staff):
        app = ApplicationFactory(status=S.INTAKE)
        result = transition_application(application_id=app.id, to_status=S.ELIGIBILITY_CHECK, by_user=staff, note="ok")
        assert result.status == S.ELIGIBILITY_CHECK
        row = app.status_history.get()
        assert (row.from_status, row.to_status, row.changed_by, row.note) == (S.INTAKE, S.ELIGIBILITY_CHECK, staff, "ok")

    def test_invalid_transition_changes_nothing(self, staff):
        app = ApplicationFactory(status=S.INTAKE)
        with pytest.raises(InvalidTransition):
            transition_application(application_id=app.id, to_status=S.CONSTRUCTION, by_user=staff)
        app.refresh_from_db()
        assert app.status == S.INTAKE and app.status_history.count() == 0

    def test_on_hold_resumes_only_to_prior_status(self, staff):
        app = ApplicationFactory(status=S.PERMITS)
        transition_application(application_id=app.id, to_status=S.ON_HOLD, by_user=staff)
        with pytest.raises(InvalidTransition):
            transition_application(application_id=app.id, to_status=S.CONSTRUCTION, by_user=staff)
        result = transition_application(application_id=app.id, to_status=S.PERMITS, by_user=staff)
        assert result.status == S.PERMITS
        assert [h.to_status for h in app.status_history.all()] == [S.ON_HOLD, S.PERMITS]

    def test_on_hold_without_history_cannot_resume(self, staff):
        app = ApplicationFactory(status=S.ON_HOLD)  # no history row explaining the hold
        with pytest.raises(InvalidTransition):
            transition_application(application_id=app.id, to_status=S.PERMITS, by_user=staff)
        transition_application(application_id=app.id, to_status=S.WITHDRAWN, by_user=staff)  # always allowed

    def test_history_failure_rolls_back_status(self, staff, monkeypatch):
        app = ApplicationFactory(status=S.INTAKE)

        def boom(*a, **k):
            raise RuntimeError("history insert failed")

        monkeypatch.setattr(ApplicationStatusHistory.objects, "create", boom)
        with pytest.raises(RuntimeError):
            transition_application(application_id=app.id, to_status=S.ELIGIBILITY_CHECK, by_user=staff)
        app.refresh_from_db()
        assert app.status == S.INTAKE


@pytest.mark.django_db(transaction=True)
class TestConcurrency:
    def test_two_concurrent_transitions_only_one_wins(self, staff):
        """Two staff advance the same intake application at once: exactly one succeeds
        and exactly one history row is written (row lock + re-validation under lock)."""
        app = ApplicationFactory(status=S.INTAKE)
        StatusHistoryFactory(application=app, to_status=S.INTAKE, changed_by=app.homeowner)
        barrier = threading.Barrier(2)
        outcomes = []

        def worker():
            try:
                barrier.wait(timeout=5)
                transition_application(application_id=app.id, to_status=S.ELIGIBILITY_CHECK, by_user=staff)
                outcomes.append("ok")
            except InvalidTransition:
                outcomes.append("rejected")
            except Exception as exc:  # noqa: BLE001
                outcomes.append(f"error: {exc!r}")
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert sorted(outcomes) == ["ok", "rejected"], outcomes
        app.refresh_from_db()
        assert app.status == S.ELIGIBILITY_CHECK
        assert app.status_history.filter(to_status=S.ELIGIBILITY_CHECK).count() == 1
        assert Application.objects.get(pk=app.id).status_history.count() == 2
