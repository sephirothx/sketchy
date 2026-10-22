/** The interface language in a public page's URL (#1462).

A URL ranks in one language, so each public page - the lobby, the rules, the
legal pages, Solo, the official lists - has one URL per interface language:
English unprefixed (`/rules`), every other language under its code
(`/de/rules`). Only those pages: a room, Settings or a profile has one URL
whatever language it is read in, and `/de/room/…` is no page at all.

The URL's language is the first step of R-I18N-06's order **for that page
view** and is not remembered: a German link shared with an English reader
shows that page in German and leaves the rest of their app in English.
`backend/app/client_routes.py` reads the same prefixes. */
import { LOCALES, type Locale } from "../content/ui/index.ts";

// The public pages' routes, as `PUBLIC` in App.tsx draws them: a URL prefix
// is a language only in front of one of these.
const PUBLIC_PATH = /^\/(?:rules|terms|privacy|solo|prompt-lists(?:\/[^/]+)?)?\/?$/i;

export function isPublicPath(path: string): boolean {
  return PUBLIC_PATH.test(path);
}

/** The URL's language, if it has one, and the page's path without it. A
    query or a fragment - an overlay's background carries one - stays on it. */
export function splitLocalePath(pathname: string): { locale: Locale | null; path: string } {
  // Without case, as the router matches the rest.
  const match = /^\/([a-z]{2})(\/[^?#]*)?([?#].*)?$/i.exec(pathname);
  const locale = match?.[1].toLowerCase() as Locale | undefined;
  const path = match?.[2] ?? "/";
  if (locale && locale !== "en" && LOCALES.includes(locale) && isPublicPath(path)) {
    return { locale, path: path + (match?.[3] ?? "") };
  }
  return { locale: null, path: pathname };
}

/** *path* read in *locale*: prefixed when it is a public page and the
    language is not English, as it is otherwise. */
export function localePath(path: string, locale: Locale | null): string {
  if (!locale || locale === "en" || !isPublicPath(path.split(/[?#]/)[0])) return path;
  return `/${locale}${path === "/" ? "" : path}`;
}
