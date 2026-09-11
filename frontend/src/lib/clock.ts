import { ui } from "../content/ui/index.ts";
/**
 * How a clock reads to this player (#577).
 *
 * One formatter for every clock and date-time the app shows, so the
 * preference means one thing everywhere: chat timestamps, sign-in dates, the
 * notices, the operator pages. "system" is the device's own convention and
 * the default; the other two override it regardless of locale.
 */
export type TimeFormat = "system" | "12h" | "24h";

export const TIME_FORMATS = ["system", "12h", "24h"] as const;
export const DEFAULT_TIME_FORMAT: TimeFormat = "system";

export function isTimeFormat(value: unknown): value is TimeFormat {
  return TIME_FORMATS.includes(value as TimeFormat);
}

/** Which language's conventions a date reads in.

The two settings do different halves of the same job and neither overrides
the other: the **locale** decides how a date is written - `12 Sep` or
`12. Sept.`, `1,000` or `1.000` - and **Time format** decides the hour
convention on top of it (R-I18N-06). Somebody reading Sketchy in German who
wants a 12-hour clock gets German dates and a 12-hour clock.

Undefined until the locale resolves, which is before the first paint; the
device's own convention is the honest answer for the moment in between. */
let displayLocale: string | undefined;

export function setClockLocale(locale: string | undefined): void {
  displayLocale = locale;
}

function clockOptions(format: TimeFormat): Intl.DateTimeFormatOptions {
  if (format === "12h") return { hour: "numeric", minute: "2-digit", hour12: true };
  // h23 rather than hour12:false, which some engines render midnight as 24:00.
  if (format === "24h") return { hour: "2-digit", minute: "2-digit", hourCycle: "h23" };
  return { hour: "2-digit", minute: "2-digit" };
}

/** Just the time of day: "15:05", "3:05 PM", or whatever the device does. */
export function formatClock(date: Date, format: TimeFormat): string {
  if (Number.isNaN(date.getTime())) return ui.clock.unknown;
  return date.toLocaleTimeString(displayLocale, clockOptions(format));
}

/** Day and time together, for anything that happened on some other day. */
export function formatDateTime(date: Date, format: TimeFormat): string {
  if (Number.isNaN(date.getTime())) return ui.clock.unknown;
  return date.toLocaleString(displayLocale, {
    year: "numeric",
    month: "short",
    day: "numeric",
    ...clockOptions(format),
  });
}

/** A day alone; no clock, so no preference to honour. */
export function formatDate(date: Date): string {
  if (Number.isNaN(date.getTime())) return ui.clock.unknown;
  return date.toLocaleDateString(displayLocale, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}
