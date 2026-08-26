import { useEffect, useRef, useState } from "react";
import { playTimerTickSound } from "../lib/sound";
import { TimerRing } from "./icons";

interface TimerProps {
  totalSeconds: number;
  startedAt: number;
  /** Compact text-only rendering for tight mobile chrome. */
  variant?: "ring" | "text";
  /** Another Timer instance owns the tick sound and announcements. */
  silent?: boolean;
}

export function Timer({ totalSeconds, startedAt, variant = "ring", silent = false }: TimerProps) {
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

  const urgent = remaining <= 10;

  return (
    <div className={`timer${urgent ? " urgent" : ""}`}>
      {variant === "ring" ? (
        <TimerRing
          seconds={remaining}
          fraction={totalSeconds > 0 ? remaining / totalSeconds : 0}
          color={urgent ? "var(--danger)" : "var(--warm)"}
          size={40}
        />
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
