import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";

import { AppHeader } from "../components/AppHeader";
import { Card, SectionLabel } from "../components/ui/Card";
import { rulesFor } from "../content/rules";

/** The rules, on one page.

Laid out the way the moderation queue is - a rail beside the thing it indexes,
collapsing to one column on a narrow screen - because that is the shape this
app already uses for "a list of things, and the one you are reading". Six rules
do not need a page each; they do need somewhere to be found from.

Every rule is anchored by the category a moderator records against it, so a
decision saying *recorded as spam* links straight to the paragraph that says
what spam is (R-RULES-02). The anchors are the contract: English ids, never
translated, because a link written into a notice has to keep working when the
page is read in another language. */
export function RulesPage() {
  const { hash } = useLocation();
  // Seeded from the hash the page was opened at - a notice links straight to
  // a rule - and taken over by the observer below once the reader moves.
  const [reading, setReading] = useState<string | null>(() =>
    typeof window === "undefined" ? null : window.location.hash.slice(1) || null,
  );
  // The language the rules are read in is the browser's, until the app has one
  // of its own to ask (there is no i18n yet, so this is English for everybody
  // today and is written to stop being so without changing here).
  const rules = rulesFor(
    typeof navigator === "undefined" ? null : navigator.language,
  );

  useEffect(() => {
    if (!hash) return;
    // The browser cannot scroll to an anchor that was not in the document when
    // the URL was opened, which is every anchor here.
    const target = document.getElementById(hash.slice(1));
    target?.scrollIntoView({ block: "start" });
  }, [hash]);

  useEffect(() => {
    // Which rule the reader is actually on, so the rail says where they are
    // rather than only where they could go. Cheap enough to watch every rule:
    // there are six.
    const seen = new Map<string, number>();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          seen.set(entry.target.id, entry.intersectionRatio);
        }
        const [best] = [...seen.entries()]
          .filter(([, ratio]) => ratio > 0)
          .sort((a, b) => b[1] - a[1]);
        if (best) setReading(best[0]);
      },
      { rootMargin: "-88px 0px -55% 0px", threshold: [0, 0.25, 1] },
    );
    for (const section of rules.sections) {
      for (const rule of section.rules) {
        const node = document.getElementById(rule.id);
        if (node) observer.observe(node);
      }
    }
    return () => observer.disconnect();
    // The document is a module constant, so this rebuilds only on a language
    // change.
  }, [rules]);

  return (
    <main className="ops-page rules-page">
      <AppHeader backLabel="Back to lobby" />

      <header className="rules-masthead">
        <SectionLabel>Sketchy</SectionLabel>
        <h1>{rules.title}</h1>
      </header>

      <div className="rules-layout">
        <aside className="rules-rail" aria-label="The rules">
          <Card className="rules-contents">
            <SectionLabel>On this page</SectionLabel>
            <ol>
              {rules.sections.map((section) => (
                <li key={section.id} className="rules-contents-section">
                  <span className="rules-contents-heading">{section.heading}</span>
                  <ul>
                    {section.rules.map((rule) => (
                      <li key={rule.id}>
                        <a
                          href={`#${rule.id}`}
                          className={
                            reading === rule.id ? "is-reading" : undefined
                          }
                          aria-current={reading === rule.id ? "true" : undefined}
                        >
                          {rule.heading}
                        </a>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
              <li className="rules-contents-section">
                <a href="#enforcement" className="rules-contents-heading-link">
                  {rules.enforcement.heading}
                </a>
              </li>
            </ol>
          </Card>
        </aside>

        <div className="rules-document">
          {/* A section like the others, in the column rather than across the
              top: a full-width paragraph over a two-column layout left the
              grid starting halfway down the page, and an unlabelled block
              above three labelled ones reads as a different document. */}
          <Card className="rules-section rules-intro">
            <SectionLabel>{rules.introHeading}</SectionLabel>
            {rules.intro.map((paragraph) => (
              <p key={paragraph}>{paragraph}</p>
            ))}
          </Card>

          {rules.sections.map((section) => (
            <Card key={section.id} id={section.id} className="rules-section">
              <SectionLabel>{section.heading}</SectionLabel>
              <p className="rules-blurb">{section.blurb}</p>
              {section.rules.map((rule) => (
                // The id is the category a decision records, which is what
                // makes a notice's link land here.
                <section key={rule.id} id={rule.id} className="rules-rule">
                  <h2>{rule.heading}</h2>
                  {rule.body.map((paragraph) => (
                    <p key={paragraph}>{paragraph}</p>
                  ))}
                  {rule.examples.length > 0 && (
                    <div className="rules-examples">
                      <p className="rules-examples-label">For example</p>
                      <ul>
                        {rule.examples.map((example) => (
                          <li key={example}>{example}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </section>
              ))}
            </Card>
          ))}

          <Card id="enforcement" className="rules-section rules-enforcement">
            <SectionLabel>{rules.enforcement.heading}</SectionLabel>
            {rules.enforcement.body.map((paragraph) => (
              <p key={paragraph}>{paragraph}</p>
            ))}
          </Card>
        </div>
      </div>
    </main>
  );
}
