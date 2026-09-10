/** What a refusal says to the player, read out of the catalogue.

Every refusal - a socket acknowledgement or an HTTP response - carries an
enumerated `errorCode` and, where a sentence needs a value, typed `params`.
The server also sends prose in `error`/`detail`, and nothing in this app
renders it: it is there for a log line, for the bug report a player attaches
to a complaint, and for an operator reading a response by hand (R-I18N-01).

The sentences themselves live in the catalogue with every other word the
interface says (`content/ui`), so a locale translates them in the same pass
as the rest and the compiler holds it to the same completeness rule.

`params` carry **values, never fragments** - a count, a limit, a reason slug -
because a server-built noun phrase dropped into a sentence is prose with extra
steps, and it breaks in the first language that inflects. */
import { ui } from "../content/ui/index.ts";
import type { ErrorCode } from "../types.ts";

/** The values a sentence may need. Always plain data, never rendered text. */
export type RefusalParams = Record<string, unknown>;

/** Anything that might be a refusal: an `ApiError`, an acknowledgement, a
    rejected promise. Read defensively - it crosses the wire. */
export type RefusalLike = {
  errorCode?: ErrorCode | string | null;
  params?: RefusalParams | null;
};

/** The code a refusal carries, if it carries one this app knows. */
export function refusalCode(problem: unknown): ErrorCode | null {
  const code = (problem as RefusalLike | null)?.errorCode;
  return typeof code === "string" && code in ui.refusals ? (code as ErrorCode) : null;
}

/** What to show the player for this refusal.

`fallback` covers the two cases a code cannot: a network failure with no
response at all, and a server newer than this bundle. Callers pass the
sentence that fits where they are - "Could not save that preset." - rather
than a generic apology. */
export function refusalText(problem: unknown, fallback: string): string {
  const code = refusalCode(problem);
  if (!code) return fallback;
  const sentence = ui.refusals[code];
  const params = (problem as RefusalLike).params ?? {};
  return typeof sentence === "function" ? sentence(params) : sentence;
}
