import { useEffect, useState } from "react";
import { useClock } from "../hooks/useClock";
import { SettingsRow } from "./SettingsRow";
import {
  exportFailureNote,
  exportLabel,
  fetchDataExports,
  pollDelayMs,
  requestDataExport,
  type DataExportJob,
} from "../lib/accountData";
import { refusalText } from "../lib/refusals.ts";
import { ui } from "../content/ui/index.ts";
import { DownloadIcon } from "./icons";

/**
 * Settings → Account → Your data → Download everything: requesting a copy of
 * everything Sketchy holds about you (R-PRIV-01), and the copies already made.
 *
 * One a week (R-PRIV-12): building one walks every game the account played,
 * so the button is off until the next is allowed rather than offering a
 * request the server will refuse, and the note under the list says when.
 * In the page rather than a dialog of its own (#864): the request and the
 * download are the same row, and a ready export is worth seeing without
 * opening anything.
 */
export function DataExports({ isGuest }: { isGuest: boolean }) {
  const { dateTime, date } = useClock();
  const [exports, setExports] = useState<DataExportJob[]>([]);
  const [nextRequestAt, setNextRequestAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [requesting, setRequesting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void fetchDataExports()
      .then((result) => {
        if (!active) return;
        setExports(result.exports);
        setNextRequestAt(result.nextRequestAt);
      })
      .catch((failure) => {
        if (active) {
          setError(refusalText(failure, ui.dataExports.couldNotLoadYourDataExports));
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, []);

  const hasWork = exports.some((job) => job.status === "pending" || job.status === "processing");
  useEffect(() => {
    if (!hasWork) return;
    // One build at a time on the server, so a queued job can sit behind
    // another account's: poll briskly while that is unlikely, then settle.
    const startedAt = Date.now();
    let timer = 0;
    let active = true;
    const tick = () => {
      void fetchDataExports()
        .then((result) => {
          if (!active) return;
          setExports(result.exports);
          setNextRequestAt(result.nextRequestAt);
        })
        .catch(() => {})
        .finally(() => {
          if (active) timer = window.setTimeout(tick, pollDelayMs(Date.now() - startedAt));
        });
    };
    timer = window.setTimeout(tick, pollDelayMs(0));
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [hasWork]);

  async function startExport() {
    setRequesting(true);
    setError(null);
    try {
      const job = await requestDataExport();
      setExports((items) => [job, ...items.filter((item) => item.id !== job.id)]);
      const refreshed = await fetchDataExports().catch(() => null);
      if (refreshed) setNextRequestAt(refreshed.nextRequestAt);
    } catch (failure) {
      setError(refusalText(failure, ui.dataExports.couldNotRequestYourDataExport));
    } finally {
      setRequesting(false);
    }
  }

  // The server sends a date only while one is in the future, and none while
  // a job is merely live - the list already shows that one being prepared.
  const waitUntil = nextRequestAt ? new Date(nextRequestAt) : null;
  const canRequest = !loading && !requesting && !hasWork && !waitUntil;

  return (
    <>
      <SettingsRow
        label={ui.settingsOverlay.downloadEverything}
        hint={isGuest ? ui.settingsOverlay.worksForAGuestToo : ui.settingsOverlay.everyGameListAndSetting}
      >
        <button
          type="button"
          className="btn btn-secondary btn-compact"
          onClick={() => void startExport()}
          disabled={!canRequest}
        >
          <DownloadIcon size={15} />
          {requesting ? ui.dataExports.requesting : ui.dataExports.requestExport}
        </button>
      </SettingsRow>
      {error && <p className="auth-error" role="alert">{error}</p>}
      {exports.length > 0 && (
        <ul className="account-export-list" aria-label={ui.settingsOverlay.downloadEverything}>
          {exports.map((job) => (
            <li key={job.id}>
              <span>
                <strong>{exportLabel(job)}</strong>
                <small>{ui.dataExports.requestedOn({ when: dateTime(new Date(job.createdAt)) })}</small>
                {exportFailureNote(job) && (
                  <small className="account-export-note">{exportFailureNote(job)}</small>
                )}
              </span>
              {job.downloadUrl && (
                <a className="btn btn-primary btn-compact" href={job.downloadUrl} download>
                  {ui.dataExports.download}
                </a>
              )}
            </li>
          ))}
        </ul>
      )}
      {/* Said before the first request too: the limit and the expiry are
          worth knowing before the button is pressed, not only after. */}
      <p className="settings-row-note">
        {ui.dataExports.exportAllowance({ nextAllowed: waitUntil ? date(waitUntil) : null })}
      </p>
    </>
  );
}
