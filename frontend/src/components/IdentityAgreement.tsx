import { Fragment, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { InfoIcon } from "./icons";
import { ui } from "../content/ui/index.ts";
import { MINIMUM_AGE } from "../lib/minimumAge.ts";

/** What starting to play is held to (#1417, R-RULES-04, R-PRIV-19), as one
row of links in fine print: the terms, the privacy notice and the minimum age
- and the rules, under the lobby's name tag, which before a name is the only
way to them. Shown under every form that makes a new identity - the lobby's
name tag, an invite link's name field, Settings for somebody with no name yet
- because whichever one a visitor meets first is where they start.

A row and not a sentence, by the owner's choice: the documents say what
playing accepts, and a paragraph under a name field is a thing to read before
playing. What a public room means for its drawings is said where the room is
chosen, not here. Terms and Privacy open a new tab, so reading them does not
lose the name typed so far. */
export function IdentityAgreement({
  className,
  withRules = false,
}: {
  className?: string;
  withRules?: boolean;
}) {
  const links: ReactNode[] = [
    <a key="terms" href="/terms" target="_blank" rel="noreferrer">
      {ui.firstRunIdentity.terms}
    </a>,
    <a key="privacy" href="/privacy" target="_blank" rel="noreferrer">
      {ui.firstRunIdentity.privacy}
    </a>,
    <span key="age" title={ui.firstRunIdentity.ageTitle({ age: MINIMUM_AGE })}>
      {ui.firstRunIdentity.agePlus({ age: MINIMUM_AGE })}
      <span className="visually-hidden"> — {ui.firstRunIdentity.ageTitle({ age: MINIMUM_AGE })}</span>
    </span>,
  ];
  if (withRules) {
    links.unshift(
      <Link key="rules" to="/rules" className="identity-rules">
        <InfoIcon size={13} />
        {ui.accountMenu.rules}
      </Link>,
    );
  }
  return (
    <p className={className ? `identity-agreement ${className}` : "identity-agreement"}>
      {/* Each item carries the dot before it, unbroken, so a row that wraps
          on a narrow phone never leaves a dot at a line's end. */}
      {links.map((link, index) => (
        <Fragment key={index}>
          {index > 0 && " "}
          <span className="identity-item">
            {index > 0 && <span aria-hidden="true">· </span>}
            {link}
          </span>
        </Fragment>
      ))}
    </p>
  );
}
