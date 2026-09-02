import { sparklinePath, sparklineSummary } from "../../lib/sparkline";

const WIDTH = 120;
const HEIGHT = 28;

/** Sixty minutes of one signal, as a line an operator can read at a glance.

An image with a sentence for a label rather than sixty numbers: what a screen
reader wants from a sparkline is the current value and the worst one. */
export function Sparkline({
  values,
  label,
  format,
  warning = false,
}: {
  values: (number | null)[];
  label: string;
  format: (value: number | null) => string;
  warning?: boolean;
}) {
  const path = sparklinePath(values, WIDTH, HEIGHT);
  const { last, max } = sparklineSummary(values);
  const description =
    last === null
      ? `${label}, last 60 minutes, nothing recorded yet`
      : `${label}, last 60 minutes, now ${format(last)}, peak ${format(max)}`;
  return (
    <svg
      className={`ops-sparkline${warning ? " is-warning" : ""}`}
      role="img"
      aria-label={description}
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      preserveAspectRatio="none"
    >
      {path ? <path d={path} /> : null}
    </svg>
  );
}
