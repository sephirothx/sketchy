import { useClock } from "../hooks/useClock";
import { useCallback, useEffect, useMemo, useState } from "react";
import { AppHeader } from "../components/AppHeader";
import { NotFoundPage } from "./NotFoundPage";
import { ReportedDrawing } from "../components/ReportedDrawing";
import { Chip, type ChipKind } from "../components/ui/Chip";
import { SectionLabel } from "../components/ui/Card";

import { ApiError } from "../lib/api";
import {
  CLOSED_CASES_PAGE_SIZE,
  createUserBan,
  createUserWarning,
  fetchReportDrawing,
  listClosedCases,
  listModerationReports,
  listHeldPublications,
  listPromptContentReports,
  listUserBans,
  revokeUserBan,
  removeReportedAvatar,
  reviewModerationReport,
  readHeldPublication,
  reviewHeldPublication,
  reviewPromptContentReport,
  type ContentIncident,
  type HeldPublication,
  type HeldPublicationDetail,
  type IncidentEvidence,
  type PlayerReportDrawing,
  composeRepeatNote,
  REPORT_REASONS,
  type ReportReason,
  scopeWords,
  type IncidentPicture,
  type ModerationIncident,
  type PriorDecision,
  type ReportOutcome,
  suspensionExpiry,
  SUSPENSION_DURATIONS,
  type UserBan,
} from "../lib/moderation";
import { canModerate } from "../lib/operatorAccess";
import { useAuthStore } from "../store/authStore";
import { STEP_UP_ABANDONED, useStepUp } from "../hooks/useStepUp";

type Filter = "open" | "players" | "content" | "held" | "bans" | "closed";
type CaseKind = "incident" | "content" | "held" | "ban";
type Selection = { kind: CaseKind; id: string };

type QueueEntry = {
  kind: CaseKind;
  id: string;
  title: string;
  snippet: string;
  /** What the list is ordered by and dated with: when the case arrived, or
      for a closed one when it was decided. */
  at: string;
  dot: "danger" | "warning" | "neutral";
  /** How a closed case ended; absent while it is still open. */
  outcome?: ReportOutcome;
  /** How many people complained, when more than one did. Shown, and
      deliberately not sorted on. */
  reporterCount?: number;
};

/** One chip per outcome: what was done, in the colour of how serious it was.
    Green for a case that ended with nothing against anyone, orange for a
    warning, red for a suspension or a takedown. */
const OUTCOMES: Record<ReportOutcome, { label: string; kind: ChipKind }> = {
  pending: { label: "Waiting", kind: "neutral" },
  dismissed: { label: "Dismissed", kind: "success" },
  resolved: { label: "Resolved", kind: "neutral" },
  warned: { label: "Warned", kind: "warning" },
  suspended: { label: "Suspended", kind: "danger" },
  hidden: { label: "Hidden", kind: "danger" },
  left_up: { label: "Left up", kind: "success" },
};

function OutcomeChip({ outcome }: { outcome: ReportOutcome }) {
  const { label, kind } = OUTCOMES[outcome] ?? OUTCOMES.resolved;
  return <Chip kind={kind} className="mod-outcome-chip">{label}</Chip>;
}

/** How a closed case was decided: the outcome, who decided it and when, and
    the note they left. The note alone used to stand for all three. */
function DecisionCard({
  report,
  dateTime,
}: {
  report: ModerationIncident | ContentIncident;
  dateTime: (date: Date) => string;
}) {
  return (
    <section className="ops-card mod-decision" aria-label="Decision" data-testid="mod-decision">
      <div className="mod-decision-head">
        <h2>Decision</h2>
        <OutcomeChip outcome={report.outcome} />
      </div>
      <p className="mod-case-meta">
        {report.reviewedBy ? `By ${report.reviewedBy}` : "Reviewer no longer has an account"}
        {report.reviewedAt ? ` · ${formatWhen(report.reviewedAt, dateTime)}` : ""}
      </p>
      {report.resolutionNote && (
        <p className="mod-resolution">{report.resolutionNote}</p>
      )}
    </section>
  );
}

const FILTERS: { name: Filter; label: string }[] = [
  { name: "open", label: "All open" },
  { name: "players", label: "Player reports" },
  { name: "content", label: "Prompt content" },
  { name: "held", label: "Held publications" },
  { name: "bans", label: "Suspensions" },
  { name: "closed", label: "Closed" },
];

/** When a decided case was decided. The review stamps it; the last write
    stands in for a row decided some other way. */
function decidedAt(report: { reviewedAt: string | null; updatedAt?: string }): string {
  return report.reviewedAt ?? report.updatedAt ?? "";
}

function formatWhen(value: string, dateTime: (date: Date) => string): string {
  return dateTime(new Date(value));
}

function age(value: string): string {
  const minutes = Math.max(0, Math.round((Date.now() - Date.parse(value)) / 60000));
  if (minutes < 60) return `${minutes}m`;
  if (minutes < 60 * 24) return `${Math.round(minutes / 60)}h`;
  return `${Math.round(minutes / (60 * 24))}d`;
}

