import { useNavigate } from "react-router-dom";
import { AppHeader } from "../components/AppHeader";
import {
  BrushIcon,
  FillIcon,
  NotFoundDoodle,
  RectIcon,
  UndoIcon,
} from "../components/icons";

/** What a URL with no page behind it shows.

Reached two ways: the catch-all route in `App.tsx`, and the staff pages when
the account holding them is not staff - the same answer the API gives that
account, rather than confirming the surface exists.

The tool strip is drawn, not wired: spans rather than buttons, and the row is
hidden from assistive technology. Controls that look live and do nothing would
say "this page is broken", which is the one thing a page about a missing page
must not say. */
export function NotFoundPage() {
  const navigate = useNavigate();

  return (
    <div className="not-found-page">
      {/* No back control: the card carries the one way out, and two of
          them side by side is the same offer made twice. */}
      <AppHeader />
      <main className="surface-card not-found-card">
        <div className="not-found-canvas">
          <NotFoundDoodle />
        </div>
        <div className="not-found-tools" aria-hidden="true">
          <span><BrushIcon size={18} /></span>
          <span><FillIcon size={18} /></span>
          <span><RectIcon size={18} /></span>
          <span><UndoIcon size={18} /></span>
        </div>
        <h1>Nobody drew this page</h1>
        <p>That link doesn’t lead anywhere on Sketchy.</p>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => navigate("/")}
        >
          Back to lobby
        </button>
      </main>
    </div>
  );
}
