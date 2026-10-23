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

The home, the rules, the legal pages and Solo also get **readable text**
(#1460): the same words the page draws, as plain semantic HTML that the
server puts inside `#root`, in a `<noscript>`. A reader that runs no script -
a crawler, a link checker - parses it as the page, with the site's links; a
browser that runs script never parses it at all, so it costs a player nothing
but its bytes. Hidden markup was tried first and cost the first paint 200 ms
on a slow phone: the browser fetched the body font for the hidden text, and
the download competed with the reader's language. React replaces it either
way when it mounts. The legal
texts' `{contact}` is left for the server, which is the one that knows the
address; `{age}` is filled here.

    node --experimental-strip-types scripts/seo-pages.mjs dist
*/
import { mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { catalogueFor, loadCatalogue, LOCALES } from "../src/content/ui/index.ts";
import { LEGAL_REVISION, legalFor, legalHistoryUrl, MINIMUM_AGE } from "../src/content/legal/index.ts";
import { rulesFor } from "../src/content/rules/index.ts";
import { soloCopyFor } from "../src/content/solo/index.ts";
import { SEO_COPY } from "../src/content/seo/index.ts";
import { documentTitle } from "../src/lib/documentTitle.ts";
import { localePath } from "../src/lib/localePath.ts";

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

/** Text made safe to put between tags or in an attribute. */
export function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

const paragraphs = (texts) => texts.map((text) => `<p>${escapeHtml(text)}</p>`).join("");
const items = (texts) =>
  texts.length ? `<ul>${texts.map((text) => `<li>${escapeHtml(text)}</li>`).join("")}</ul>` : "";
const link = (href, text) => `<a href="${escapeHtml(href)}">${escapeHtml(text)}</a>`;

/** The header's site links and the footer's legal ones, around a page's own
    words: the way a crawler that runs no script finds the rest of the site. */
function framed(ui, legal, main, locale) {
  // Each page's links stay in its language (#1462).
  const to = (path) => localePath(path, locale);
  const nav = [
    ["/", ui.lobbyBrowserPage.lobby],
    ["/solo", ui.solo.solo],
    ["/community-lists", ui.appHeader.communityLink],
    ["/prompt-lists", ui.appHeader.promptStatsLink],
    ["/rules", ui.accountMenu.rules],
  ];
  return (
    '<noscript><div class="prerender">' +
    `<header>${link(to("/"), "Sketchy")}<nav aria-label="${escapeHtml(ui.appHeader.siteNav)}"><ul>` +
    nav.map(([href, text]) => `<li>${link(to(href), text)}</li>`).join("") +
    `</ul></nav></header><main>${main}</main>` +
    `<footer>${link(to("/terms"), legal.terms.title)} · ${link(to("/privacy"), legal.privacy.title)}</footer>` +
    "</div></noscript>"
  );
}

function rulesBody(rules, ui) {
  return (
    `<h1>${escapeHtml(rules.title)}</h1>` +
    `<section><h2>${escapeHtml(rules.introHeading)}</h2>${paragraphs(rules.intro)}</section>` +
    rules.sections
      .map(
        (section) =>
          `<section id="${escapeHtml(section.id)}"><h2>${escapeHtml(section.heading)}</h2>` +
          `<p>${escapeHtml(section.blurb)}</p>` +
          section.rules
            .map(
              (rule) =>
                `<h3 id="${escapeHtml(rule.id)}">${escapeHtml(rule.heading)}</h3>` +
                paragraphs(rule.body) +
                (rule.examples.length ? `<p>${escapeHtml(ui.rulesPage.forExample)}</p>${items(rule.examples)}` : ""),
            )
            .join("") +
          "</section>",
      )
      .join("") +
    `<section id="enforcement"><h2>${escapeHtml(rules.enforcement.heading)}</h2>` +
    `${paragraphs(rules.enforcement.body)}</section>`
  );
}

/** A legal document, `{age}` filled and `{contact}` left for the server,
    under the date it last changed, as `LegalPage` shows it. */
function legalBody(document, ui, locale) {
  const fill = (text) => text.replaceAll("{age}", String(MINIMUM_AGE));
  const date = new Intl.DateTimeFormat(locale, { dateStyle: "long", timeZone: "UTC" }).format(
    new Date(`${LEGAL_REVISION.date}T00:00:00Z`),
  );
  return (
    `<h1>${escapeHtml(document.title)}</h1>` +
    `<p>${escapeHtml(ui.legalPage.lastUpdated({ date }))} · ` +
    `${link(legalHistoryUrl(locale), ui.legalPage.history)}</p>` +
    paragraphs(document.intro.map(fill)) +
    document.sections
      .map(
        (section) =>
          `<section id="${escapeHtml(section.id)}"><h2>${escapeHtml(section.heading)}</h2>` +
          paragraphs(section.body.map(fill)) +
          items((section.items ?? []).map(fill)) +
          "</section>",
      )
      .join("")
  );
}

/** The heads of every public page in every interface language. */
export async function seoPages(lists) {
  const locales = {};
  for (const locale of LOCALES) {
    await loadCatalogue(locale);
    const ui = catalogueFor(locale);
    const seo = SEO_COPY[locale];
    const legal = legalFor(locale);
    const rules = rulesFor(locale);
    const home = documentTitle(null, ui.document.tagline);
    const body = (main) => framed(ui, legal, main, locale);
    const pages = {
      "/": {
        title: home,
        description: seo.home,
        body: body(`<h1>${escapeHtml(home)}</h1><p>${escapeHtml(ui.firstRunIdentity.oneLineExplainer)}</p>`),
      },
      "/rules": { title: documentTitle(rules.title), description: seo.rules, body: body(rulesBody(rules, ui)) },
      "/solo": {
        title: documentTitle(ui.solo.solo),
        description: seo.solo,
        body: body(`<h1>${escapeHtml(ui.solo.solo)}</h1><p>${escapeHtml(soloCopyFor(locale).intro)}</p>`),
      },
      "/terms": { title: documentTitle(legal.terms.title), description: seo.terms, body: body(legalBody(legal.terms, ui, locale)) },
      "/privacy": {
        title: documentTitle(legal.privacy.title),
        description: seo.privacy,
        body: body(legalBody(legal.privacy, ui, locale)),
      },
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
      // What `{contact}` reads where the deployment names no address: the
      // words the page itself shows then.
      contactPending: ui.legalPage.contactPending,
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
