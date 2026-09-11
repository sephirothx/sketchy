import { ui } from "../content/ui/index.ts";
/**
 * The password floor, kept in one place on this side of the wire.
 *
 * Twelve rather than eight since #468: eight characters of anything a person
 * chooses is within reach of an offline guess against a stolen hash. The
 * server holds the real rule (`backend/app/auth/password.py`) and screens for
 * breached and identity-derived passwords besides; this exists so the form can
 * refuse the obvious case without a round trip, and so the number appears
 * once rather than in every dialog that mentions it.
 */
export const MIN_PASSWORD_LENGTH = 12;

/** What the form says when it refuses a password under the floor - a function,
so it is read in the language in force when it is shown rather than at import. */
export function passwordTooShort(): string {
  return ui.passwordPolicy.tooShort({ count: MIN_PASSWORD_LENGTH });
}
