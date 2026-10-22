/* The words the server writes into each public page it serves (#1459).

Every URL is served one shell, and a crawler that runs no script - and every
link preview - reads only what that shell says. So the build writes, per
interface language, each indexable page's title and description from the
same catalogues the app reads, and the server puts them into the page at
startup (`backend/app/seo_pages.py`), where the deployment's origin is known.

Titles come from `content/ui/` because they are what the tab says, and the app
sets the same words once it runs; a crawler that does run it indexes what the
app leaves, so the two must agree. Descriptions come from `content/seo/`,
which the app never loads.

The official lists are read from `backend/data/prompt_lists/`, the files the
server seeds them from: a list's name in each language and its word count are
facts the build needs to write "English — Standard: 1,038 words to draw" in
that language's own plural. Name lists are expanded here as the server
expands them. The server uses an entry only for a list it
actually serves.

    node --experimental-strip-types scripts/seo-pages.mjs dist
*/
import { mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { catalogueFor, loadCatalogue, LOCALES } from "../src/content/ui/index.ts";
import { legalFor } from "../src/content/legal/index.ts";
import { rulesFor } from "../src/content/rules/index.ts";
import { SEO_COPY } from "../src/content/seo/index.ts";
import { documentTitle } from "../src/lib/documentTitle.ts";

const here = dirname(fileURLToPath(import.meta.url));
export const LIST_DIRECTORY = join(here, "..", "..", "backend", "data", "prompt_lists");

/** The prompt languages, by the names a name list's slugs are built from
    (`PromptLanguage` in `backend/app/domain_values.py`). */
const PROMPT_LANGUAGE_NAMES = {
  en: "english",
  de: "german",
  es: "spanish",
  fr: "french",
  it: "italian",
  nl: "dutch",
  pt: "portuguese",
  pl: "polish",
};

/** One file's lists, as `expand_name_list` (`backend/app/db/name_lists.py`)
    makes them: a **name list** - a file with `languages` and no `language` -
    stands for one list per prompt language, `<language>_<slug>`, named in that
    language where the file has the name and holding every one of its
    prompts. Only the facts a head needs; `tests/e2e/test_seo_pages.py` holds
    every list the server serves to having one. */
export function expandedLists(data) {
  if (!("languages" in data) || "language" in data) {
    return [{ slug: data.slug, name: data.name, language: data.language, count: data.prompts.length }];
  }
  return Object.entries(PROMPT_LANGUAGE_NAMES).map(([language, name]) => ({
    slug: `${name}_${data.slug}`,
    name: data.names?.[language] ?? data.name,
    language,
    count: data.prompts.length,
  }));
}

/** Every official list, as the server seeds it. */
export function bundledLists(directory = LIST_DIRECTORY) {
  return readdirSync(directory)
    .filter((name) => name.endsWith(".json"))
    .sort()
    .flatMap((name) => expandedLists(JSON.parse(readFileSync(join(directory, name), "utf-8"))));
}

/** The heads of every public page in every interface language. */
export async function seoPages(lists) {
  const locales = {};
  for (const locale of LOCALES) {
    await loadCatalogue(locale);
    const ui = catalogueFor(locale);
    const seo = SEO_COPY[locale];
    const legal = legalFor(locale);
    const pages = {
      "/": { title: documentTitle(null, ui.document.tagline), description: seo.home },
      "/rules": { title: documentTitle(rulesFor(locale).title), description: seo.rules },
      "/solo": { title: documentTitle(ui.solo.solo), description: seo.solo },
      "/terms": { title: documentTitle(legal.terms.title), description: seo.terms },
      "/privacy": { title: documentTitle(legal.privacy.title), description: seo.privacy },
    };
    const promptLists = {};
    for (const list of lists) {
      // The list's own name in every interface language: the catalogue has
      // no translations for official lists, so that is what the page shows.
      const facts = { name: list.name, count: list.count };
      promptLists[list.slug] = {
        title: documentTitle(ui.promptStatsPage.listTitle(facts)),
        description: seo.promptList(facts),
      };
    }
    // Where `/prompt-lists` with no list named points (R-STAT-01): the
    // Standard list of the language the page is read in, else English's.
    const standard =
      lists.find((list) => list.language === locale && list.slug.endsWith("_standard")) ??
      lists.find((list) => list.language === "en" && list.slug.endsWith("_standard"));
    locales[locale] = {
      tagline: ui.document.tagline,
      pages,
      promptLists,
      standardList: standard?.slug ?? null,
    };
  }
  return { version: 1, locales };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const out = process.argv[2] ?? "dist";
  const pages = await seoPages(bundledLists());
  mkdirSync(join(out, "seo"), { recursive: true });
  writeFileSync(join(out, "seo", "pages.json"), `${JSON.stringify(pages)}\n`);
}
