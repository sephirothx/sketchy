import { useEffect } from "react";
import { BRAND_TITLE, documentTitle } from "../lib/documentTitle";

/**
 * Name the browser tab after the page on screen: "<page> · Sketchy", or
 * "Sketchy – <tagline>" for `null` (the lobby, which is the site's front
 * door).
 *
 * The caller passes words it read from the catalogue at render time, so a
 * language switch re-renders the page and renames the tab with it. Leaving
 * puts the brand back, so a page that sets nothing never inherits the name of
 * the one before it.
 */
export function useDocumentTitle(page: string | null | undefined, tagline?: string): void {
  useEffect(() => {
    document.title = documentTitle(page, tagline);
    return () => {
      document.title = BRAND_TITLE;
    };
  }, [page, tagline]);
}
