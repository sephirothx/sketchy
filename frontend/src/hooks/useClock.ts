import { useCallback } from "react";
import { formatClock, formatDate, formatDateTime } from "../lib/clock";
import { useSettingsStore } from "../store/settingsStore";

/** The clock formatters bound to this player's time format, reactively. */
export function useClock() {
  const timeFormat = useSettingsStore((state) => state.timeFormat);
  const clock = useCallback((date: Date) => formatClock(date, timeFormat), [timeFormat]);
  const dateTime = useCallback((date: Date) => formatDateTime(date, timeFormat), [timeFormat]);
  return { timeFormat, clock, dateTime, date: formatDate };
}
