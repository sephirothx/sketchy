/** Which of the header's site links is where you are (R-UX-11).

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
