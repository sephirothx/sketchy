import type { AuthUser } from "../store/authStore";
import { apiRequest } from "./api.ts";

/** The supporter pass, as this page talks to it (#1475). Every route here is
absent on a deployment that sells nothing, which is how the page finds out. */

export type SupportProduct = "year" | "lifetime";

export interface SupportPlans {
  year: { price: string };
  lifetime: { price: string };
  gift: { price: string };
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

/** Twelve months for somebody else, one charge, never renewing (#1540). */
export async function startGift(
  recipientId: string,
  anonymous: boolean,
  extraMinor: number,
): Promise<string> {
  const { url } = await apiRequest<{ url: string }>("/api/support/gift", {
    method: "POST",
    body: { recipientId, anonymous, extraMinor },
  });
  return url;
}

/** Go to the provider's checkout. Over a room in play it opens a new tab, because
leaving this page would drop a seat without leaving the room (R-UX-15). Opened
before the wait, or a browser takes it for a popup. */
export async function sendToCheckout(getUrl: () => Promise<string>, seated: boolean): Promise<void> {
  const tab = seated ? window.open("", "_blank") : null;
  try {
    const url = await getUrl();
    if (tab) tab.location.href = url;
    else window.location.assign(url);
  } catch (failure) {
    tab?.close();
    throw failure;
  }
}

export const NAME_STYLES = [
  "sunset",
  "ocean",
  "aurora",
  "ember",
  "berry",
  "meadow",
  "twilight",
  "galaxy",
  "glacier",
  "lagoon",
  "orchid",
  "silver",
] as const;

export function setAccountNameStyle(nameStyle: string | null): Promise<AuthUser> {
  return apiRequest<AuthUser>("/api/auth/name-style", { method: "POST", body: { nameStyle } });
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

/** Whether `typed` may stand in the extra's box: an amount in whole currency
with at most two decimals, either separator, and no more than the cap. Anything
else is refused as it is typed, so the box never holds what cannot be charged. */
export function extraTypedAllowed(typed: string, maxExtraMinor: number): boolean {
  if (!/^\d*(?:[.,]\d{0,2})?$/.test(typed)) return false;
  const value = Number(typed.replace(",", "."));
  return !Number.isFinite(value) || Math.round(value * 100) <= maxExtraMinor;
}

/** Whether the page's language writes the euro sign before the amount. */
export function euroSignFirst(lang: string | undefined): boolean {
  const parts = new Intl.NumberFormat(lang || undefined, { style: "currency", currency: "EUR" }).formatToParts(1);
  return parts.findIndex((part) => part.type === "currency") < parts.findIndex((part) => part.type === "integer");
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
