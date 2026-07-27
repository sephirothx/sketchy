import { useEffect, useRef, useState } from "react";
import { playTimerTickSound } from "../lib/sound";

interface TimerProps {
  totalSeconds: number;
  startedAt: number;
}

export function Timer({ totalSeconds, startedAt }: TimerProps) {
  const [remaining, setRemaining] = useState(totalSeconds);
  const prevRemainingRef = useRef<number>(totalSeconds);

  useEffect(() => {
    const compute = () => {
      const elapsed = (Date.now() - startedAt) / 1000;
      const nextVal = Math.max(0, Math.ceil(totalSeconds - elapsed));
      if (nextVal !== prevRemainingRef.current) {
        if (nextVal <= 10 && nextVal > 0) {
          playTimerTickSound();
        }
        prevRemainingRef.current = nextVal;
      }
      setRemaining(nextVal);
    };
    compute();
    const interval = setInterval(compute, 250);
    return () => clearInterval(interval);
  }, [totalSeconds, startedAt]);

  if (totalSeconds <= 0) return null;

  return <div className={`timer${remaining <= 10 ? " urgent" : ""}`}>{remaining}s</div>;
}
