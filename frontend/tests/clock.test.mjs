import assert from "node:assert/strict";
import test from "node:test";

import { formatClock, formatDate, formatDateTime, isTimeFormat, setClockLocale } from "../src/lib/clock.ts";

const afternoon = new Date(2026, 8, 3, 15, 5);
const justAfterMidnight = new Date(2026, 8, 3, 0, 7);

test("a 24-hour clock is two digits with no meridiem, midnight included", () => {
  assert.equal(formatClock(afternoon, "24h"), "15:05");
  assert.equal(formatClock(justAfterMidnight, "24h"), "00:07");
});

test("a 12-hour clock carries a meridiem and drops the leading zero", () => {
  assert.match(formatClock(afternoon, "12h"), /^3:05\s?PM$/i);
  assert.match(formatClock(justAfterMidnight, "12h"), /^12:07\s?AM$/i);
});

test("system leaves the choice to the device, and still reads as a clock", () => {
  assert.match(formatClock(afternoon, "system"), /\d{1,2}:\d{2}/);
});

test("a date-time honours the same clock beside the day", () => {
  const stamped = formatDateTime(afternoon, "24h");
  assert.match(stamped, /2026/);
  assert.match(stamped, /15:05/);
  assert.match(formatDateTime(afternoon, "12h"), /3:05\s?PM/i);
  assert.doesNotMatch(formatDate(afternoon), /\d{1,2}:\d{2}/, "a day alone has no clock");
});

test("an unreadable instant says so rather than printing Invalid Date", () => {
  const broken = new Date("not a date");
  assert.equal(formatClock(broken, "24h"), "Unknown");
  assert.equal(formatDateTime(broken, "system"), "Unknown");
  assert.equal(formatDate(broken), "Unknown");
});

test("only the three known formats are accepted from storage", () => {
  assert.equal(isTimeFormat("24h"), true);
  assert.equal(isTimeFormat("system"), true);
  assert.equal(isTimeFormat("13h"), false);
  assert.equal(isTimeFormat(null), false);
});

test("the cached formatters write exactly what toLocale*String did (#991)", () => {
  const moment = new Date(Date.UTC(2026, 8, 22, 21, 5, 0));
  const clockOptions = {
    system: { hour: "2-digit", minute: "2-digit" },
    "12h": { hour: "numeric", minute: "2-digit", hour12: true },
    "24h": { hour: "2-digit", minute: "2-digit", hourCycle: "h23" },
  };
  for (const locale of ["en", "de", "it", "pt"]) {
    setClockLocale(locale);
    for (const format of ["system", "12h", "24h"]) {
      assert.equal(formatClock(moment, format), moment.toLocaleTimeString(locale, clockOptions[format]));
      assert.equal(
        formatDateTime(moment, format),
        moment.toLocaleString(locale, { year: "numeric", month: "short", day: "numeric", ...clockOptions[format] }),
      );
    }
    assert.equal(formatDate(moment), moment.toLocaleDateString(locale, { year: "numeric", month: "short", day: "numeric" }));
  }
  setClockLocale(undefined);
});
