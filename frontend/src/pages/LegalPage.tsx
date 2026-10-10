import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";

import { AppHeader } from "../components/AppHeader";
import { DocumentLinks } from "../components/DocumentLinks";
import { Card, SectionLabel } from "../components/ui/Card";
import { LEGAL_REVISION, legalFor, legalHistoryUrl } from "../content/legal/index.ts";
import { fill } from "../content/ui/slots.tsx";
import { ui } from "../content/ui/index.ts";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { apiRequest } from "../lib/api";
import { MINIMUM_AGE } from "../lib/minimumAge.ts";
import { useSettingsStore } from "../store/settingsStore.ts";
import "../styles/lazy/operator.css";

type Which = "privacy" | "terms";

/** The privacy notice and the terms of use, on one page with a switch
between them (#1417).

Laid out as the rules are - a rail of sections beside the text - because it
is the same kind of document, read the same way: somebody looking for one
answer ("how do I delete this?") and jumping to it. Section ids are English
anchors, so `/privacy#rights` lands in every language.

The operator's contact address is the one thing the text needs from the
server (`GET /api/legal`), shown as a `mailto:` link. Until it arrives the
sentence carries an ellipsis, a failed read says the address could not be
loaded rather than that there is none, and only a server that answers with
no address - never production, which refuses to start without one - says so. */
type Contact =
  | { state: "loading" }
  | { state: "failed" }
  | { state: "loaded"; address: string | null };

/** The revision date in the reader's language, as a calendar date: read in
UTC, so no time zone moves it to the day before. */
function revisionDate(locale: string | null | undefined): string {
  return new Intl.DateTimeFormat(locale ?? undefined, { dateStyle: "long", timeZone: "UTC" }).format(
    new Date(`${LEGAL_REVISION.date}T00:00:00Z`),
  );
}

export function LegalPage({ document: which }: { document: Which }) {
  const { hash } = useLocation();
  const locale = useSettingsStore((state) => state.locale);
  const documents = legalFor(locale);
  const shown = documents[which];
  useDocumentTitle(shown.title);
  const [contact, setContact] = useState<Contact>({ state: "loading" });

  useEffect(() => {
    let live = true;
    apiRequest<{ contactAddress: string | null }>("/api/legal")
      .then((answer) => {
        if (live) setContact({ state: "loaded", address: answer.contactAddress });
      })
      .catch(() => {
        if (live) setContact({ state: "failed" });
      });
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    if (!hash) return;
    // The anchor was not in the document when the URL was opened.
    window.document.getElementById(hash.slice(1))?.scrollIntoView({ block: "start" });
  }, [hash, which]);

  const contactNode =
    contact.state === "loading" ? (
      ui.legalPage.contactLoading
    ) : contact.state === "failed" ? (
      ui.legalPage.contactUnavailable
    ) : contact.address ? (
      <a href={`mailto:${contact.address}`}>{contact.address}</a>
    ) : (
      ui.legalPage.contactPending
    );
  const text = (paragraph: string) => fill(paragraph, { contact: contactNode, age: MINIMUM_AGE });

  return (
    <main className="ops-page rules-page legal-page">
      <AppHeader backLabel={ui.rulesPage.backToLobby} />

      <header className="rules-masthead">
        <h1>{shown.title}</h1>
        {/* When it last changed, and every change before it (#1417): what
            "Changes to this notice" and "Changes to these terms" point to. */}
        <p className="legal-updated">
          {ui.legalPage.lastUpdated({ date: revisionDate(locale) })}
          {" · "}
          <a href={legalHistoryUrl(locale)} target="_blank" rel="noreferrer">
            {ui.legalPage.history}
          </a>
        </p>
      </header>

      <div className="rules-layout">
        <aside className="rules-rail" aria-label={ui.rulesPage.thisPage}>
          <Card className="rules-contents">
            <SectionLabel>{ui.rulesPage.thisPage}</SectionLabel>
            <ol>
              {shown.sections.map((section) => (
                <li key={section.id} className="rules-contents-section">
                  <a href={`#${section.id}`} className="rules-contents-heading-link">
                    {section.heading}
                  </a>
                </li>
              ))}
            </ol>
          </Card>
        </aside>

        <div className="rules-document">
          <Card className="rules-section rules-intro">
            {shown.intro.map((paragraph) => (
              <p key={paragraph}>{text(paragraph)}</p>
            ))}
          </Card>
          {shown.sections.map((section) => (
            <Card key={section.id} id={section.id} className="rules-section">
              <SectionLabel>{section.heading}</SectionLabel>
              {section.body.map((paragraph) => (
                <p key={paragraph}>{text(paragraph)}</p>
              ))}
              {section.items && section.items.length > 0 && (
                <ul className="legal-items">
                  {section.items.map((item) => (
                    <li key={item}>{text(item)}</li>
                  ))}
                </ul>
              )}
            </Card>
          ))}
          <DocumentLinks current={which} />
        </div>
      </div>
    </main>
  );
}
