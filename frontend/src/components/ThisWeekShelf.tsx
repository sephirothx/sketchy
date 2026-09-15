import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { GalleryCard, GalleryViewer } from "./GalleryDrawings";
import { fetchThisWeek, type GalleryEntry } from "../lib/gallery";
import { refusalText } from "../lib/refusals.ts";
import { useAuthStore } from "../store/authStore";
import { ui } from "../content/ui/index.ts";

/**
 * The lobby's **This week** (R-GAL-07): the six most-reacted public drawings
 * of the last seven days, read once when the lobby opens and never polled.
 * Absent for a visitor with no session (R-GAL-02); with a session and an
 * empty week it says so, because an absent shelf and an empty week must not
 * look alike. Opening a drawing reuses the Gallery's viewer.
 */
export function ThisWeekShelf() {
  const navigate = useNavigate();
  const user = useAuthStore((state) => state.user);
  const hasResolved = useAuthStore((state) => state.hasResolved);
  // Keyed by who read it, so signing in or out here re-reads the viewer's
  // own facts rather than showing the last account's picks.
  const reader = user?.id ?? "";
  const [shelf, setShelf] = useState<{ reader: string; entries: GalleryEntry[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openIndex, setOpenIndex] = useState<number | null>(null);

  useEffect(() => {
    if (!hasResolved || !reader) return;
    let cancelled = false;
    void fetchThisWeek()
      .then((fetched) => {
        if (cancelled) return;
        setShelf({ reader, entries: fetched.entries });
        setError(null);
      })
      .catch((loadError) => {
        if (!cancelled) setError(refusalText(loadError, ui.galleryPage.couldNotLoadTheGallery));
      });
    return () => { cancelled = true; };
  }, [hasResolved, reader]);

  if (!hasResolved || !user) return null;
  const entries = shelf?.reader === reader ? shelf.entries : null;

  return (
    <section className="panel lobby-week-panel" data-testid="this-week">
      <div className="lobby-rooms-heading">
        <h2>{ui.galleryPage.thisWeek}</h2>
        <button
          type="button"
          className="lobby-catalogue-link"
          onClick={() => navigate("/gallery")}
        >
          {ui.galleryPage.seeTheGallery}
        </button>
      </div>
      {error ? (
        <p className="lobby-action-error" role="alert">{error}</p>
      ) : entries === null ? (
        <p className="gallery-empty">{ui.galleryPage.loading}</p>
      ) : entries.length === 0 ? (
        <p className="gallery-empty" data-testid="this-week-empty">{ui.galleryPage.nothingThisWeek}</p>
      ) : (
        <ul className="gallery-grid lobby-week-grid" data-testid="this-week-grid">
          {entries.map((entry, index) => (
            <GalleryCard key={entry.turnId} entry={entry} onOpen={() => setOpenIndex(index)} />
          ))}
        </ul>
      )}
      {openIndex !== null && entries && entries.length > 0 && (
        <GalleryViewer
          entries={entries}
          openIndex={openIndex}
          onClose={() => setOpenIndex(null)}
          onReacted={(changed) =>
            setShelf((held) => (held
              ? { ...held, entries: held.entries.map((entry) => (entry.turnId === changed.turnId ? changed : entry)) }
              : held))}
        />
      )}
    </section>
  );
}
