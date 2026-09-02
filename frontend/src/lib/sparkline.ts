/** One SVG path through a minute series, gaps where a minute has no data.

Kept as a pure function so it can be tested without a DOM: the shape of a
chart is the one thing about it worth asserting on. */
export function sparklinePath(
  values: (number | null)[],
  width = 120,
  height = 28,
  padding = 2,
): string {
  const present = values.filter((value): value is number => value !== null && Number.isFinite(value));
  if (present.length === 0 || values.length === 0) return "";
  const max = Math.max(...present);
  const min = Math.min(0, ...present);
  const span = max - min;
  const innerHeight = height - padding * 2;
  const step = values.length > 1 ? (width - padding * 2) / (values.length - 1) : 0;
  const y = (value: number) =>
    span === 0 ? height / 2 : padding + innerHeight - ((value - min) / span) * innerHeight;
  const segments: string[] = [];
  let open = false;
  values.forEach((value, index) => {
    if (value === null || !Number.isFinite(value)) {
      open = false;
      return;
    }
    const x = padding + index * step;
    const point = `${round(x)} ${round(y(value))}`;
    segments.push(open ? `L${point}` : `M${point}`);
    open = true;
  });
  return segments.join(" ");
}

export function sparklineSummary(values: (number | null)[]): {
  last: number | null;
  max: number | null;
} {
  const present = values.filter((value): value is number => value !== null && Number.isFinite(value));
  let last: number | null = null;
  for (let index = values.length - 1; index >= 0; index -= 1) {
    const value = values[index];
    if (value !== null && Number.isFinite(value)) {
      last = value;
      break;
    }
  }
  return { last, max: present.length === 0 ? null : Math.max(...present) };
}

function round(value: number): string {
  return String(Math.round(value * 10) / 10);
}
