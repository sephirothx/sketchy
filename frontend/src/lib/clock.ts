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

// One formatter per kind, locale and time format (#991). A `toLocale*String`
// call builds a new `Intl.DateTimeFormat` every time - resolving the locale,
// the calendar and the pattern afresh - and a lobby chat of 200 lines called
// two per line on every render, so a keystroke there cost ~400 of them. The
// cache is keyed on everything the output depends on, so a change of
// language or of Time format simply reaches for a different entry.
const formatters = new Map<string, Intl.DateTimeFormat>();

function formatterFor(kind: string, options: Intl.DateTimeFormatOptions, format = ""): Intl.DateTimeFormat {
  // The time zone too: a formatter keeps the one it was built in, where the
  // `toLocale*String` calls it replaced read the current one every time - a
  // laptop that wakes up somewhere else would keep the old clock.
  const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const key = `${kind}|${displayLocale ?? ""}|${format}|${timeZone}`;
  let formatter = formatters.get(key);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat(displayLocale, options);
    formatters.set(key, formatter);
  }
  return formatter;
}

/** Just the time of day: "15:05", "3:05 PM", or whatever the device does. */
export function formatClock(date: Date, format: TimeFormat): string {
  if (Number.isNaN(date.getTime())) return ui.clock.unknown;
  return formatterFor("clock", clockOptions(format), format).format(date);
}

/** Day and time together, for anything that happened on some other day. */
export function formatDateTime(date: Date, format: TimeFormat): string {
  if (Number.isNaN(date.getTime())) return ui.clock.unknown;
  return formatterFor("dateTime", {
    year: "numeric",
    month: "short",
    day: "numeric",
    ...clockOptions(format),
  }, format).format(date);
}

/** A day alone; no clock, so no preference to honour. */
export function formatDate(date: Date): string {
  if (Number.isNaN(date.getTime())) return ui.clock.unknown;
  return formatterFor("date", {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(date);
}
