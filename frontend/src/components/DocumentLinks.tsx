import { Link } from "react-router-dom";

import { ui } from "../content/ui/index.ts";

type Document = "rules" | "terms" | "privacy";

/** The other two of the documents a player is held to - the rules, the terms
and the privacy notice - as a small row at the foot of each one's page
(#1417). At the foot rather than under the title, by the owner's choice: a
reader arrives for one of them, and the way across is there when they are
done rather than the first thing they see. */
export function DocumentLinks({ current }: { current: Document }) {
  const all: { document: Document; to: string; label: string }[] = [
    { document: "rules", to: "/rules", label: ui.accountMenu.rules },
    { document: "terms", to: "/terms", label: ui.legalPage.terms },
    { document: "privacy", to: "/privacy", label: ui.legalPage.privacy },
  ];
  const others = all.filter((entry) => entry.document !== current);
  return (
    <p className="document-links">
      {others.map((entry, index) => (
        <span key={entry.document}>
          {index > 0 && <span aria-hidden="true"> · </span>}
          <Link to={entry.to}>{entry.label}</Link>
        </span>
      ))}
    </p>
  );
}
