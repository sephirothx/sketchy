import { apiRequest } from "./api";

/** The supporter pass, as this page talks to it (#1475). Every route here is
absent on a deployment that sells nothing, which is how the page finds out. */

export type SupportProduct = "year" | "lifetime";

export interface SupportPlans {
  year: { price: string };
  lifetime: { price: string };
  maxExtraMinor: number;
  tipUrl: string | null;
}

export interface SupporterStatus {
  active: boolean;
  /** When the last known period ends. Null while inactive and on a lifetime pass. */
  until: string | null;
  renews: boolean;
}

export function fetchSupportPlans(): Promise<SupportPlans> {
  return apiRequest<SupportPlans>("/api/support/plans");
}

export function fetchSupporterStatus(): Promise<SupporterStatus> {
  return apiRequest<SupporterStatus>("/api/support/status");
}

/** Where to send the buyer: the provider's hosted checkout, never a form here. */
export async function startCheckout(product: SupportProduct, extraMinor: number): Promise<string> {
  const { url } = await apiRequest<{ url: string }>("/api/support/checkout", {
    method: "POST",
    body: { product, extraMinor },
  });
  return url;
}

export function cancelRenewal(): Promise<SupporterStatus> {
  return apiRequest<SupporterStatus>("/api/support/cancel", { method: "POST" });
}

export async function requestCancellation(email: string): Promise<void> {
  await apiRequest("/api/support/cancel/request", { method: "POST", body: { email } });
}

export function isLifetime(status: SupporterStatus | null): boolean {
  return Boolean(status?.active && status.until === null);
}

/** An extra as typed, in whole currency, as minor units: 0 for nothing usable. */
export function extraMinorFrom(typed: string, maxExtraMinor: number): number {
  const value = Number(typed.trim().replace(",", "."));
  if (!Number.isFinite(value) || value <= 0) return 0;
  return Math.min(Math.round(value * 100), maxExtraMinor);
}

/** `€5` or `5 €`, as the page's language writes it. */
export function formatEuros(minor: number): string {
  return new Intl.NumberFormat(document.documentElement.lang || undefined, {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  }).format(minor / 100);
}

/** The host a tip link goes to, said beside it because it leaves this site. */
export function tipHost(url: string): string | null {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return null;
  }
}
