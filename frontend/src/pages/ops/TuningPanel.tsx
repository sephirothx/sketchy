import { useCallback, useEffect, useMemo, useState } from "react";

import { Chip } from "../../components/ui/Chip";
import { ApiError } from "../../lib/api";
import {
  changeTunables,
  groupLabel,
  groupTunables,
  readTunables,
  tunableLabel,
  type Tunable,
} from "../../lib/adminControls";

/** Where a value in force came from, said in words rather than a code. */
function origin(
  tunable: Tunable,
): { label: string; kind: "primary" | "neutral" | "warm" } {
  // A row this release will not apply. Said plainly, because the value beside
  // it is the default rather than the stored one, and "stored" alone would
  // read as a panel disagreeing with itself.
  if (tunable.overrideRejected) {
    return { label: "Stored value refused", kind: "warm" };
  }
  if (tunable.source === "stored") return { label: "Changed here", kind: "primary" };
  if (tunable.source === "environment") {
    return { label: tunable.envVar ?? "Environment", kind: "neutral" };
  }
  return { label: "Default", kind: "neutral" };
}

function sameNumber(left: string, right: number): boolean {
  const parsed = Number(left);
  return Number.isFinite(parsed) && parsed === right;
}

export function TuningPanel() {
  const [tunables, setTunables] = useState<Tunable[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const adopt = useCallback((next: Tunable[]) => {
    setTunables(next);
    // Drafts are cleared rather than merged: the server has just told us what
    // is actually in force, and a field still showing what somebody typed
    // over a value the server refused is a field that lies.
    setDrafts({});
  }, []);

  const load = useCallback(() => {
    void readTunables()
      .then((result) => {
        adopt(result.tunables);
        setError(null);
      })
      .catch((failure: unknown) =>
        setError(failure instanceof ApiError ? failure.message : "Could not load settings."),
      );
  }, [adopt]);

  useEffect(load, [load]);

  const pending = useMemo(() => {
    const values: Record<string, number> = {};
    for (const tunable of tunables) {
      const draft = drafts[tunable.name];
      if (draft === undefined || draft.trim() === "") continue;
      if (sameNumber(draft, tunable.value)) continue;
      const parsed = Number(draft);
      if (Number.isFinite(parsed)) values[tunable.name] = parsed;
    }
    return values;
  }, [drafts, tunables]);

  const pendingCount = Object.keys(pending).length;

  function submit(changes: { values?: Record<string, number>; reset?: string[] }) {
    setSaving(true);
    setSaved(null);
    void changeTunables(changes)
      .then((result) => {
        adopt(result.tunables);
        setError(null);
        setSaved("Saved. In force now — no restart needed.");
      })
      .catch((failure: unknown) =>
        setError(
          failure instanceof ApiError ? failure.message : "Could not save settings.",
        ),
      )
      .finally(() => setSaving(false));
  }

  const groups = useMemo(() => groupTunables(tunables), [tunables]);

  return (
    <div className="ops-tuning">
      <div className="ops-tuning-head">
        <p className="ops-card-sub">
          Every value here is bounded by the server and takes effect on the next
          command. Changes survive a restart; resetting one puts it back to what
          this process started with.
        </p>
        <div className="ops-tuning-actions">
          {pendingCount > 0 && (
            <span className="ops-pending" role="status">
              {pendingCount} unsaved
            </span>
          )}
          <button
            type="button"
            className="btn btn-primary btn-compact"
            disabled={pendingCount === 0 || saving}
            onClick={() => submit({ values: pending })}
          >
            Apply changes
          </button>
        </div>
      </div>

      {error && (
        <p className="auth-error" role="alert">
          {error}
        </p>
      )}
      {saved && !error && (
        <p className="ops-saved" role="status">
          {saved}
        </p>
      )}

      {groups.map(([group, items]) => (
        <section className="ops-card" key={group} aria-label={groupLabel(group)}>
          <div className="ops-card-head">
            <h2>{groupLabel(group)}</h2>
            {group === "client" && (
              <Chip kind="primary">Sent to every browser</Chip>
            )}
          </div>
          <ul className="ops-tunable-list">
            {items.map((tunable) => {
              const tag = origin(tunable);
              const draft = drafts[tunable.name] ?? String(tunable.value);
              const changed = !sameNumber(draft, tunable.value);
              const inputId = `tunable-${tunable.name}`;
              return (
                <li className="ops-tunable" key={tunable.name}>
                  <div className="ops-tunable-main">
                    <label htmlFor={inputId}>{tunableLabel(tunable.name)}</label>
                    <p className="ops-tunable-why">{tunable.description}</p>
                    <p className="ops-tunable-bounds">
                      {tunable.minimum}–{tunable.maximum} {tunable.unit} · default{" "}
                      {tunable.default}
                      {tunable.bootValue !== tunable.default && (
                        <> · started at {tunable.bootValue}</>
                      )}
                    </p>
                  </div>
                  <div className="ops-tunable-control">
                    <Chip kind={tag.kind}>{tag.label}</Chip>
                    <input
                      id={inputId}
                      type="number"
                      inputMode="decimal"
                      className={changed ? "is-changed" : undefined}
                      value={draft}
                      min={tunable.minimum}
                      max={tunable.maximum}
                      // Whole numbers step by one; the rest step by anything,
                      // or the browser calls a legal value like 12.5 seconds
                      // invalid and its arrows cannot reach it.
                      step={tunable.integral ? 1 : "any"}
                      aria-describedby={`${inputId}-why`}
                      onChange={(change) =>
                        setDrafts((current) => ({
                          ...current,
                          [tunable.name]: change.target.value,
                        }))
                      }
                    />
                    <span id={`${inputId}-why`} className="visually-hidden">
                      {tunable.description}
                    </span>
                    <button
                      type="button"
                      className="btn btn-ghost btn-compact"
                      disabled={
                        saving
                        || (tunable.source !== "stored" && !tunable.overrideRejected)
                      }
                      onClick={() => submit({ reset: [tunable.name] })}
                    >
                      Reset
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}
