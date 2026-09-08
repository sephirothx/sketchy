import { apiRequest } from "./api";

/**
 * Two-factor authentication, as the account page and the staff surfaces use it.
 *
 * A moderator or administrator cannot sign in without one (R-AUTH-20), and
 * every destructive staff action asks for it again inside a short window
 * (R-AUTH-21). An ordinary player may enrol as well, and most will not.
 */
export interface SecondFactorState {
  enrolled: boolean;
  confirmedAt: string | null;
  recoveryCodesRemaining: number;
  /** Whether this account's role makes it mandatory. */
  required: boolean;
  /** How long a step-up stands before it is asked for again. */
  stepUpWindowSeconds: number;
}

/**
 * The secret is held here, in the page, between the offer and the confirmation
 * — the server stores nothing until a code proves it arrived, so an enrolment
 * somebody abandons leaves no credential behind.
 */
export interface EnrolmentOffer {
  secret: string;
  uri: string;
}

export function fetchSecondFactor(): Promise<SecondFactorState> {
  return apiRequest("/api/auth/second-factor");
}

export function beginEnrolment(): Promise<EnrolmentOffer> {
  return apiRequest("/api/auth/second-factor/enrol", { method: "POST" });
}

/**
 * `password` is required only when this replaces a second factor the account
 * already has: swapping the authenticator out is as good as taking it off, so
 * it asks for the same proof that removing one does.
 */
export function confirmEnrolment(
  secret: string,
  code: string,
  password?: string,
): Promise<{ ok: boolean; recoveryCodes: string[] }> {
  return apiRequest("/api/auth/second-factor/confirm", {
    method: "POST",
    body: password ? { secret, code, password } : { secret, code },
  });
}

export function replaceRecoveryCodes(
  password: string,
): Promise<{ recoveryCodes: string[] }> {
  return apiRequest("/api/auth/second-factor/recovery-codes", {
    method: "POST",
    body: { password },
  });
}

export function removeSecondFactor(password: string): Promise<{ ok: boolean }> {
  return apiRequest("/api/auth/second-factor", {
    method: "DELETE",
    body: { password },
  });
}

/** Prove the second factor again, opening the window for staff actions. */
export function stepUp(code: string): Promise<{ ok: boolean; expiresInSeconds: number }> {
  return apiRequest("/api/auth/step-up", { method: "POST", body: { code } });
}
