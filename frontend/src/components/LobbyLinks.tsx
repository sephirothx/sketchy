import { Link } from "react-router-dom";
import { useAuthStore } from "../store/authStore";
import { linksToGallery } from "../lib/lobbyControls.ts";
import { BarChartIcon, ImageIcon, InfoIcon, StarIcon } from "./icons";
import { ui } from "../content/ui/index.ts";

/**
 * The lobby's own way to the rest of the site: a quiet row of links under the
 * rooms and the people.
 *
 * The Gallery, the Community catalogue, Prompt stats and Rules were reachable
 * only from the identity chip's menu - eleven rows for a registered player -
 * and a visitor who had not chosen a name has no chip, so for them those pages
 * did not exist. This row is the phone's way there (below 901px): from 901px
 * the header carries the same links on every page (`SiteNav` in AppHeader), and
 * CSS hides this one. The menu keeps its entries, Rules included (R-RULES-01).
 *
 * The Gallery only once there is a session: without one it is not a page but a
 * refusal (R-GAL-02), and a link to a refusal is not a way anywhere.
 */
export function LobbyLinks() {
  const hasSession = useAuthStore((state) => linksToGallery(state.user));
  return (
    <nav className="lobby-links" aria-label={ui.lobbyBrowserPage.moreFromSketchy}>
      <ul>
        {hasSession && (
          <li>
            <Link to="/gallery"><ImageIcon size={15} />{ui.galleryPage.gallery}</Link>
          </li>
        )}
        <li>
          <Link to="/community-lists"><StarIcon size={15} />{ui.communityCataloguePage.communityCatalogue}</Link>
        </li>
        <li>
          <Link to="/prompt-lists"><BarChartIcon size={15} />{ui.accountMenu.promptStats}</Link>
        </li>
        <li>
          <Link to="/rules"><InfoIcon size={15} />{ui.accountMenu.rules}</Link>
        </li>
      </ul>
    </nav>
  );
}
