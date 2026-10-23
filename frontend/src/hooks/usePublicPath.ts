import { createContext, useContext } from "react";

import type { Locale } from "../content/ui/index.ts";
import { localePath } from "../lib/localePath";

/** The language the address of the page on screen names (#1462), or null.
    Provided by the page table: inside it the router sees the address without
    its prefix, which is how `/de/rules` matches the `/rules` route. */
export const PageLocaleContext = createContext<Locale | null>(null);

/** A public page's address in the language of the page on screen: from
    `/de/rules`, the terms are `/de/terms`; from anywhere else they are
    `/terms`. Links between public pages keep the URL's language so that a
    reader, or a crawler, who arrived in German stays in German. */
export function usePublicPath(): (path: string) => string {
  const locale = useContext(PageLocaleContext);
  return (path) => localePath(path, locale);
}
