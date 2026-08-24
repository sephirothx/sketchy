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

/** What to tell someone about an address they have offered but not confirmed. */
export function recoveryStatusMessage(state: EmailState): string {
  if (state.verified && state.address) {
    return `You can recover this account through ${state.address}.`;
  }
  if (state.pendingAddress) {
    return `Check ${state.pendingAddress} for a confirmation link. Until you follow it, this account has no way back in.`;
  }
  if (!state.deliveryConfigured) {
    return "This server cannot send email, so a lost password has to be reset by whoever runs it.";
  }
  return "Add an email address so you can get back in if you forget your password.";
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

export function completePasswordReset(
  token: string,
  password: string,
): Promise<unknown> {
  return apiRequest("/api/auth/password/reset", {
    method: "POST",
    body: { token, password },
  });
}
