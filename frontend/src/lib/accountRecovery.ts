import { apiRequest } from "./api.ts";

/** What an account knows about its own way back in. */
export type EmailState = {
  address: string | null;
  verified: boolean;
  pendingAddress: string | null;
  reminderDue: boolean;
  /** False when the deployment has no SMTP configured, which changes the advice. */
  deliveryConfigured: boolean;
};

export const MAX_EMAIL_LENGTH = 255;

/** The shape a server-side address check will accept, no more.

Deliberately permissive: the authority is the confirmation message, and a
client-side pattern that rejects a real address is worse than one that lets a
typo through to be caught by a link that never arrives. */
export function emailLooksUsable(value: string): boolean {
  const trimmed = value.trim();
  if (!trimmed || trimmed.length > MAX_EMAIL_LENGTH) return false;
  if (/\s/.test(trimmed)) return false;
  const at = trimmed.lastIndexOf("@");
  if (at <= 0 || at === trimmed.length - 1) return false;
  return trimmed.slice(at + 1).includes(".");
}

/**
 * Hide the middle of one segment, keeping its ends so the owner still
 * recognises it. A one-character segment has no middle, so it goes entirely -
 * keeping it would be keeping the whole thing.
 */
const HIDDEN = "\u2022";

function maskSegment(segment: string): string {
  if (segment.length <= 1) return HIDDEN;
  if (segment.length === 2) return `${segment[0]}${HIDDEN}`;
  return `${segment[0]}${HIDDEN.repeat(segment.length - 2)}${segment[segment.length - 1]}`;
}

/**
 * An address as it is shown back to its owner (R-SET-08).
 *
 * Settings is opened in rooms with other people looking at the screen, and
 * the address is the one value on it worth copying down. So it is printed with
 * its middle hidden one dot per letter - `s•••••o@e•••••e.com` - enough to
 * recognise which address it is by shape and length, not enough for somebody
 * reading over a shoulder to write it down. The top-level domain survives
 * because it identifies nobody and makes the shape read as an address.
 *
 * Presentation only. The wire, the confirmation link and any typed correction
 * use the real value; a reveal control shows it in full on request.
 */
export function maskEmail(address: string): string {
  const at = address.lastIndexOf("@");
  if (at <= 0 || at === address.length - 1) return maskSegment(address);
  const local = address.slice(0, at);
  const domain = address.slice(at + 1);
  const dot = domain.indexOf(".");
  if (dot <= 0) return `${maskSegment(local)}@${maskSegment(domain)}`;
  return `${maskSegment(local)}@${maskSegment(domain.slice(0, dot))}${domain.slice(dot)}`;
}

/** What to tell someone about an address they have offered but not confirmed. */
export function recoveryStatusMessage(state: EmailState): string {
  // Masked for the same reason the Settings row is (R-SET-08): this sentence
  // rides a banner across every screen, which is a worse place to print an
  // address in full than a pane somebody deliberately opened.
  if (state.verified && state.address) {
    return `You can recover this account through ${maskEmail(state.address)}.`;
  }
  if (state.pendingAddress) {
    return `Check ${maskEmail(state.pendingAddress)} for a confirmation link. Until you follow it, this account has no way back in.`;
  }
  if (!state.deliveryConfigured) {
    return "This server cannot send email, so a lost password has to be reset by whoever runs it.";
  }
  return "Add an email address so you can get back in if you forget your password.";
}

/** Whether the standing "no way back in" note belongs on screen right now.

A rule rather than a condition buried in the component, because the interesting
part is what it refuses. It is a note about account hygiene: it can wait, and
anything that can wait must not land on top of a game - the room lays itself
out to the viewport rather than flowing beneath a banner, so it covered the
drawing tools. Being in a room suppresses it without counting as having seen
it, so it returns to the lobby rather than being spent. */
export function shouldShowRecoveryReminder({
  registered,
  inRoom,
  dismissed,
  state,
}: {
  registered: boolean;
  inRoom: boolean;
  dismissed: boolean;
  state: EmailState | null;
}): boolean {
  if (!registered || inRoom || dismissed) return false;
  return Boolean(state?.reminderDue);
}

export function readEmailState(): Promise<EmailState> {
  return apiRequest<EmailState>("/api/auth/email");
}

export function setEmailAddress(email: string): Promise<{ pendingAddress: string }> {
  return apiRequest("/api/auth/email", { method: "PUT", body: { email } });
}

export function confirmEmailToken(token: string): Promise<{ address: string }> {
  return apiRequest("/api/auth/email/verify", { method: "POST", body: { token } });
}

export function acknowledgeReminder(): Promise<unknown> {
  return apiRequest("/api/auth/email/reminder-seen", { method: "POST" });
}

export function requestPasswordReset(identifier: string): Promise<{ detail: string }> {
  return apiRequest("/api/auth/password/forgot", {
    method: "POST",
    body: { identifier },
  });
}

/** Whether a reset link still works, asked before the form is offered.

Does not spend the link: the person has not chosen a password yet. */
export function passwordResetLinkIsUsable(token: string): Promise<{ valid: boolean }> {
  return apiRequest("/api/auth/password/reset/check", {
    method: "POST",
    body: { token },
  });
}

export function completePasswordReset(
  token: string,
  password: string,
): Promise<unknown> {
  return apiRequest("/api/auth/password/reset", {
    method: "POST",
    body: { token, password },
  });
}

/**
 * Change the password of the account making the request (R-AUTH-17).
 *
 * Ends the way a reset does: every session is revoked and this one is issued
 * afresh, so the caller stays signed in and every other device is out.
 */
export function changePassword(
  currentPassword: string,
  password: string,
): Promise<{ ok: boolean }> {
  return apiRequest("/api/auth/password/change", {
    method: "POST",
    body: { currentPassword, password },
  });
}
