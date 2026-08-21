import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { AccountMenu } from "../components/AccountMenu";
import { ApiError, apiRequest } from "../lib/api";
import {
  PROMPT_STATS_SORTS,
  emptyStatsMessage,
  isPromptStatsSort,
  statsRows,
  unratedNote,
} from "../lib/promptStats";
import type {
  PromptListSummary,
  PromptStatsResponse,
  PromptStatsSort,
} from "../types";

export function PromptStatsPage() {
  const params = useParams<{ slug?: string }>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const slug = params.slug ?? "english_standard";
  const requested = searchParams.get("sort") ?? "hardest";
  const sort: PromptStatsSort = isPromptStatsSort(requested) ? requested : "hardest";

  const [list, setList] = useState<PromptListSummary | null>(null);
  const [stats, setStats] = useState<PromptStatsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      setLoading(true);
      setError(null);
      try {
        const [lists, response] = await Promise.all([
          apiRequest<PromptListSummary[]>("/api/prompt-lists"),
          apiRequest<PromptStatsResponse>(
            `/api/prompt-lists/${encodeURIComponent(slug)}/prompt-stats?sort=${sort}&limit=100`,
          ),
        ]);
        if (cancelled) return;
        setList(lists.find((entry) => entry.slug === slug) ?? null);
        setStats(response);
      } catch (err) {
        if (cancelled) return;
        setError(
          err instanceof ApiError && err.status === 404
            ? "There is no prompt list with that name."
            : "Could not load these prompt stats. Please try again.",
        );
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [slug, sort]);

  const rows = stats ? statsRows(stats.prompts) : [];
  const empty = stats
    ? emptyStatsMessage(stats.ratedCount, stats.unratedCount, stats.minRatedGuessers)
    : null;
  const note = stats ? unratedNote(stats.unratedCount, stats.minRatedGuessers) : null;

  return (
    <div className="prompt-stats-page">
      <div className="profile-top-bar">
        <button type="button" className="back-link" onClick={() => navigate("/")}>
          ← Back to lobby
        </button>
        <AccountMenu />
      </div>

      <header className="prompt-stats-header">
        <h1>{list ? list.name : "Prompt stats"}</h1>
        <p className="prompt-stats-intro">
          How these prompts have actually played across every finished game on this
          server.
        </p>
      </header>

      <div className="prompt-stats-controls">
        <label htmlFor="prompt-stats-sort">Sort</label>
        <select
          id="prompt-stats-sort"
          value={sort}
          onChange={(event) => setSearchParams({ sort: event.target.value })}
        >
          {PROMPT_STATS_SORTS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      {loading && <p className="prompt-stats-note">Loading…</p>}
      {error && !loading && <p className="prompt-stats-note is-error">{error}</p>}
      {!loading && !error && empty && <p className="prompt-stats-note">{empty}</p>}

      {!loading && !error && rows.length > 0 && (
        <>
          <div className="prompt-stats-table-scroll">
            <table className="prompt-stats-table">
              <caption>
                {stats?.ratedCount} ranked prompts, {PROMPT_STATS_SORTS.find(
                  (option) => option.value === sort,
                )?.label.toLowerCase()}
              </caption>
              <thead>
                <tr>
                  <th scope="col">Prompt</th>
                  <th scope="col">How it goes</th>
                  <th scope="col">Guessed</th>
                  <th scope="col">Picked</th>
                  <th scope="col">Guessers</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.text}>
                    <th scope="row">{row.text}</th>
                    <td>{row.band}</td>
                    <td>{row.guessedLabel}</td>
                    <td>{row.pickedLabel}</td>
                    <td>{row.totalGuesserCount}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {note && <p className="prompt-stats-note">{note}</p>}
        </>
      )}
    </div>
  );
}
