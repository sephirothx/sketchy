import { apiRequest } from "./api";

/**
 * Passkeys, as the staff surfaces use them (R-AUTH-23).
 *
 * A moderator or administrator signs in with one gesture: the authenticator
 * proves it holds the credential and verifies the person holding it, and the
 * credential is bound by the browser to this deployment's origin — so unlike
 * a code from an authenticator app, there is nothing here for somebody on the
 * phone to a moderator to be told, and nothing a lookalike site can obtain.
 *
 * The browser's own WebAuthn objects are `ArrayBuffer`s, and JSON is not, so
 * everything crossing the wire is base64url. The conversions are here rather
 * than in a component because getting one of them wrong fails as "that
 * passkey could not be verified", which is a long way from the mistake.
 */

export interface Passkey {
  id: string;
  label: string;
  createdAt: string;
  lastUsedAt: string | null;
  /** Whether the platform keeps a copy. One that is not backed up is one lost
      device away from needing a recovery code, and can be said so. */
  backedUp: boolean;
}

/** Whether this browser can do WebAuthn at all.
 *
 * Checked before offering anything: a device with no authenticator should be
 * told that up front rather than after a dialog it cannot complete. Sketchy
 * asks for a discoverable credential with user verification, so a browser
 * without conditional-mediation support can still register and sign in — it
 * simply shows its own picker. */
export function passkeysAvailable(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.PublicKeyCredential === "function" &&
    typeof navigator?.credentials?.create === "function"
  );
}

function toBase64Url(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** Backed by a plain `ArrayBuffer` on purpose: WebAuthn's own types want one,
    and a `Uint8Array` over an unspecified buffer is not assignable to it. */
function fromBase64Url(value: string): Uint8Array<ArrayBuffer> {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/");
  const binary = atob(padded.padEnd(Math.ceil(padded.length / 4) * 4, "="));
  const bytes = new Uint8Array(new ArrayBuffer(binary.length));
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

/** The server sends WebAuthn's own JSON shape; the browser wants buffers. */
function decodeCreationOptions(options: Record<string, unknown>): PublicKeyCredentialCreationOptions {
  const user = options.user as { id: string; name: string; displayName: string };
  const exclude = (options.excludeCredentials ?? []) as { id: string; type: string }[];
  return {
    ...(options as unknown as PublicKeyCredentialCreationOptions),
    challenge: fromBase64Url(options.challenge as string),
    user: { ...user, id: fromBase64Url(user.id) },
    excludeCredentials: exclude.map((credential) => ({
      ...credential,
      id: fromBase64Url(credential.id),
      type: "public-key" as const,
    })),
  };
}

function decodeRequestOptions(options: Record<string, unknown>): PublicKeyCredentialRequestOptions {
  const allow = (options.allowCredentials ?? []) as { id: string; type: string }[];
  return {
    ...(options as unknown as PublicKeyCredentialRequestOptions),
    challenge: fromBase64Url(options.challenge as string),
    allowCredentials: allow.map((credential) => ({
      ...credential,
      id: fromBase64Url(credential.id),
      type: "public-key" as const,
    })),
  };
}

function encodeRegistration(credential: PublicKeyCredential): unknown {
  const response = credential.response as AuthenticatorAttestationResponse;
  return {
    id: credential.id,
    rawId: toBase64Url(credential.rawId),
    type: credential.type,
    response: {
      clientDataJSON: toBase64Url(response.clientDataJSON),
      attestationObject: toBase64Url(response.attestationObject),
      transports: response.getTransports?.() ?? [],
    },
    clientExtensionResults: credential.getClientExtensionResults(),
  };
}

function encodeAssertion(credential: PublicKeyCredential): unknown {
  const response = credential.response as AuthenticatorAssertionResponse;
  return {
    id: credential.id,
    rawId: toBase64Url(credential.rawId),
    type: credential.type,
    response: {
      clientDataJSON: toBase64Url(response.clientDataJSON),
      authenticatorData: toBase64Url(response.authenticatorData),
      signature: toBase64Url(response.signature),
      userHandle: response.userHandle ? toBase64Url(response.userHandle) : null,
    },
    clientExtensionResults: credential.getClientExtensionResults(),
  };
}

export function fetchPasskeys(): Promise<{ passkeys: Passkey[]; canHold: boolean }> {
  return apiRequest("/api/auth/passkeys");
}

/**
 * Make a credential and hand its public key over.
 *
 * The password goes with it for the reason R-AUTH-20 gives about an
 * authenticator app: the ceremony says a device is present, the password says
 * whose account it is being bound to. `roleGranted` names a role that was
 * waiting on exactly this and has just begun.
 */
export async function registerPasskey(
  password: string,
): Promise<{ passkey: Passkey; roleGranted: "moderator" | "admin" | null }> {
  const { options } = await apiRequest<{ options: string }>(
    "/api/auth/passkeys/options",
    { method: "POST" },
  );
  const credential = (await navigator.credentials.create({
    publicKey: decodeCreationOptions(JSON.parse(options)),
  })) as PublicKeyCredential | null;
  if (!credential) throw new Error("No passkey was created.");
  return apiRequest("/api/auth/passkeys", {
    method: "POST",
    body: { credential: encodeRegistration(credential), password },
  });
}

/**
 * Sign in, or prove it is still you — one act, and the server decides which
 * from whether this browser already holds a session on the account that
 * signed.
 */
export async function assertPasskey(): Promise<{
  ok: boolean;
  steppedUp: boolean;
  user: { id: string; role: string };
}> {
  const { options } = await apiRequest<{ options: string }>(
    "/api/auth/passkeys/challenge",
    { method: "POST" },
  );
  const credential = (await navigator.credentials.get({
    publicKey: decodeRequestOptions(JSON.parse(options)),
  })) as PublicKeyCredential | null;
  if (!credential) throw new Error("No passkey was used.");
  return apiRequest("/api/auth/passkeys/verify", {
    method: "POST",
    body: { credential: encodeAssertion(credential) },
  });
}

export function forgetPasskey(passkeyId: string, password: string): Promise<{ ok: boolean }> {
  return apiRequest(`/api/auth/passkeys/${passkeyId}`, {
    method: "DELETE",
    body: { password },
  });
}
