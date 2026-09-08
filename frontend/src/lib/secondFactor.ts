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
  /** Whether a staff role could be granted on this factor as it stands, or
      whether the account's password still has to be proved for it. */
  passwordProved: boolean;
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
 * `password` marks the factor as *proved* to belong to the account's owner,
 * which is what a staff role requires (R-AUTH-20): the code says an
 * authenticator produced it, the password says whose account it is being
 * bound to. Giving it is also what takes up a role that was offered and is
 * waiting on this enrolment — `roleGranted` names the role that just took
 * effect, and with it every session on the account has ended.
 *
 * Optional at this layer because the endpoint accepts an enrolment without
 * one; the form always sends it.
 */
export function confirmEnrolment(
  secret: string,
  code: string,
  password?: string,
): Promise<{
  ok: boolean;
  recoveryCodes: string[];
  roleGranted: "moderator" | "admin" | null;
}> {
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

/**
 * Record that this factor is the account owner's — what a staff role needs
 * and setting one up deliberately does not ask for.
 *
 * Both halves are the point: the password says the owner is here, the code
 * says they hold the authenticator that is enrolled.
 */
export function confirmSecondFactorOwner(
  password: string,
  code: string,
): Promise<{ ok: boolean; roleGranted: "moderator" | "admin" | null }> {
  return apiRequest("/api/auth/second-factor/confirm-owner", {
    method: "POST",
    body: { password, code },
  });
}

/** Prove the second factor again, opening the window for staff actions. */
export function stepUp(code: string): Promise<{ ok: boolean; expiresInSeconds: number }> {
  return apiRequest("/api/auth/step-up", { method: "POST", body: { code } });
}
