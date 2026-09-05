"""The moderation payload guards, exercised directly.

Every model here is the staff-facing safety surface, and every guard below is
the difference between a moderation record that means something and one that
does not: a `details` field of three spaces satisfies `min_length=1` and says
nothing, a naive `expiresAt` is a suspension whose end nobody can agree on, and
a duplicated message id is evidence counted twice.

The endpoint suites reach these models only through requests that are meant to
succeed, so the rejection branches went untested. `docs/requirements.md`
R-ENG-02 requires bounded validation to complete before authorization or
mutation, which is precisely why it is worth knowing the bounds hold.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.api.moderation import (
    MAX_REPORT_CONTEXT_BYTES,
    BanBody,
    BanRevokeBody,
    PromptContentReportBody,
    PromptContentReviewBody,
    ReportBody,
    ReportReviewBody,
    WarningBody,
)


# Whitespace only. The empty string is refused a step earlier, by
# `min_length=1`, so it carries Pydantic's own message rather than the
# validator's - covered separately below.
BLANK = ["   ", "\t", "\n  \n"]


def _report(**overrides) -> dict:
    payload = {
        "reportedUserId": str(uuid4()),
        "reason": "harassment",
        "details": "they would not stop",
    }
    payload.update(overrides)
    return payload


# --- text that is present but says nothing ----------------------------------


@pytest.mark.parametrize("blank", BLANK)
def test_report_details_that_are_only_whitespace_are_stored_empty(blank):
    """The evidence is the complaint, so the words beside it are optional -
    and blank is stored as nothing rather than as a row of spaces."""
    assert ReportBody(**_report(details=blank)).details == ""


def test_report_details_may_be_left_out_altogether():
    body = _report()
    body.pop("details", None)
    assert ReportBody(**body).details == ""


@pytest.mark.parametrize("blank", BLANK)
def test_a_review_note_that_is_only_whitespace_is_refused(blank):
    with pytest.raises(ValidationError, match="note cannot be blank"):
        ReportReviewBody(status="resolved", note=blank)


@pytest.mark.parametrize("blank", BLANK)
def test_a_prompt_report_with_blank_details_is_refused(blank):
    with pytest.raises(ValidationError, match="details cannot be blank"):
        PromptContentReportBody(
            promptListId=str(uuid4()), reason="offensive", details=blank
        )


@pytest.mark.parametrize("blank", BLANK)
def test_a_prompt_review_with_a_blank_note_is_refused(blank):
    with pytest.raises(ValidationError, match="note cannot be blank"):
        PromptContentReviewBody(status="dismissed", note=blank)


@pytest.mark.parametrize("blank", BLANK)
def test_a_suspension_without_a_stated_reason_is_refused(blank):
    """The reason is shown to the suspended player. Blank is not an answer."""
    with pytest.raises(ValidationError, match="reason cannot be blank"):
        BanBody(userId=str(uuid4()), reason=blank)


@pytest.mark.parametrize("blank", BLANK)
def test_revoking_a_suspension_without_a_reason_is_refused(blank):
    with pytest.raises(ValidationError, match="reason cannot be blank"):
        BanRevokeBody(reason=blank)


@pytest.mark.parametrize("blank", BLANK)
def test_a_warning_without_a_reason_is_refused(blank):
    with pytest.raises(ValidationError, match="reason cannot be blank"):
        WarningBody(userId=str(uuid4()), reason=blank)


@pytest.mark.parametrize(
    ("build", "field"),
    [
        (lambda v: ReportReviewBody(status="resolved", note=v), "note"),
        (lambda v: BanBody(userId=str(uuid4()), reason=v), "reason"),
        (lambda v: BanRevokeBody(reason=v), "reason"),
        (lambda v: WarningBody(userId=str(uuid4()), reason=v), "reason"),
        (
            lambda v: PromptContentReportBody(
                promptListId=str(uuid4()), reason="offensive", details=v
            ),
            "details",
        ),
        (lambda v: PromptContentReviewBody(status="dismissed", note=v), "note"),
    ],
)
def test_an_empty_string_is_refused_too(build, field):
    """By `min_length`, one guard earlier than the strip - but still refused."""
    with pytest.raises(ValidationError):
        build("")


def test_surrounding_whitespace_is_stripped_rather_than_rejected():
    assert ReportBody(**_report(details="  they would not stop  ")).details == (
        "they would not stop"
    )
    assert BanRevokeBody(reason="  mistaken  ").reason == "mistaken"


# --- bounds -----------------------------------------------------------------


def test_an_oversized_context_snapshot_is_refused():
    """The snapshot is attacker-influenced and lands in the database."""
    oversized = {"chat": "x" * (MAX_REPORT_CONTEXT_BYTES + 1)}
    with pytest.raises(ValidationError, match="contextSnapshot is too large"):
        ReportBody(**_report(contextSnapshot=oversized))


def test_a_context_snapshot_inside_the_bound_is_kept():
    snapshot = {"chat": "x" * 100}
    assert ReportBody(**_report(contextSnapshot=snapshot)).context_snapshot == snapshot


def test_duplicate_message_ids_are_refused():
    """Evidence counted twice reads as a worse pattern than what happened."""
    duplicated = str(uuid4())
    with pytest.raises(ValidationError, match="messageIds must be unique"):
        ReportBody(**_report(messageIds=[duplicated, duplicated]))


def test_distinct_message_ids_are_kept_in_order():
    first, second = str(uuid4()), str(uuid4())
    body = ReportBody(**_report(messageIds=[first, second]))
    assert [str(value) for value in body.message_ids] == [first, second]


# --- when a suspension ends -------------------------------------------------


def test_a_naive_expiry_is_refused():
    """Two people reading a bare timestamp disagree about when it ends."""
    with pytest.raises(ValidationError, match="expiresAt must include a timezone"):
        BanBody(
            userId=str(uuid4()),
            reason="harassment",
            expiresAt=datetime(2026, 9, 1, 12, 0, 0),
        )


def test_an_aware_expiry_is_normalised_to_utc():
    somewhere_else = timezone(timedelta(hours=5, minutes=30))
    local = datetime(2026, 9, 1, 12, 0, 0, tzinfo=somewhere_else)
    body = BanBody(userId=str(uuid4()), reason="harassment", expiresAt=local)
    assert body.expires_at.tzinfo == timezone.utc
    assert body.expires_at == local


def test_a_suspension_may_have_no_expiry():
    assert BanBody(userId=str(uuid4()), reason="harassment").expires_at is None


# --- the models refuse what they were not asked ------------------------------


def test_unknown_fields_are_refused():
    """extra="forbid" across the surface: a typo must not be silently ignored."""
    with pytest.raises(ValidationError):
        ReportBody(**_report(escalate=True))
    with pytest.raises(ValidationError):
        BanRevokeBody(reason="mistaken", permanent=True)
