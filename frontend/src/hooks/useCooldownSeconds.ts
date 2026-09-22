import { useEffect, useState } from "react";

/** Whole seconds left until `until` (a `Date.now()` timestamp), counting down.

Owned by whatever shows the number, rather than by the room around it (#987):
the restart cooldown is 60 s after every vote, and its clock used to live in
`ActiveGameRoom`, which re-rendered the whole room four times a second for
all of it - for a label in a menu that is usually closed. Checked four times
a second so the label turns over on time, but held as whole seconds, so React
skips the three checks in four that change nothing.
*/
export function useCooldownSeconds(until: number): number {
  const secondsLeft = () => Math.max(0, Math.ceil((until - Date.now()) / 1000));
  const [seconds, setSeconds] = useState(secondsLeft);

  useEffect(() => {
    const update = () => {
      const left = Math.max(0, Math.ceil((until - Date.now()) / 1000));
      setSeconds(left);
      if (left === 0) window.clearInterval(interval);
    };
    // The first check runs straight away, from a timer rather than the effect
    // body, so a new `until` is picked up without an extra render pass.
    const first = window.setTimeout(update, 0);
    const interval = window.setInterval(update, 250);
    return () => {
      window.clearTimeout(first);
      window.clearInterval(interval);
    };
  }, [until]);

  return seconds;
}
