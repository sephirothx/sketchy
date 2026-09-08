/**
 * The recovery codes as something a person can keep.
 *
 * They are shown once and stored only as hashes, so the moment they are on
 * screen is the only moment they can be saved — and "write these ten down"
 * is a worse instruction than a file. Built here rather than in the dialog so
 * the wording and the filename are testable without a browser.
 */
export function recoveryCodeFileName(username: string, now = new Date()): string {
  const date = [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, "0"),
    String(now.getDate()).padStart(2, "0"),
  ].join("-");
  const who = username.trim().toLowerCase().replace(/[^a-z0-9_-]/g, "") || "account";
  return `sketchy-recovery-codes-${who}-${date}.txt`;
}

export function recoveryCodeFileBody(
  username: string,
  codes: string[],
  now = new Date(),
): string {
  return [
    "Sketchy recovery codes",
    `Account: ${username}`,
    `Created: ${now.toISOString().slice(0, 10)}`,
    "",
    "Each code signs you in once if you lose your authenticator app.",
    "Keep this file somewhere only you can reach. Anyone holding these",
    "codes and your password can sign in as you.",
    "",
    ...codes.map((code) => `  ${code}`),
    "",
  ].join("\n");
}

/** Hand the file to the browser. Nothing is uploaded; this never leaves it. */
export function downloadRecoveryCodes(username: string, codes: string[]): void {
  const blob = new Blob([recoveryCodeFileBody(username, codes)], {
    type: "text/plain;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = recoveryCodeFileName(username);
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
