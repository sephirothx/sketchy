/** The header's site links (R-UX-11): which one is where you are, and how
much of the nav the bar has room for.

Pure and free of runtime imports, so `frontend/tests` can reach it without
rendering the header. */

/** The `aria-current` a site link carries on `pathname`.

`"page"` on the page itself. `"true"` on a page nested under it - a Gallery
drawing, a list's Prompt stats, one catalogue list - so the section still
reads as the one you are in, without claiming the link *is* this page.
Nothing anywhere else; the lobby is `/` and nothing is nested under it. */
export function siteLinkCurrent(to: string, pathname: string): "page" | "true" | undefined {
  const path = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
  if (path === to) return "page";
  if (to !== "/" && path.startsWith(`${to}/`)) return "true";
  return undefined;
}

/** How the header's site links are drawn: named, as icons, or not at all. */
export type SiteNavMode = "labels" | "icons" | "hidden";

/** How much more room than it needs a fuller mode must find before the nav
    grows into it. Shrinking happens the moment a mode no longer fits; growing
    waits for this much to spare, so a bar resized back and forth across the
    line - or a width that rounds differently from one layout to the next -
    does not flicker between two modes. */
export const SITE_NAV_SLACK = 8;

/** The fullest mode that fits the room the bar leaves (R-UX-11): the labels,
    else the icons, else nothing. `labels` and `icons` are the widths each
    mode needs, `room` what the bar has left for it, and `current` the mode on
    screen, which a fuller mode needs `SITE_NAV_SLACK` more than its width to
    replace. */
export function siteNavMode(state: {
  room: number;
  labels: number;
  icons: number;
  current: SiteNavMode;
}): SiteNavMode {
  const rank = { hidden: 0, icons: 1, labels: 2 } as const;
  const fits = (mode: "labels" | "icons") => {
    const need = mode === "labels" ? state.labels : state.icons;
    return state.room >= need + (rank[mode] > rank[state.current] ? SITE_NAV_SLACK : 0);
  };
  if (fits("labels")) return "labels";
  if (fits("icons")) return "icons";
  return "hidden";
}
