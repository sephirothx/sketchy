"""Grouping reports of one incident, and reading them as one thread.

Five players watching the same person do the same thing file five reports.
Nothing about that is a mistake - it is what a room full of witnesses looks
like - but read one at a time it costs a moderator five readings of one
story, and decided one at a time it costs five decisions, four of which are
about something already dealt with (#620).

An **incident** is those reports read together: one reported account, in one
place. The key is derived from what the report already records rather than
matched by hand, and the grouping is derived at read time rather than stored,
because the reports and the decision are the facts and this is a way of
looking at them.

Nothing here does I/O. It is handed rows and returns a shape.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.db.models import PlayerReport, PlayerReportMessageEvidence
from app.domain_values import ReportScope


@dataclass(frozen=True)
class IncidentKey:
    """What makes two reports the same incident.

    A room instance is the natural bound: it says where the complaint
    happened and, because the instance ends when the room does, roughly when
    - without a window anybody has to pick a number for. The lobby has no
    instance, so every lobby report about one account shares its one bucket.

    `standalone` is set for a report that groups with nothing: one that cited
    no evidence and so names no place to look, or one whose reported account
    has since been anonymised away. It carries the report's own id, which
    makes each such report its own incident rather than heaping the
    ungroupable together under a key they only appear to share.
    """

    reported_user_id: UUID | None
    scope: str
    room_instance_id: UUID | None
    standalone: UUID | None = None


class Groupable(Protocol):
    """The columns an incident is grouped by, and nothing else.

    Stated as a protocol so the queue can group from a light row - five
    columns, no evidence - and load the reports only for the page it is
    actually going to render. The grouping rule then has one implementation
    whether it is handed a row or a report.
    """

    id: UUID
    reported_user_id: UUID | None
    scope: str
    room_instance_id: UUID | None
    created_at: datetime


def incident_key(report: Groupable) -> IncidentKey:
    if report.reported_user_id is None or report.scope == ReportScope.UNSCOPED.value:
        return IncidentKey(None, report.scope, None, report.id)
    return IncidentKey(report.reported_user_id, report.scope, report.room_instance_id)


@dataclass(frozen=True)
class EvidenceLine:
    """One line of the merged thread, and which reports cited it.

    `cited_by` is empty for a line no report cited - context the server
    copied around somebody's citation. A line cited by any report in the
    incident is cited for the whole of it: what makes a line evidence is that
    somebody complained about it, not how many did.
    """

    evidence: PlayerReportMessageEvidence
    cited_by: tuple[UUID, ...]

    @property
    def role(self) -> str:
        return "cited" if self.cited_by else "context"


@dataclass(frozen=True)
class Incident:
    """Reports of one incident, oldest first.

    `id` is the oldest report's id. A client needs one handle to name the
    incident, and the oldest report is stable in a way a synthesised id is
    not: it does not change when a sixth reporter arrives, and it is already
    a real row every decision route accepts.
    """

    key: IncidentKey
    reports: tuple[PlayerReport, ...]

    @property
    def id(self) -> UUID:
        return self.reports[0].id

    @property
    def report_ids(self) -> tuple[UUID, ...]:
        return tuple(report.id for report in self.reports)

    @property
    def opened_at(self) -> datetime:
        return self.reports[0].created_at

    @property
    def latest_at(self) -> datetime:
        return self.reports[-1].created_at

    @property
    def reasons(self) -> tuple[str, ...]:
        """The distinct reasons given, in the order they were first given.

        Five reporters rarely reach for the same word for one incident, and
        which words they reached for is worth reading. Deduplicated because
        four people choosing `harassment` is four reporters, not four
        reasons - the count says how many complained.
        """
        seen: dict[str, None] = {}
        for report in self.reports:
            seen.setdefault(report.reason, None)
        return tuple(seen)

    @property
    def evidence(self) -> tuple[EvidenceLine, ...]:
        """Every report's evidence as one thread, each line once.

        Deduplicated on the message's own identity, because the same line
        reaches the incident once per reporter who cited it and once more as
        context around somebody else's citation - and a moderator reading the
        thread should meet it once, knowing who complained about it.

        This is a union across several reporters' audiences and blocks, which
        is exactly the point: it is the first view of the incident that is
        not one witness's slice of it. It is a reviewer's view and never the
        player's - a Warning or a Suspension shows cited lines only
        (R-MOD-12), and every cited line is by construction their own.
        """
        cited: dict[UUID, list[UUID]] = {}
        lines: dict[UUID, PlayerReportMessageEvidence] = {}
        for report in self.reports:
            for line in report.message_evidence:
                key = line.source_message_snapshot_id
                # The first copy wins. Every copy of one line snapshots the
                # same message, so they agree on everything a reader sees.
                lines.setdefault(key, line)
                if line.role == "cited":
                    cited.setdefault(key, []).append(report.id)
        return tuple(
            EvidenceLine(line, tuple(cited.get(key, ())))
            for key, line in sorted(
                lines.items(),
                key=lambda pair: (pair[1].message_created_at, pair[0]),
            )
        )

    @property
    def drawings(self) -> tuple[PlayerReport, ...]:
        """The reports that carried a canvas, oldest first.

        Several reporters watching one drawing each attach the canvas as it
        stood when they sent, so the set is the drawing as it changed under
        them. Kept as the reports rather than the evidence rows, because the
        bytes are fetched per report and only ever by a reviewer.
        """
        return tuple(
            report for report in self.reports if report.drawing_evidence is not None
        )


def group_into_incidents(reports: list) -> list[Incident]:
    """Reports as incidents, each oldest-first, ordered by when it opened.

    The queue stays oldest-first on the first report of each incident. Volume
    deliberately does not reorder anything: six reports is six people who
    chose to complain, not six times the evidence, and letting a pile-on jump
    the queue would reward arranging one.
    """
    grouped: dict[IncidentKey, list[PlayerReport]] = {}
    for report in reports:
        grouped.setdefault(incident_key(report), []).append(report)
    incidents = [
        Incident(key, tuple(sorted(rows, key=lambda row: (row.created_at, row.id))))
        for key, rows in grouped.items()
    ]
    incidents.sort(key=lambda incident: (incident.opened_at, incident.id))
    return incidents
