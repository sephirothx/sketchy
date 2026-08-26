import { useEffect, useRef, useState } from "react";
import { playTimerTickSound } from "../lib/sound";
import { TimerRing } from "./icons";

interface TimerProps {
  totalSeconds: number;
  startedAt: number;
  /** The phase's full length for ring/bar fractions. sync_game rebases
      totalSeconds to the remaining time, so without this a reconnect shows a
      full ring over a correct countdown. */
  durationSeconds?: number;
  /** Ring for the header, compact text for tight chrome, or the depleting
      bar mobile shows while guessing. */
  variant?: "ring" | "text" | "bar";
  /** Another Timer instance owns the tick sound and announcements. */
  silent?: boolean;
}

/** Green while there is time, amber as it runs down, red for the last 10s. */
function timerColor(remaining: number, totalSeconds: number): string {
  if (remaining <= 10) return "var(--danger)";
  if (totalSeconds > 0 && remaining / totalSeconds <= 0.35) return "var(--warm)";
  return "var(--success)";
}

export function Timer({ totalSeconds, startedAt, durationSeconds, variant = "ring", silent = false }: TimerProps) {
  const [remaining, setRemaining] = useState(totalSeconds);
  const [announcement, setAnnouncement] = useState("");
  const prevRemainingRef = useRef<number>(totalSeconds);

  useEffect(() => {
    const compute = () => {
      const elapsed = (Date.now() - startedAt) / 1000;
      const nextVal = Math.max(0, Math.ceil(totalSeconds - elapsed));
      if (nextVal !== prevRemainingRef.current) {
        if (!silent) {
          if (nextVal <= 10 && nextVal > 0) {
            playTimerTickSound();
          }
          if (prevRemainingRef.current > 10 && nextVal <= 10 && nextVal > 0) {
            setAnnouncement("10 seconds remaining");
          } else if (prevRemainingRef.current > 0 && nextVal === 0) {
            setAnnouncement("Time is up");
          }
        }
        prevRemainingRef.current = nextVal;
      }
      setRemaining(nextVal);
    };
    compute();
    const interval = setInterval(compute, 250);
    return () => clearInterval(interval);
  }, [totalSeconds, startedAt, silent]);

  if (totalSeconds <= 0) return null;

  const duration = durationSeconds && durationSeconds > 0 ? durationSeconds : totalSeconds;
  const urgent = remaining <= 10;
  const color = timerColor(remaining, duration);
  const fraction = duration > 0 ? remaining / duration : 0;

  return (
    <div className={`timer${urgent ? " urgent" : ""}${variant === "bar" ? " timer-bar" : ""}`}>
      {variant === "ring" ? (
        <TimerRing seconds={remaining} fraction={fraction} color={color} size={40} />
      ) : variant === "bar" ? (
        <span className="timer-bar-track" aria-hidden="true">
          <span
            className="timer-bar-fill"
            style={{ width: `${Math.max(0, Math.min(1, fraction)) * 100}%`, background: color }}
          />
        </span>
      ) : (
        <>{remaining}s</>
      )}
      {announcement && (
        <span className="visually-hidden" role="status" aria-live="polite" data-testid="timer-announcer">
          {announcement}
        </span>
      )}
    </div>
  );
}
