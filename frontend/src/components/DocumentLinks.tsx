import { Link } from "react-router-dom";

import { ui } from "../content/ui/index.ts";
import { usePublicPath } from "../hooks/usePublicPath";
import { useEffect } from "react";
import { useSupportStore } from "../store/supportStore";

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
  const publicPath = usePublicPath();
  const hasPlans = useSupportStore((state) => Boolean(state.plans));
  const tipUrl = useSupportStore((state) => state.plans?.tipUrl);
  const loadPlans = useSupportStore((state) => state.loadPlans);
  useEffect(() => {
    void loadPlans();
  }, [loadPlans]);
  return (
    <p className="document-links">
      {others.map((entry, index) => (
        <span key={entry.document}>
          {index > 0 && <span aria-hidden="true"> · </span>}
          <Link to={publicPath(entry.to)}>{entry.label}</Link>
        </span>
      ))}
      {hasPlans && (
        <span>
          <span aria-hidden="true"> · </span>
          <Link to="/support/cancel">{ui.support.cancelRenewal}</Link>
        </span>
      )}
      {tipUrl && (
        <span>
          <span aria-hidden="true"> · </span>
          <a href={tipUrl} target="_blank" rel="noopener noreferrer">
            {ui.support.tipLabel}
          </a>
        </span>
      )}
    </p>
  );
}
