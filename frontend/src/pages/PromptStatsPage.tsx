import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { AccountMenu } from "../components/AccountMenu";
import { ApiError, apiRequest } from "../lib/api";
import {
  PROMPT_STATS_SORTS,
  coverageNote,
  isPromptStatsSort,
  matchingPrompts,
  searchNote,
  statsRows,
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

  const [lists, setLists] = useState<PromptListSummary[]>([]);
  const [stats, setStats] = useState<PromptStatsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");

  // No slug in the path means "whichever list comes first", which is only
  // knowable once the lists have loaded - so the table waits rather than
  // guessing at a name.
  const [firstSlug, setFirstSlug] = useState<string | null>(null);
  const slug = params.slug ?? firstSlug;

  const requested = searchParams.get("sort") ?? "hardest";
  const sort: PromptStatsSort = isPromptStatsSort(requested) ? requested : "hardest";

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const loaded = await apiRequest<PromptListSummary[]>("/api/prompt-lists");
        if (cancelled) return;
        setLists(loaded);
        setFirstSlug(loaded[0]?.slug ?? null);
        if (loaded.length === 0) setLoading(false);
      } catch {
        if (!cancelled) {
          setError("Could not load the prompt lists. Please try again.");
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!slug) return;
    let cancelled = false;
    void (async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await apiRequest<PromptStatsResponse>(
          `/api/prompt-lists/${encodeURIComponent(slug)}/prompt-stats?sort=${sort}`,
        );
        if (cancelled) return;
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

  const list = lists.find((entry) => entry.slug === slug) ?? null;
  const matches = stats ? matchingPrompts(stats.prompts, query) : [];
  const rows = statsRows(matches);
  const coverage = stats
    ? coverageNote(stats.ratedCount, stats.unratedCount, stats.minRatedGuessers)
    : null;
  const found = stats ? searchNote(query, matches.length) : null;

  function chooseList(nextSlug: string) {
    setQuery("");
    navigate(`/prompt-lists/${nextSlug}?sort=${sort}`);
  }

  return (
    <div className="prompt-stats-page">
      <div className="profile-top-bar">
        <button type="button" className="back-link" onClick={() => navigate("/")}>
          ← Back to lobby
        </button>
        <AccountMenu />
      </div>

      <header className="prompt-stats-header">
        <h1>Prompt stats</h1>
        <p className="prompt-stats-intro">
          Every prompt in the list, and how it has actually played across finished
          games on this server.
        </p>
      </header>

      <div className="prompt-stats-controls">
        {lists.length > 1 && (
          <div className="prompt-stats-control">
            <label htmlFor="prompt-stats-list">Prompt list</label>
            <select
              id="prompt-stats-list"
              value={slug ?? ""}
              onChange={(event) => chooseList(event.target.value)}
            >
              {lists.map((entry) => (
                <option key={entry.slug} value={entry.slug}>
                  {entry.name} ({entry.promptCount})
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="prompt-stats-control">
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
        <div className="prompt-stats-control prompt-stats-search">
          <label htmlFor="prompt-stats-search">Find a prompt</label>
          <input
            id="prompt-stats-search"
            type="search"
            value={query}
            placeholder="roller coaster"
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
      </div>

      {loading && <p className="prompt-stats-note">Loading…</p>}
      {error && !loading && <p className="prompt-stats-note is-error">{error}</p>}
      {!loading && !error && coverage && (
        <p className="prompt-stats-note">{coverage}</p>
      )}
      {!loading && !error && found && <p className="prompt-stats-note">{found}</p>}

      {!loading && !error && rows.length > 0 && (
        <div className="prompt-stats-table-scroll">
          <table className="prompt-stats-table">
            <caption>
              {list ? `${list.name}, ` : ""}
              {PROMPT_STATS_SORTS.find((option) => option.value === sort)
                ?.label.toLowerCase()}
            </caption>
            <thead>
              <tr>
                <th scope="col">Prompt</th>
                <th scope="col">How it goes</th>
                <th scope="col">Guessed</th>
                <th scope="col">Picked</th>
                <th scope="col">Drawn</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.text} className={row.isRated ? "" : "is-unrated"}>
                  <th scope="row">{row.text}</th>
                  <td>{row.band}</td>
                  <td>{row.guessedLabel}</td>
                  <td>{row.pickedLabel}</td>
                  <td>{row.drawnLabel}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
