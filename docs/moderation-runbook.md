# Moderation runbook

What moderators and administrators do with a report, in what order, and what to do
when it is more than a game problem. The mechanics live in [requirements.md](requirements.md)
(R-MOD, R-BAN, R-GAL, R-AVA) and in the README's *Reports and suspensions*. This is the
procedure around them. The parts marked **owner** are the operator's to fill in before
launch: who is on duty, and how fast they answer.

## Roles

- **Moderators** read reports, and decide them: dismiss, warn, suspend, take down a
  picture, hide a drawing from the Gallery, hide a prompt or a list. They are adults
  appointed by the operator, as the terms say (R-ROLE-03).
- **Administrators** do all of that, and the two things that cannot be undone: **erase a
  drawing** for illegal content (R-MOD-22), and act on accounts and the server from
  *Operations*. Nobody can suspend an administrator.
- **The operator** is the contact for authorities and for anybody who writes to the
  contact address (`CONTACT_ADDRESS`, shown in the privacy notice and the terms).

**Owner:** list who is on duty and how to reach each other outside the app.

## Order of work

Read the queue in this order, whatever order it arrives in:

1. **Danger to someone's life or safety**: a threat of violence, or a player saying they
   intend to harm themselves.
2. **Sexual content involving minors**, in any form: a drawing, a message, a name, a
   picture.
3. **Other illegal content**: incitement to violence, terrorist content, a hate crime, a
   real person's private information published.
4. **Harassment** of a player, and anything aimed at one person.
5. **Everything else**: spam, cheating, offensive drawings or names that break the rules
   without breaking the law.

**Owner:** set response targets. A starting point: categories 1 and 2 as soon as anyone
sees them, and within 24 hours at most; the rest within 72 hours.

## The tools, and what each one does

| Tool | Who | Undo | Effect |
|---|---|---|---|
| Dismiss | moderator | — | The report is closed; nothing happens to anybody. |
| Warning | moderator | — | A notice the player must acknowledge before taking a new seat (R-INBOX-04). Kept 12 months. |
| Suspension | moderator | revoke | Ends every session and live seat. A day, a week, a month or no end date. A suspended player can still download or delete their data. |
| Remove picture | moderator | — | The profile picture goes; uploading another is blocked for a while (R-AVA-08). |
| Hide from the Gallery | moderator | release | The drawing leaves the Gallery, This week and every pin. **The players who were in the game keep seeing it** in their history. |
| Hide a prompt or list | moderator | release | Takes it out of play and out of the catalogue (R-LIST-13). |
| **Erase drawing** | administrator | **none** | The drawing goes from every player's history, the Gallery, pins, profiles and a recap still open; its reactions and shares go with it, and the game reads *Removed by moderation*. The copy kept with the report stays, readable by administrators only (R-MOD-22). |

Hiding is for a drawing that should not be public. Erasing is for a drawing **nobody may
keep seeing**: one that is illegal. When in doubt, hide first and ask an administrator.

## Danger to life or safety

- If someone may be in immediate danger, **call the emergency services**: 112 in the EU and
  in Switzerland, or 117 for the Swiss police. Give them what the report shows; do not wait
  for the queue.
- A player who says they will harm themselves is not a rules problem. Do not suspend them
  for saying it. Point the operator to the crisis lines: in Switzerland 143 (Die
  Dargebotene Hand) and 147 for young people (Pro Juventute); elsewhere the national line.
- A player threatening somebody else: suspend, record the category, and tell the operator
  so they can decide on a police report.

## Sexual content involving minors

- **Do not download, screenshot, copy or forward it**, and look at it only as much as
  deciding needs. Keeping, copying or passing it on is itself an offence. The report has
  already kept the copy that is needed.
- **Report it to the police first.** In Switzerland: fedpol or the cantonal police. In an EU
  country: the national police, or that country's hotline listed by INHOPE (inhope.org).
  Note the date, the report id and the turn; describe what it is, but attach nothing.
- **Then an administrator erases the drawing** (*Erase drawing* on the case), and the
  account is suspended with no end date.
- The copy kept with the report stays, readable by administrators only, by the operator's
  decision. Give it to the police only when they ask for it, through the operator. Nothing
  in the app deletes that copy yet; if the police say it is no longer needed, the operator
  removes it from the database.

## Other illegal content

Report it to the police where it is a crime. Then: erase it if it is a drawing, hide it if
it is a prompt or list, remove it if it is a picture, and suspend the account. For a
message, suspending the account takes its lines out of the lobby for new arrivals; taking
single lines out of every open lobby is #1435.

## Harassment and everything else

Decide against the [Rules](../frontend/src/content/rules/en.ts): a warning for a first
offence that is not serious, a suspension for a repeat or a serious one. Record the
category whenever you can (R-MOD-19); the player is shown it with the rule it links to.

## Records

- Every decision is in the audit log with who made it. The note you write is for other
  staff and the log, and **is never shown to the player**. Write what you saw and why you
  decided, in plain words.
- A report's evidence (the cited lines and the drawing copy) is kept with the report. Do
  not copy it anywhere else: not into a chat, not into a ticket, not onto your own device.
- Requests from authorities go to the operator. Do not answer one yourself, and do not
  confirm or deny anything about an account to somebody who writes in.

## Looking after yourself

Some of what reaches the queue is distressing. Step away when you need to, hand a case to
somebody else, and do not review the worst categories alone for long stretches.
**Owner:** say who moderators can talk to.
