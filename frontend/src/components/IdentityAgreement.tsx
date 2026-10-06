import { ui } from "../content/ui/index.ts";
import { fill } from "../content/ui/slots.tsx";
import { MINIMUM_AGE } from "../lib/minimumAge.ts";

/** What starting to play agrees to (#1417, R-RULES-04, R-PRIV-19): the terms,
the minimum age, and that a drawing in a public room is published, with the
privacy notice beside it. Shown under every form that makes a new identity -
the lobby's name tag, an invite link's name field, Settings for somebody with
no name yet - because whichever one a visitor meets first is where they
start. The links open a new tab, so reading them does not lose the name
typed so far. */
export function IdentityAgreement({ className }: { className?: string }) {
  return (
    <p className={className ? `identity-agreement ${className}` : "identity-agreement"}>
      {fill(ui.firstRunIdentity.agreement, {
        terms: (
          <a href="/terms" target="_blank" rel="noreferrer">
            {ui.accountMenu.terms2}
          </a>
        ),
        privacy: (
          <a href="/privacy" target="_blank" rel="noreferrer">
            {ui.accountMenu.privacy2}
          </a>
        ),
        age: MINIMUM_AGE,
      })}
    </p>
  );
}
