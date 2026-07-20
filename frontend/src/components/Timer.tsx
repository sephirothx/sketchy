import { useEffect, useState } from "react";

interface TimerProps {
  totalSeconds: number;
  startedAt: number;
}

export function Timer({ totalSeconds, startedAt }: TimerProps) {
  const [remaining, setRemaining] = useState(totalSeconds);

  useEffect(() => {
    const compute = () => {
      const elapsed = (Date.now() - startedAt) / 1000;
      setRemaining(Math.max(0, Math.ceil(totalSeconds - elapsed)));
    };
    compute();
    const interval = setInterval(compute, 250);
    return () => clearInterval(interval);
  }, [totalSeconds, startedAt]);

  if (totalSeconds <= 0) return null;

  return <div className={`timer${remaining <= 10 ? " urgent" : ""}`}>{remaining}s</div>;
}