function humanize(value: string): string {
  const spaced = value.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** Account age in the coarsest sensible unit, for the context card. */
function accountAge(createdAt: string): string {
  const days = Math.max(0, Math.floor((Date.now() - Date.parse(createdAt)) / 86400000));
  if (days < 1) return "Today";
  if (days < 31) return `${days} day${days === 1 ? "" : "s"}`;
  if (days < 365) {
    const months = Math.floor(days / 30);
    return `${months} month${months === 1 ? "" : "s"}`;
  }
  const years = Math.floor(days / 365);
  return `${years} year${years === 1 ? "" : "s"}`;
}

/** The drawing a report carries, for the case view. */
function ReportDrawing({
  reportId,
  drawing,
  drawerName,
  dateTime,
}: {
  reportId: string;
  drawing: PlayerReportDrawing;
  drawerName: string;
  dateTime: (date: Date) => string;
}) {
  return (
    <ReportedDrawing
      className="mod-drawing"
      testId="mod-drawing"
      load={() => fetchReportDrawing(reportId)}
      label={`${drawerName}'s drawing of ${drawing.prompt}, as it was when reported`}
      caption={
        <>
          The canvas when the report was sent, {formatWhen(drawing.capturedAt, dateTime)}:
          round {drawing.roundNumber}, {drawing.actionCount} action
          {drawing.actionCount === 1 ? "" : "s"}. They were asked to draw{" "}
          <strong>{drawing.prompt || "nothing yet"}</strong>.
        </>
      }
    />
  );
}

/** Who complained, and in whose words.

An incident's reports are the one thing merging must not flatten: five people
choosing five different words for what happened is evidence in itself, and a
moderator who only sees the first complaint has read a fifth of the case. The
evidence below is merged because it is one conversation seen from several
seats; this is not. */
function ReportersPanel({
  incident,
  dateTime,
}: {
  incident: ModerationIncident;
  dateTime: (date: Date) => string;
}) {
  const many = incident.reports.length > 1;
  return (
    <>
      <h2>{many ? `${incident.reports.length} complaints` : "The complaint"}</h2>
      <ol className="mod-reporters" data-testid="mod-reporters">
        {incident.reports.map((report, index) => (
          <li key={report.id} className="mod-reporter">
            <div className="mod-reporter-head">
              {many && <span className="mod-reporter-index">{index + 1}</span>}
              <Chip kind="neutral">{humanize(report.reason)}</Chip>
              <time dateTime={report.createdAt}>
                {formatWhen(report.createdAt, dateTime)}
              </time>
              {report.pictureStatus === "replaced" && (
                <Chip kind="warning">Different picture now</Chip>
              )}
              {report.pictureStatus === "removed" && (
                <Chip kind="neutral">Picture gone</Chip>
              )}
            </div>
            <p className="mod-case-details">
              {report.details ||
                "No details given; the evidence is the complaint."}
            </p>
          </li>
        ))}
      </ol>
    </>
  );
}

/** What became of the picture the case is about, when it is about one.

Only says anything when the picture is no longer the one complained about,
because "still the reported picture" is what a moderator assumes and does not
need telling. The removal case is the one this exists for: a picture already
taken down read as merely "a different picture now", which is the opposite of
what happened to it - and most often the moderator reading it is the one who
removed it, from this very case, a minute earlier. */
function PictureBanner({
  picture,
  dateTime,
}: {
  picture: IncidentPicture | null;
  dateTime: (date: Date) => string;
}) {
  if (!picture || picture.status === "same") return null;
  const when = picture.removedAt
    ? formatWhen(picture.removedAt, dateTime)
    : null;
  return (
    <aside className="mod-picture-note" data-testid="mod-picture-note">
      {picture.status === "removed" ? (
        <p>
          <strong>
            {picture.removedByModerator
              ? picture.removedFromThisIncident
                ? "Already removed from this case"
                : "Already removed by a moderator"
              : "The player took this picture down themselves"}
          </strong>
          {when ? ` — ${when}.` : "."}{" "}
          {!picture.removedByModerator
            ? "The account has no picture. Taking your own down is not a punishment and sets no block."
            : picture.uploadBlockedUntil
              ? `The account has no picture, and cannot upload another until ${formatWhen(picture.uploadBlockedUntil, dateTime)}.`
              : "The account has no picture. They may upload another one now."}
        </p>
      ) : (
        <p>
          <strong>This is a different picture.</strong> The one complained
          about is gone — an upload deletes what it replaces — so what is shown
          is the one on the account now, and the one a removal would act on.
        </p>
      )}
    </aside>
  );
}

/** What was already decided about this same incident.

A decided incident cannot be reopened, so a fresh complaint about the same
person in the same place opens a new one - which is right, and which would
otherwise arrive looking like nothing had ever been done about it. The note
is shown because it was written for whoever reads the case next, and this is
that reader. */
function PriorDecisionBanner({
  prior,
  repeat,
  dateTime,
  onRepeat,
  busy,
}: {
  prior: PriorDecision | null;
  repeat: string;
  dateTime: (date: Date) => string;
  /** Dismiss this incident on the strength of the one above it. */
  onRepeat: (note: string) => void;
  busy: boolean;
}) {
  if (!prior) return null;
  const again = prior.priorDecisions > 1;
  return (
    <aside className="mod-prior" data-testid="mod-prior-decision">
      <p className="mod-prior-head">
        <Chip kind={OUTCOMES[prior.outcome]?.kind ?? "neutral"}>
          {OUTCOMES[prior.outcome]?.label ?? humanize(prior.outcome)}
        </Chip>
        <span>
          {again
            ? `Decided ${prior.priorDecisions} times before — most recently`
            : "This was decided before —"}{" "}
          {prior.decidedAt ? formatWhen(prior.decidedAt, dateTime) : "at an unknown time"}
          {prior.decidedBy ? ` by ${prior.decidedBy}` : ""}, about the same player{" "}
          {repeat}.
        </span>
      </p>
      {prior.note && <p className="mod-prior-note">“{prior.note}”</p>}
      {/* The common ending for a repeat: nothing new happened, and the case
          above already says what was made of it. Only a dismissal is offered
          from here - it restricts nobody, so it is the one outcome that can
          safely be one press away from a moderator who has read this. A
          warning or a suspension is not repeated by shortcut. */}
      <div className="mod-prior-actions">
        <button
          type="button"
          className="btn btn-secondary btn-compact"
          disabled={busy}
          data-testid="mod-prior-dismiss"
          onClick={() =>
            onRepeat(
              composeRepeatNote(
                prior,
                OUTCOMES[prior.outcome]?.label ?? humanize(prior.outcome),
                prior.decidedAt ? formatWhen(prior.decidedAt, dateTime) : null,
              ),
            )
          }
        >
          Dismiss as already decided
        </button>
        <span className="mod-prior-hint">
          Closes this one with the decision above as its note.
        </span>
      </div>
    </aside>
  );
}

/** Who complained about this content, and in whose words.

The target is one thing and is stated once above; how people described it is
not, and merging that away would lose the part a moderator reads. */
function ContentReportersPanel({
  incident,
  dateTime,
}: {
  incident: ContentIncident;
  dateTime: (date: Date) => string;
}) {
  const many = incident.reports.length > 1;
  return (
    <>
      <h3>{many ? `${incident.reports.length} complaints` : "The complaint"}</h3>
      <ol className="mod-reporters" data-testid="mod-content-reporters">
        {incident.reports.map((report, index) => (
          <li key={report.id} className="mod-reporter">
            <div className="mod-reporter-head">
              {many && <span className="mod-reporter-index">{index + 1}</span>}
              <Chip kind="neutral">{humanize(report.reason)}</Chip>
              <time dateTime={report.createdAt}>
                {formatWhen(report.createdAt, dateTime)}
              </time>
            </div>
            <p className="mod-case-details">
              {report.details || "No details given."}
            </p>
          </li>
        ))}
      </ol>
    </>
  );
}

/** One line of the merged thread.

A cited line says how many of the incident's reporters picked it out. That is
the one number worth reading off a pile-on: it separates the line everybody
complained about from the one line only one person did, which is a difference
the count of reports on its own cannot show. */
function EvidenceLine({
  line,
  reporterCount,
}: {
  line: IncidentEvidence;
  reporterCount: number;
}) {
  const cited = line.citedBy?.length ?? 0;
  return (
    <span className={`mod-evidence-line is-${line.role}`} data-role={line.role}>
      <strong>{line.senderDisplayName}:</strong> {line.text}
      {reporterCount > 1 && cited > 0 && (
        <span className="mod-evidence-cites" data-testid="mod-evidence-cites">
          {cited === reporterCount
            ? `all ${reporterCount} reporters`
            : `${cited} of ${reporterCount}`}
        </span>
      )}
      {/* The snapshot is the evidence. The live message may have been deleted
          since, which is the point of keeping one. */}
      {!line.sourceAvailable && <em> — original no longer in the room</em>}
    </span>
  );
}

export function ModerationPage() {
  const { dateTime } = useClock();
  const user = useAuthStore((state) => state.user);
  const hasResolved = useAuthStore((state) => state.hasResolved);
  const [filter, setFilter] = useState<Filter>("open");
  // Which page of closed cases is open, and whether an older one exists.
  const [page, setPage] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [incidents, setIncidents] = useState<ModerationIncident[]>([]);
  const [content, setContent] = useState<ContentIncident[]>([]);
  const [bans, setBans] = useState<UserBan[]>([]);
  // Publications the switch is holding (R-LIST-13). Not a report queue:
  // nothing was complained about, so there is no reporter and no reason -
  // only a list waiting for somebody to read it.
  const [held, setHeld] = useState<HeldPublication[]>([]);
  const [heldDetail, setHeldDetail] = useState<HeldPublicationDetail | null>(null);
  const [openCount, setOpenCount] = useState(0);
  const [selected, setSelected] = useState<Selection | null>(null);
  const [note, setNote] = useState<Record<string, string>>({});
  // Optional, so nothing here refuses to proceed without it: what it buys is
  // a notice with structure when the sentence is terse, not another gate on
  // a decision that already has a step-up in front of it.
  const [category, setCategory] = useState<Record<string, ReportReason>>({});
  const [duration, setDuration] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const { guard, dialog: stepUpDialog } = useStepUp();
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const allowed = hasResolved && canModerate(user?.role);
  const showingClosed = filter === "closed";

  const fail = useCallback((problem: unknown) => {
    setError(
      problem instanceof ApiError
        ? problem.message
        : "Could not reach the moderation queue.",
    );
  }, []);

  const load = useCallback(() => {
    if (!allowed) return;
    // The open queues are the pending work, whatever is being viewed: the
    // "N open" chip counts them even while a closed page is on screen.
    const pending = Promise.all([
      listModerationReports("pending"),
      listPromptContentReports("pending"),
    ]);
    // Closed cases are paged by the server, newest decision first, because
    // they accumulate for as long as the service runs; the open queues are
    // small enough to hold whole.
    const cases = showingClosed
      ? listClosedCases({
          limit: CLOSED_CASES_PAGE_SIZE,
          offset: page * CLOSED_CASES_PAGE_SIZE,
        })
      : pending.then(([playerResult, contentResult]) => ({
          players: playerResult.incidents,
          content: contentResult.incidents,
          hasMore: false,
        }));
    void Promise.all([
      cases,
      // Everything, not only what is in force: a suspension that has been
      // lifted or has expired is part of the record of what was done.
      listUserBans(),
      pending,
      listHeldPublications(),
    ])
      .then(([caseResult, banResult, pendingResult, heldResult]) => {
        setIncidents(caseResult.players);
        setContent(caseResult.content);
        setHasMore(caseResult.hasMore);
        setBans(banResult.bans);
        // Incidents, not reports: the chip counts the work waiting, and
        // five complaints about one thing are one thing to look at.
        setHeld(heldResult.lists);
        setOpenCount(
          pendingResult[0].incidents.length
            + pendingResult[1].incidents.length
            // A held list is work waiting too: nobody else is going to
            // complain about it, because it is out of everyone's reach.
            + heldResult.waiting,
        );
        setError(null);
      })
      .catch(fail);
  }, [allowed, showingClosed, page, fail]);

  useEffect(load, [load]);

  // A page is a position in the closed stream and means nothing elsewhere.
  function changeFilter(next: Filter) {
    setFilter(next);
    setPage(0);
  }

  const queue = useMemo<QueueEntry[]>(() => {
    // A closed case is dated by its decision and marked as settled; an open
    // one by its arrival and by what kind of trouble it is.
    // The reported player is what an incident is about; the reasons are how
    // the people who complained described it, which may be several things.
    const playerEntries: QueueEntry[] = incidents.map((incident) => ({
      kind: "incident",
      id: incident.id,
      title: incident.reportedPlayer?.displayName ?? "Deleted player",
      snippet: incident.reasons.map(humanize).join(" · "),
      at: showingClosed ? decidedAt(incident) : incident.openedAt,
      dot: showingClosed ? "neutral" : "danger",
      outcome: showingClosed ? incident.outcome : undefined,
      reporterCount: incident.reporterCount,
    }));
    // The content is what an incident is about; the reasons are how the
    // people who complained described it.
    const contentEntries: QueueEntry[] = content.map((incident) => ({
      kind: "content",
      id: incident.id,
      title:
        incident.targetType === "prompt"
          ? `Prompt “${incident.prompt}”`
          : `List “${incident.listName}”`,
      snippet: incident.reasons.map(humanize).join(" · "),
      at: showingClosed ? decidedAt(incident) : incident.openedAt,
      dot: showingClosed ? "neutral" : "warning",
      outcome: showingClosed ? incident.outcome : undefined,
      reporterCount: incident.reporterCount,
    }));
    const heldEntries: QueueEntry[] = held.map((publication) => ({
      kind: "held",
      id: publication.id,
      title: `List “${publication.name}”`,
      snippet: `by ${publication.ownerDisplayName ?? "Deleted player"} · ${publication.promptCount} prompts`,
      at: publication.publishedAt ?? "",
      dot: "warning",
    }));
    const banEntries: QueueEntry[] = bans.map((ban) => ({
      kind: "ban",
      id: ban.id,
      title: ban.displayName ?? "Deleted player",
      snippet: ban.reason,
      at: ban.createdAt,
      dot: ban.isActive ? "danger" : "neutral",
    }));
    const entries =
      filter === "players"
        ? playerEntries
        : filter === "content"
          ? contentEntries
          : filter === "held"
            ? heldEntries
            : filter === "bans"
              ? banEntries
              // Nothing held is decided yet, so it belongs to "All open" and
              // never to the archive of what was settled.
              : showingClosed
                ? [...playerEntries, ...contentEntries]
                : [...playerEntries, ...contentEntries, ...heldEntries];
    return entries.sort((a, b) => Date.parse(b.at) - Date.parse(a.at));
  }, [filter, showingClosed, incidents, content, bans, held]);

  // Derived rather than synced by an effect: whatever is clicked wins while
  // it is still in the queue, and the newest entry stands in otherwise.
  const active: Selection | null = useMemo(() => {
    if (
      selected &&
      queue.some((entry) => entry.kind === selected.kind && entry.id === selected.id)
    ) {
      return selected;
    }
    return queue.length > 0 ? { kind: queue[0].kind, id: queue[0].id } : null;
  }, [queue, selected]);

  // Up here rather than beside the other cases below, because the effect that
  // reads the list needs it and hooks may not sit under the early return.
  const heldCase = useMemo(
    () =>
      active?.kind === "held"
        ? held.find((publication) => publication.id === active.id) ?? null
        : null,
    [active, held],
  );

  // The revision actually on screen, which is the one a decision is taken on:
  // every decision below names `heldRead.version` rather than the version the
  // queue summary happens to carry. The two can differ for a moment after an
  // owner edits a list that is already open, and naming the summary's version
  // there would release a revision nobody had read (R-LIST-05). Naming what
  // was read instead means the worst case is the server refusing it.
  const heldRead =
    heldDetail && heldCase && heldDetail.id === heldCase.id ? heldDetail : null;

  // Everything about the list comes from that one response once it is here -
  // name, description, prompts, version - so no field on screen can belong to
  // a revision the decision does not name. The queue summary stands in only
  // while the read is in flight, which is also while there is nothing to
  // decide with.
  const heldShown = heldRead ?? heldCase;

  // Keyed on the version as well as the list: an owner may edit a list while
  // it waits, and re-reading only when the selection changes would leave the
  // old prompts on screen beside a decision that now names the new revision.
  const heldId = heldCase?.id;
  const heldVersion = heldCase?.version;
  // Bumped when a decision is refused, because the reason may be a version
  // the queue has not caught up with yet: the id and the version can both
  // come back unchanged, and then nothing above would ask for the list again.
  const [heldStale, setHeldStale] = useState(0);
  useEffect(() => {
    if (heldId === undefined) return;
    let cancelled = false;
    // The queue carries a name and a count; a decision needs the words.
    void readHeldPublication(heldId)
      .then((detail) => { if (!cancelled) setHeldDetail(detail); })
      .catch(fail);
    return () => { cancelled = true; };
  }, [heldId, heldVersion, heldStale, fail]);

  if (hasResolved && !allowed) {
    // The same answer the API gives this account. A page that names the
    // surface and refuses it confirms the surface exists; R-ROLE-01 has every
    // endpoint behind these entries answer 404 rather than 403, and the door
    // in front of them should say the same thing.
    return <NotFoundPage />;
  }

  async function act(
    id: string,
    run: () => Promise<unknown>,
    // A string, or what to say once the answer is in - for an action whose
    // outcome is not fixed in advance.
    done: string | ((outcome: unknown) => string),
    // The note `run` will send, when the caller composed one rather than
    // taking it from the box - the required-note rule is about what reaches
    // the ledger, not about which field it was typed into.
    composed?: string,
  ) {
    if (busy) return;
    if (!(composed ?? note[id] ?? "").trim()) {
      setError("A note is required, so the decision is not anonymous.");
      return;
    }
    setBusy(id);
    setError(null);
    try {
      // Every decision here is destructive, so each one may be met with
      // R-AUTH-21's "prove it again" - which `guard` turns into a prompt and
      // then this same call, re-sent. `undefined` means the prompt was
      // dismissed: nothing happened, so nothing is announced or cleared.
      const outcome = await guard(run);
      if (outcome === STEP_UP_ABANDONED) return;
      setMessage(typeof done === "string" ? done : done(outcome));
      setNote((current) => ({ ...current, [id]: "" }));
      load();
    } catch (problem) {
      fail(problem);
    } finally {
      setBusy(null);
    }
  }

  const playerCase =
    active?.kind === "incident"
      ? incidents.find((incident) => incident.id === active.id)
      : undefined;
  const contentCase =
    active?.kind === "content"
      ? content.find((report) => report.id === active.id)
      : undefined;
  const banCase =
    active?.kind === "ban"
      ? bans.find((ban) => ban.id === active.id)
      : undefined;

  const categoryField = (id: string) => (
    <label className="mod-note mod-category">
      What was it (optional)
      <select
        value={category[id] ?? ""}
        onChange={(change) =>
          setCategory((current) => {
            const next = { ...current };
            if (change.target.value) {
              next[id] = change.target.value as ReportReason;
            } else {
              delete next[id];
            }
            return next;
          })
        }
      >
        <option value="">Not recorded</option>
        {REPORT_REASONS.map((reason) => (
          <option key={reason} value={reason}>
            {humanize(reason)}
          </option>
        ))}
      </select>
      <span className="mod-note-hint">
        Your finding, shown to the player with the decision. Never the
        reporters&rsquo; words.
      </span>
    </label>
  );

  const noteField = (id: string) => (
    <label className="mod-note">
      Resolution note
      <textarea
        placeholder="Why, in one line — required to decide"
        value={note[id] ?? ""}
        onChange={(change) =>
          setNote((current) => ({ ...current, [id]: change.target.value }))
        }
      />
      <span className="mod-note-hint">
        Kept in the append-only audit ledger. A warning or suspension from
        here also resolves the incident.
      </span>
    </label>
  );

  /** What a decision here will close, said before it is taken.

      A moderator pressing Dismiss on an incident of five is deciding five
      complaints, and should not have to infer that from a chip in the
      queue. */
  const decisionScope = (
    incident: ModerationIncident | ContentIncident,
    about: string,
  ) =>
    incident.reporterCount > 1 && (
      <p className="mod-decision-scope" data-testid="mod-decision-scope">
        This decides all {incident.reporterCount} complaints about {about},
        under one note.
      </p>
    );

  /**
   * One held decision, with the resync a refusal needs.
   *
   * A 409 here is the version check: the owner edited the list after it was
   * read, so the revision this names no longer exists to decide on. Dropping
   * what was read and pulling the queue again is the whole remedy - without
   * it every retry resubmits the same stale version and is refused the same
   * way, and the only way out is reloading the browser.
   */
  const decideHeld =
    (id: string, version: number, state: "active" | "hidden") => async () => {
      try {
        return await reviewHeldPublication(id, state, note[id], version);
      } catch (problem) {
        if (problem instanceof ApiError && problem.status === 409) {
          // This list's read is the one that went stale, so only it is
          // dropped: the reviewer may have moved on to another case while
          // this decision was in flight, and that one is still what they
          // are reading.
          setHeldDetail((current) => (current?.id === id ? null : current));
          setHeldStale((count) => count + 1);
          load();
        }
        throw problem;
      }
    };

  return (
    <main className="ops-page">
      <AppHeader backLabel="Back to lobby" />
      {stepUpDialog}

      {error && (
        <p className="auth-error" role="alert">
          {error}
        </p>
      )}
      {message && (
        <p className="ops-empty" role="status">
          {message}
        </p>
      )}

      <div className="mod-layout">
        <aside className="ops-card mod-queue" aria-label="Review queue">
          <div className="mod-queue-head">
            <div>
              <SectionLabel>Moderation</SectionLabel>
              <h2>Review queue</h2>
            </div>
            <Chip kind={openCount > 0 ? "danger" : "success"}>
              {openCount} open
            </Chip>
          </div>
          <div className="mod-filters" role="group" aria-label="Queues">
            {FILTERS.map(({ name, label }) => (
              <button
                key={name}
                type="button"
                className="mod-filter-pill"
                aria-pressed={filter === name}
                onClick={() => changeFilter(name)}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="mod-queue-list">
            {queue.length === 0 && (
              <p className="ops-empty">
                {filter === "bans"
                  ? "Nobody has been suspended."
                  : showingClosed
                    ? page > 0
                      ? "No older cases."
                      : "No case has been decided yet."
                    : "Nothing in this queue."}
              </p>
            )}
            {queue.map((entry) => {
              const isSelected =
                active?.kind === entry.kind && active.id === entry.id;
              return (
                <button
                  key={`${entry.kind}:${entry.id}`}
                  type="button"
                  className={`mod-queue-item${isSelected ? " is-selected" : ""}`}
                  aria-current={isSelected || undefined}
                  onClick={() => setSelected({ kind: entry.kind, id: entry.id })}
                >
                  <span
                    className={`mod-queue-dot${
                      entry.dot === "danger"
                        ? " is-danger"
                        : entry.dot === "neutral"
                          ? " is-neutral"
                          : ""
                    }`}
                    aria-hidden="true"
                  />
                  <span className="mod-queue-item-text">
                    <strong>{entry.title}</strong>
                    {/* Said, never sorted on: a pile-on is more people, not
                        more evidence, and letting it jump the queue would
                        reward arranging one. */}
                    {entry.reporterCount !== undefined &&
                      entry.reporterCount > 1 && (
                        <Chip kind="warm" className="mod-reporter-chip">
                          {entry.reporterCount} reporters
                        </Chip>
                      )}
                    {entry.outcome && <OutcomeChip outcome={entry.outcome} />}
                    <span>{entry.snippet}</span>
                  </span>
                  <time dateTime={entry.at}>{age(entry.at)}</time>
                </button>
              );
            })}
          </div>
          {showingClosed && (
            <nav className="mod-pager" aria-label="Closed cases pages">
              <button
                type="button"
                className="btn btn-secondary"
                disabled={page === 0}
                onClick={() => setPage((current) => Math.max(0, current - 1))}
              >
                Newer
              </button>
              <span className="mod-pager-page">Page {page + 1}</span>
              <button
                type="button"
                className="btn btn-secondary"
                disabled={!hasMore}
                onClick={() => setPage((current) => current + 1)}
              >
                Older
              </button>
            </nav>
          )}
        </aside>

        <div className="mod-case">
          {playerCase && (
            <>
              <div className="mod-case-head">
                <div>
                  <SectionLabel>
                    Player report · #{playerCase.id.slice(0, 6)}
                  </SectionLabel>
                  <h1>
                    {playerCase.reportedPlayer?.displayName ?? "Deleted player"}
                  </h1>
                  <p className="mod-case-meta">
                    {playerCase.reporterCount === 1
                      ? "1 reporter"
                      : `${playerCase.reporterCount} reporters`}
                    {` · ${scopeWords(playerCase).label}`}
                    {` · opened ${formatWhen(playerCase.openedAt, dateTime)}`}
                    {playerCase.reporterCount > 1 &&
                      ` · latest ${formatWhen(playerCase.latestReportedAt, dateTime)}`}
                  </p>
                </div>
                {/* Every word the reporters reached for, not just the first
                    one's: five people rarely describe one thing the same way,
                    and which words they chose is worth reading. */}
                <div className="mod-reason-chips">
                  {playerCase.reasons.map((reason) => (
                    <Chip key={reason} kind="danger">{humanize(reason)}</Chip>
                  ))}
                </div>
              </div>

              <PictureBanner
                picture={playerCase.picture}
                dateTime={dateTime}
              />

              <PriorDecisionBanner
                prior={playerCase.priorDecision}
                repeat={scopeWords(playerCase).repeat}
                dateTime={dateTime}
                busy={busy === playerCase.id}
                onRepeat={(composed) =>
                  act(
                    playerCase.id,
                    () =>
                      reviewModerationReport(
                        playerCase.id,
                        "dismissed",
                        composed,
                      ),
                    "Dismissed, as already decided.",
                    composed,
                  )
                }
              />

              <div className="mod-case-columns">
                <section className="ops-card" aria-label="Reported evidence">
                  <ReportersPanel incident={playerCase} dateTime={dateTime} />
                  {playerCase.evidence.length > 0 && (
                    <>
                      <h2>What was said</h2>
                      {/* One thread, in the order it was said, however many
                          reports it took to assemble: the cited lines marked,
                          and around them what everyone else said, dimmed. A
                          line on its own is often unreadable; the
                          conversation is what a moderator judges. */}
                      <blockquote className="mod-evidence">
                        {playerCase.evidence.map((line) => (
                          <EvidenceLine
                            key={line.sourceMessageId}
                            line={line}
                            reporterCount={playerCase.reporterCount}
                          />
                        ))}
                      </blockquote>
                      <p className="mod-evidence-caption">
                        Marked lines are the ones reported — up to 20 per
                        report, pinned by the server exactly as each reporter
                        received them. The rest is what was said around them:
                        up to 10 lines before and 5 after, within 12 hours.
                        {playerCase.reporterCount > 1 &&
                          " Every report's evidence is merged here, each line" +
                            " once."}
                      </p>
                    </>
                  )}
                  {playerCase.drawings.length > 0
                    ? playerCase.drawings.map((drawing) => (
                        <ReportDrawing
                          key={drawing.reportId}
                          reportId={drawing.reportId}
                          drawing={drawing}
                          drawerName={
                            playerCase.reportedPlayer?.displayName ??
                            "The reported player"
                          }
                          dateTime={dateTime}
                        />
                      ))
                    : playerCase.reasons.includes("offensive_drawing") && (
                        <p className="mod-evidence-caption">
                          No drawing was attached: nobody included one, or the
                          reported player was not drawing at the time.
                        </p>
                      )}
                </section>
                <aside className="ops-card" aria-label="Account context">
                  <h2>Account context</h2>
                  {playerCase.reportedPlayer ? (
                    <>
                      <div className="mod-context-row">
                        <span>Player</span>
                        <strong>{playerCase.reportedPlayer.displayName}</strong>
                      </div>
                      {playerCase.reportedPlayer.avatarUrl && (
                        <div className="mod-context-row">
                          <span>Picture</span>
                          {/* Shown at the size a player list shows it, and
                              at full size on hover: the case may be about it. */}
                          <img
                            className="mod-context-avatar"
                            src={playerCase.reportedPlayer.avatarUrl}
                            alt={`${playerCase.reportedPlayer.displayName}'s picture`}
                          />
                        </div>
                      )}
                      <div className="mod-context-row">
                        <span>Account</span>
                        <strong>
                          {playerCase.reportedPlayer.registered
                            ? "Registered"
                            : "Guest"}
                        </strong>
                      </div>
                      <div className="mod-context-row">
                        <span>Age</span>
                        <strong>{accountAge(playerCase.reportedPlayer.createdAt)}</strong>
                      </div>
                      <div className="mod-context-row">
                        <span>Prior reports</span>
                        <strong>{playerCase.reportedPlayer.priorReports}</strong>
                      </div>
                      <div className="mod-context-row">
                        <span>Warnings</span>
                        <strong>{playerCase.reportedPlayer.priorWarnings}</strong>
                      </div>
                      <div className="mod-context-row">
                        <span>Active suspension</span>
                        <strong>
                          {playerCase.reportedPlayer.activeSuspension
                            ? "In force"
                            : "None"}
                        </strong>
                      </div>
                    </>
                  ) : (
                    <p className="mod-case-details">
                      The account behind this report no longer exists.
                    </p>
                  )}
                </aside>
              </div>

              {playerCase.status === "pending" ? (
                <>
                  {decisionScope(
                    playerCase,
                    playerCase.reportedPlayer?.displayName ?? "this player",
                  )}
                  {categoryField(playerCase.id)}
                  {noteField(playerCase.id)}
                  <div className="mod-actions">
                    <button
                      type="button"
                      className="btn btn-success"
                      disabled={busy === playerCase.id}
                      onClick={() =>
                        act(
                          playerCase.id,
                          () =>
                            reviewModerationReport(
                              playerCase.id,
                              "dismissed",
                              note[playerCase.id],
                            ),
                          "Dismissed.",
                        )
                      }
                    >
                      Dismiss
                    </button>
                    {/* Warning and suspending both need an account to act on;
                        a report about an accountless seat can only be closed,
                        so a plain Resolve stands in for those. */}
                    {!playerCase.reportedUserId && (
                      <button
                        type="button"
                        className="btn btn-secondary"
                        disabled={busy === playerCase.id}
                        onClick={() =>
                          act(
                            playerCase.id,
                            () =>
                              reviewModerationReport(
                                playerCase.id,
                                "resolved",
                                note[playerCase.id],
                              ),
                            "Resolved.",
                          )
                        }
                      >
                        Resolve
                      </button>
                    )}
                    {playerCase.reportedUserId && playerCase.reportedPlayer?.avatarUrl && (
                      <button
                        type="button"
                        className="btn btn-danger-ghost"
                        disabled={busy === playerCase.id}
                        onClick={() =>
                          act(
                            playerCase.id,
                            () => removeReportedAvatar(playerCase.id),
                            // The wait is no longer one length, so what it
                            // cost them is read from the answer rather than
                            // asserted here (R-AVA-08).
                            (outcome) => {
                              const until = (
                                outcome as { blockedUntil?: string | null } | null
                              )?.blockedUntil;
                              return until
                                ? `Picture removed. They cannot upload another until ${formatWhen(until, dateTime)}.`
                                : "Picture removed. They can upload another one straight away.";
                            },
                          )
                        }
                      >
                        Remove picture
                      </button>
                    )}
                    {playerCase.reportedUserId && (
                      <>
                        <button
                          type="button"
                          className="btn btn-secondary"
                          disabled={busy === playerCase.id}
                          onClick={() =>
                            act(
                              playerCase.id,
                              () =>
                                // One request: the server resolves the report
                                // in the same transaction as the warning.
                                createUserWarning({
                                  userId: playerCase.reportedUserId as string,
                                  reason: note[playerCase.id],
                                  ...(category[playerCase.id]
                                    ? { category: category[playerCase.id] }
                                    : {}),
                                  // So the warned player can be shown what
                                  // the complaint was actually about.
                                  reportId: playerCase.id,
                                }),
                              "Warned, and the report resolved. They will see it the next time they open Sketchy.",
                            )
                          }
                        >
                          Warn player
                        </button>
                        <button
                          type="button"
                          className="mod-danger-button"
                          disabled={busy === playerCase.id}
                          onClick={() =>
                            act(
                              playerCase.id,
                              () => {
                                const expiresAt = suspensionExpiry(
                                  duration[playerCase.id] ?? "24h",
                                );
                                // One request: the server resolves the report
                                // in the same transaction as the suspension.
                                return createUserBan({
                                  userId: playerCase.reportedUserId as string,
                                  reason: note[playerCase.id],
                                  ...(category[playerCase.id]
                                    ? { category: category[playerCase.id] }
                                    : {}),
                                  // So the suspended player can be shown what
                                  // the complaint was actually about.
                                  reportId: playerCase.id,
                                  ...(expiresAt ? { expiresAt } : {}),
                                });
                              },
                              "Suspended, and the report resolved. They are signed out everywhere, and told why if they have a confirmed address.",
                            )
                          }
                        >
                          Suspend…
                        </button>
                        <select
                          aria-label="How long the suspension lasts"
                          className="ops-select"
                          value={duration[playerCase.id] ?? "24h"}
                          onChange={(change) =>
                            setDuration((current) => ({
                              ...current,
                              [playerCase.id]: change.target.value,
                            }))
                          }
                        >
                          {SUSPENSION_DURATIONS.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </>
                    )}
                  </div>
                </>
              ) : (
                <DecisionCard report={playerCase} dateTime={dateTime} />
              )}
            </>
          )}

          {contentCase && (
            <>
              <div className="mod-case-head">
                <div>
                  <SectionLabel>
                    Prompt content · #{contentCase.id.slice(0, 6)}
                  </SectionLabel>
                  <h1>
                    {contentCase.targetType === "prompt"
                      ? `Prompt “${contentCase.prompt}”`
                      : `List “${contentCase.listName}”`}
                  </h1>
                  <p className="mod-case-meta">
                    {contentCase.reporterCount === 1
                      ? "1 reporter"
                      : `${contentCase.reporterCount} reporters`}
                    {` · opened ${formatWhen(contentCase.openedAt, dateTime)}`}
                    {contentCase.reporterCount > 1 &&
                      ` · latest ${formatWhen(contentCase.latestReportedAt, dateTime)}`}
                  </p>
                </div>
                <div className="mod-reason-chips">
                  {contentCase.reasons.map((reason) => (
                    <Chip key={reason} kind="warm">{humanize(reason)}</Chip>
                  ))}
                </div>
              </div>

              <section className="ops-card" aria-label="Reported content">
                <h2>Reported content</h2>
                <blockquote className="mod-evidence">
                  <span>
                    {contentCase.targetType === "prompt" ? (
                      <>
                        Prompt <strong>{contentCase.prompt}</strong> in{" "}
                        {contentCase.listName}
                      </>
                    ) : (
                      <>
                        List <strong>{contentCase.listName}</strong>
                      </>
                    )}
                  </span>
                </blockquote>
                <ContentReportersPanel
                  incident={contentCase}
                  dateTime={dateTime}
                />
              </section>

              {contentCase.status === "pending" ? (
                <>
                  {decisionScope(
                    contentCase,
                    contentCase.targetType === "prompt"
                      ? "this prompt"
                      : "this list",
                  )}
                  {noteField(contentCase.id)}
                  <div className="mod-actions">
                    <button
                      type="button"
                      className="btn btn-success"
                      disabled={busy === contentCase.id}
                      onClick={() =>
                        act(
                          contentCase.id,
                          () =>
                            reviewPromptContentReport(
                              contentCase.id,
                              "dismissed",
                              note[contentCase.id],
                            ),
                          "Dismissed.",
                        )
                      }
                    >
                      Dismiss
                    </button>
                    <button
                      type="button"
                      className="btn btn-secondary"
                      disabled={busy === contentCase.id}
                      onClick={() =>
                        act(
                          contentCase.id,
                          () =>
                            reviewPromptContentReport(
                              contentCase.id,
                              "resolved",
                              note[contentCase.id],
                              "active",
                            ),
                          "Resolved, and left where it is.",
                        )
                      }
                    >
                      Leave it up
                    </button>
                    <button
                      type="button"
                      className="mod-danger-button"
                      disabled={busy === contentCase.id}
                      onClick={() =>
                        act(
                          contentCase.id,
                          () =>
                            reviewPromptContentReport(
                              contentCase.id,
                              "resolved",
                              note[contentCase.id],
                              "hidden",
                            ),
                          "Hidden, and the owner is told if they have a confirmed address.",
                        )
                      }
                    >
                      Hide it
                    </button>
                  </div>
                </>
              ) : (
                <DecisionCard report={contentCase} dateTime={dateTime} />
              )}
            </>
          )}

          {heldCase && heldShown && (
            <>
              <div className="mod-case-head">
                <div>
                  <SectionLabel>Held publication</SectionLabel>
                  <h1>{heldShown.name}</h1>
                  <p className="mod-case-meta">
                    {heldShown.ownerDisplayName ?? "A deleted player"}
                    {` · ${heldRead ? heldRead.prompts.length : heldCase.promptCount} prompts`}
                    {heldShown.publishedAt
                      ? ` · sent ${formatWhen(heldShown.publishedAt, dateTime)}`
                      : ""}
                  </p>
                </div>
                <Chip kind="warning">Waiting</Chip>
              </div>

              {heldShown.description && (
                <p className="mod-held-description">{heldShown.description}</p>
              )}

              <section className="ops-card" aria-label="The prompts">
                <h2>The prompts</h2>
                {/* Nobody complained about this list, so there is no evidence
                    panel and nothing to compare against: the prompts are the
                    whole of what is being decided. */}
                {heldRead ? (
                  <ol className="mod-held-prompts">
                    {heldRead.prompts.map((entry, index) => (
                      <li key={index}>
                        <span className="mod-held-prompt">{entry.prompt}</span>
                        {entry.moderationState !== "active" && (
                          <Chip kind="danger">
                            {humanize(entry.moderationState)}
                          </Chip>
                        )}
                        {entry.aliases.length > 0 && (
                          <span className="mod-held-aliases">
                            also {entry.aliases.join(", ")}
                          </span>
                        )}
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="ops-empty">Reading the list…</p>
                )}
              </section>

              {heldRead && <>
                {/* A decision names the version it was taken on, so an edit
                    made while the list sat here cannot be released unread. */}
                <p className="mod-decision-scope">
                  This decides version {heldRead.version}. If the owner changes
                  the list first, the decision is refused and the list comes
                  back here.
                </p>
                <label className="mod-note">
                  Decision note
                  <textarea
                    placeholder="Why, in one line — required to decide"
                    value={note[heldCase.id] ?? ""}
                    onChange={(change) =>
                      setNote((current) => ({
                        ...current,
                        [heldCase.id]: change.target.value,
                      }))
                    }
                  />
                  <span className="mod-note-hint">
                    Kept in the append-only audit ledger. Hiding tells the owner
                    if they have a confirmed address.
                  </span>
                </label>
                <div className="mod-actions">
                  <button
                    type="button"
                    className="btn btn-success"
                    disabled={busy === heldCase.id}
                    onClick={() =>
                      act(
                        heldCase.id,
                        decideHeld(heldCase.id, heldRead.version, "active"),
                        "Released into the community catalogue.",
                      )
                    }
                  >
                    Release
                  </button>
                  <button
                    type="button"
                    className="mod-danger-button"
                    disabled={busy === heldCase.id}
                    onClick={() =>
                      act(
                        heldCase.id,
                        decideHeld(heldCase.id, heldRead.version, "hidden"),
                        "Hidden, and the owner is told if they have a confirmed address.",
                      )
                    }
                  >
                    Hide it
                  </button>
                </div>
              </>}
            </>
          )}

          {banCase && (
            <>
              <div className="mod-case-head">
                <div>
                  <SectionLabel>Suspension · #{banCase.id.slice(0, 6)}</SectionLabel>
                  <h1>{banCase.displayName ?? "Deleted player"}</h1>
                  <p className="mod-case-meta">
                    {banCase.isActive
                      ? banCase.expiresAt
                        ? `In force until ${formatWhen(banCase.expiresAt, dateTime)}`
                        : "In force, with no end date"
                      : banCase.revokedAt
                        ? `Lifted ${formatWhen(banCase.revokedAt, dateTime)}`
                        : "Expired"}
                  </p>
                </div>
                <Chip kind={banCase.isActive ? "danger" : "neutral"}>
                  {banCase.isActive ? "In force" : "Over"}
                </Chip>
              </div>

              <section className="ops-card" aria-label="Suspension reason">
                <h2>Why</h2>
                <p className="mod-case-details">{banCase.reason}</p>
                <p className="mod-evidence-caption">
                  Suspended {formatWhen(banCase.createdAt, dateTime)}
                </p>
              </section>

              {banCase.isActive ? (
                <>
                  <label className="mod-note">
                    Reason for lifting
                    <textarea
                      placeholder="Why, in one line — required to decide"
                      value={note[banCase.id] ?? ""}
                      onChange={(change) =>
                        setNote((current) => ({
                          ...current,
                          [banCase.id]: change.target.value,
                        }))
                      }
                    />
                    <span className="mod-note-hint">
                      Kept in the append-only audit ledger.
                    </span>
                  </label>
                  <div className="mod-actions">
                    <button
                      type="button"
                      className="mod-danger-button"
                      disabled={busy === banCase.id}
                      onClick={() =>
                        act(
                          banCase.id,
                          () => revokeUserBan(banCase.id, note[banCase.id]),
                          "Lifted. They can sign in again.",
                        )
                      }
                    >
                      Lift suspension
                    </button>
                  </div>
                </>
              ) : (
                banCase.revokeReason && (
                  <p className="mod-resolution">{banCase.revokeReason}</p>
                )
              )}
            </>
          )}

          {!playerCase && !contentCase && !banCase && !heldCase && (
            <p className="ops-empty">Nothing selected. The queue is clear.</p>
          )}
        </div>
      </div>
    </main>
  );
}
