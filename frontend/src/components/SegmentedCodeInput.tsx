import { useEffect, useId, useRef } from "react";
import { ui } from "../content/ui/index.ts";

/**
 * Six boxes for a six-digit code, rather than one field to type into.
 *
 * The shape tells you how much is wanted before you start, which one long
 * input never does, and the digits stay legible at a glance while you copy
 * them off a phone. Backspace walks back, arrows move, and a pasted code
 * fills the row however it was formatted — people paste `123 456` and
 * `123-456` as readily as `123456`.
 *
 * `onComplete` carries the value rather than leaving the caller to read
 * state: a form that submits on the last digit would otherwise send whatever
 * React had committed before that keystroke, which is one digit short.
 */
export function SegmentedCodeInput({
  value,
  onChange,
  onComplete,
  length = 6,
  label,
  autoFocus = false,
  disabled = false,
}: {
  value: string;
  onChange: (value: string) => void;
  onComplete?: (value: string) => void;
  length?: number;
  label: string;
  autoFocus?: boolean;
  disabled?: boolean;
}) {
  const groupId = useId();
  const boxes = useRef<(HTMLInputElement | null)[]>([]);
  const digits = value.padEnd(length, " ").slice(0, length).split("");

  useEffect(() => {
    if (autoFocus) boxes.current[0]?.focus();
  }, [autoFocus]);

  function put(next: string) {
    const cleaned = next.replace(/\D/g, "").slice(0, length);
    onChange(cleaned);
    if (cleaned.length === length) onComplete?.(cleaned);
    return cleaned;
  }

  function typeAt(index: number, raw: string) {
    // A whole code arriving in one box is a paste, wherever the caret was.
    if (raw.replace(/\D/g, "").length > 1) {
      const filled = put(raw);
      boxes.current[Math.min(filled.length, length - 1)]?.focus();
      return;
    }
    const digit = raw.replace(/\D/g, "").slice(-1);
    if (!digit) return;
    const next = (value.slice(0, index) + digit + value.slice(index + 1)).slice(0, length);
    put(next);
    boxes.current[Math.min(index + 1, length - 1)]?.focus();
  }

  function keyDown(index: number, event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Backspace") {
      event.preventDefault();
      if (value[index]) {
        put(value.slice(0, index) + value.slice(index + 1));
        return;
      }
      // Empty box: take the one before it, which is what the finger meant.
      put(value.slice(0, Math.max(0, index - 1)));
      boxes.current[Math.max(0, index - 1)]?.focus();
    } else if (event.key === "ArrowLeft") {
      boxes.current[Math.max(0, index - 1)]?.focus();
    } else if (event.key === "ArrowRight") {
      boxes.current[Math.min(length - 1, index + 1)]?.focus();
    }
  }

  return (
    <div className="code-boxes" role="group" aria-labelledby={groupId}>
      <span id={groupId} className="visually-hidden">{label}</span>
      {digits.map((digit, index) => (
        <input
          // Fixed positions in a fixed-length row: the index is the identity.
          key={index}
          ref={(node) => { boxes.current[index] = node; }}
          className="code-box"
          value={digit.trim()}
          onChange={(event) => typeAt(index, event.target.value)}
          onKeyDown={(event) => keyDown(index, event)}
          onFocus={(event) => event.target.select()}
          inputMode="numeric"
          autoComplete={index === 0 ? "one-time-code" : "off"}
          aria-label={ui.segmentedCodeInput.digitPosition({ label, index: index + 1, length })}
          // Deliberately no `maxLength`: the controlled value already keeps a
          // box to one character, and the attribute would truncate a pasted
          // code before the paste path below ever saw it.
          disabled={disabled}
        />
      ))}
    </div>
  );
}
