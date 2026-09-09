import { useEffect } from "react";
import { useLocation } from "react-router-dom";

import { AppHeader } from "../components/AppHeader";
import { rulesFor } from "../content/rules";

/** The rules, on one page.

One page rather than a set, because there are six rules: a contents page over
three short sections would be a click in front of almost nothing. Every rule is
anchored by the category a moderator records against it, so a decision saying
*recorded as spam* links straight to the paragraph that says what spam is
(R-RULES-02).

The anchors are the contract. They are English ids and are never translated -
a link written into a notice has to keep working when the page is read in
another language. */
export function RulesPage() {
  const { hash } = useLocation();
  // The language the rules are read in is the browser's, until the app has a
  // language of its own to ask (there is no i18n yet, so this is English for
  // everybody today and is written to stop being so without changing here).
  const rules = rulesFor(
    typeof navigator === "undefined" ? null : navigator.language,
  );

  useEffect(() => {
    if (!hash) return;
    // The browser cannot scroll to an anchor that was not in the document
    // when the URL was opened, which is every anchor here.
    const target = document.getElementById(hash.slice(1));
    target?.scrollIntoView({ block: "start" });
  }, [hash]);

  return (
    <main className="rules-page">
      <AppHeader backLabel="Back to lobby" />

      <article className="rules-document">
        <h1>{rules.title}</h1>
        {rules.intro.map((paragraph) => (
          <p key={paragraph} className="rules-intro">
            {paragraph}
          </p>
        ))}

        <nav className="rules-contents" aria-label="The rules">
          <ul>
            {rules.sections.flatMap((section) =>
              section.rules.map((rule) => (
                <li key={rule.id}>
                  <a href={`#${rule.id}`}>{rule.heading}</a>
                </li>
              )),
            )}
          </ul>
        </nav>

        {rules.sections.map((section) => (
          <section key={section.id} id={section.id} className="rules-section">
            <h2>{section.heading}</h2>
            <p className="rules-blurb">{section.blurb}</p>
            {section.rules.map((rule) => (
              // The id is the category a decision records, which is what
              // makes a notice's link land here.
              <section key={rule.id} id={rule.id} className="rules-rule">
                <h3>{rule.heading}</h3>
                {rule.body.map((paragraph) => (
                  <p key={paragraph}>{paragraph}</p>
                ))}
                {rule.examples.length > 0 && (
                  <>
                    <p className="rules-examples-label">For example:</p>
                    <ul className="rules-examples">
                      {rule.examples.map((example) => (
                        <li key={example}>{example}</li>
                      ))}
                    </ul>
                  </>
                )}
              </section>
            ))}
          </section>
        ))}

        <section id="enforcement" className="rules-section">
          <h2>{rules.enforcement.heading}</h2>
          {rules.enforcement.body.map((paragraph) => (
            <p key={paragraph}>{paragraph}</p>
          ))}
        </section>
      </article>
    </main>
  );
}
