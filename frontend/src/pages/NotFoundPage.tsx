import { useNavigate } from "react-router-dom";
import { AppHeader } from "../components/AppHeader";
import { BrushIcon, FillIcon, RectIcon, UndoIcon } from "../components/icons";
import { NOT_FOUND_PATHS, NOT_FOUND_VIEWBOX } from "../components/notFoundArt";
import { ui } from "../content/ui/index.ts";

/** What a URL with no page behind it shows.

Reached two ways: the catch-all route in `App.tsx`, and the staff pages when
the account holding them is not staff - the same answer the API gives that
account, rather than confirming the surface exists.

The tool strip is drawn, not wired: spans rather than buttons, and the row is
hidden from assistive technology. Controls that look live and do nothing would
say "this page is broken", which is the one thing a page about a missing page
must not say. */
/* The drawing nobody finished, for the not-found page. The geometry is
 * Stefano's Inkscape original, derived into `notFoundArt.ts` by
 * `scripts/brand/derive-assets.mjs` - the same pipeline as the wordmark, so
 * the app and the mockup artboards cannot drift apart.
 *
 * It carries its own colours rather than theme tokens, because it hangs on the
 * canvas sheet and that sheet is white in both themes; the paint is the game's
 * drawing palette, so this is a drawing a player could have made.
 *
 * Decoration, deliberately: the heading says what happened, and an unnamed
 * <svg> that is not aria-hidden is a serious axe violation. */
function NotFoundDoodle() {
  return (
    <svg
      viewBox={NOT_FOUND_VIEWBOX}
      width="100%"
      height="100%"
      aria-hidden="true"
      style={{ display: "block" }}
    >
      {NOT_FOUND_PATHS.map(({ fill, d }) => (
        <path key={d} d={d} fill={fill} />
      ))}
    </svg>
  );
}

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
        <h1>{ui.notFoundPage.nobodyDrewThisPage}</h1>
        <p>{ui.notFoundPage.thatLinkDoesnTLeadAnywhere}</p>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => navigate("/")}
        >
          {ui.notFoundPage.backLobby}
        </button>
      </main>
    </div>
  );
}
