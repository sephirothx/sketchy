import { apiRequest } from "./api.ts";

export type DataExportStatus = "pending" | "processing" | "ready" | "failed";

/**
 * Why a build failed. `too_large` is the deployment's ceiling on one document
 * (R-PRIV-13): the account is not at fault and the operator can raise it, so
 * the dialog says so rather than "could not prepare".
 */
export type DataExportFailureCode = "generation_failed" | "too_large";

export interface DataExportJob {
  id: string;
  status: DataExportStatus;
  schemaVersion: number;
  createdAt: string;
  startedAt: string | null;
  completedAt: string | null;
  expiresAt: string;
  downloadUrl: string | null;
  failureCode: DataExportFailureCode | string | null;
}

/** The row's one-word state as the dialog shows it. */
export function exportLabel(job: Pick<DataExportJob, "status" | "failureCode">): string {
  if (job.status === "pending") return "Queued";
  if (job.status === "processing") return "Preparing…";
  if (job.status === "ready") return "Ready";
  if (job.failureCode === "too_large") return "Too large to prepare here";
  return "Could not prepare";
}

/** A sentence under a failed row, when the failure is one the player can act on. */
export function exportFailureNote(
  job: Pick<DataExportJob, "status" | "failureCode">,
): string | null {
  if (job.status !== "failed") return null;
  if (job.failureCode === "too_large") {
    return "Your data is larger than this server prepares in one document. Ask the operator to raise the limit.";
  }
  return "Something went wrong while preparing it. You can request another export.";
}

/**
 * How long to wait before asking again while a job is live: every second at
 * first, since most builds finish in one, then every five - a job queued
 * behind another account's build is a wait, not a countdown.
 */
export function pollDelayMs(sinceStartMs: number): number {
  return sinceStartMs < 10_000 ? 1_000 : 5_000;
}

export function requestDataExport(): Promise<DataExportJob> {
  return apiRequest("/api/auth/data-exports", { method: "POST" });
}

/** `nextRequestAt` is when another export may be asked for; null means now. */
export function fetchDataExports(): Promise<{
  exports: DataExportJob[];
  nextRequestAt: string | null;
}> {
  return apiRequest("/api/auth/data-exports");
}

export function deleteAccount(password?: string): Promise<{
  ok: boolean;
  identitiesAnonymized: number;
  sessionsRevoked: number;
}> {
  return apiRequest("/api/auth/account", {
    method: "DELETE",
    body: password ? { password } : {},
  });
}
