import type { HintMode, ScoringMode } from "../types";

export const MAX_PLAYERS_MIN = 2;
export const MAX_PLAYERS_MAX = 16;
export const ROUNDS_MIN = 1;
export const ROUNDS_MAX = 10;
export const DRAWING_TIME_OPTIONS = [15, 30, 60, 90, 120, 180, 240, 300] as const;
export const DEFAULT_DRAWING_SECONDS = 90;
export const DEFAULT_HINT_MODE: HintMode = "checkpoints";

export const SCORING_OPTIONS: { value: ScoringMode; label: string }[] = [
  { value: "none", label: "Just for fun" },
  { value: "default", label: "Default" },
];

export const HINT_OPTIONS: { value: HintMode; label: string; description: string }[] = [
  { value: "none", label: "None", description: "No letters are revealed during the round." },
  {
    value: "checkpoints",
    label: "Timed hints",
    description: "Letters are revealed to everyone as the round progresses.",
  },
  {
    value: "purchase",
    label: "Buy letters",
    description: "Players spend points to uncover one letter position, visible only to them.",
  },
  {
    value: "wheel",
    label: "Wheel of Fortune",
    description: "Players spend points to buy a letter and reveal every match for themselves.",
  },
];

function clampInt(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  return Math.min(max, Math.max(min, Math.round(value)));
}

function nearestOption(value: number, options: readonly number[]): number {
  return options.reduce((best, option) =>
    Math.abs(option - value) < Math.abs(best - value) ? option : best,
  );
}

function stepDiscrete(value: number, direction: -1 | 1, options: readonly number[]): number {
  const current = options.includes(value) ? value : nearestOption(value, options);
  const index = options.indexOf(current);
  return options[index + direction] ?? current;
}

interface InputNumberProps {
  label: string;
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  options?: readonly number[];
}

export function InputNumber({
  label,
  value,
  onChange,
  min = 0,
  max = 100,
  options,
}: InputNumberProps) {
  const atMin = options ? value <= options[0] : value <= min;
  const atMax = options ? value >= options[options.length - 1] : value >= max;

  function commit(raw: number) {
    if (options) {
      onChange(nearestOption(clampInt(raw, options[0], options[options.length - 1]), options));
      return;
    }
    onChange(clampInt(raw, min, max));
  }

  return (
    <label className="input-number-field">
      <span>{label}</span>
      <div className="input-number">
        <button
          type="button"
          aria-label={`Decrease ${label}`}
          disabled={atMin}
          onClick={() =>
            onChange(options ? stepDiscrete(value, -1, options) : clampInt(value - 1, min, max))
          }
        >
          −
        </button>
        <input
          type="number"
          inputMode="numeric"
          min={options ? options[0] : min}
          max={options ? options[options.length - 1] : max}
          step={1}
          value={value}
          aria-label={label}
          onChange={(event) => {
            const next = Number(event.currentTarget.value);
            if (Number.isInteger(next)) onChange(next);
          }}
          onBlur={(event) => {
            const parsed = Number(event.currentTarget.value);
            commit(Number.isFinite(parsed) ? parsed : value);
          }}
        />
        <button
          type="button"
          aria-label={`Increase ${label}`}
          disabled={atMax}
          onClick={() =>
            onChange(options ? stepDiscrete(value, 1, options) : clampInt(value + 1, min, max))
          }
        >
          +
        </button>
      </div>
    </label>
  );
}

interface SegmentedControlProps<T extends string> {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}

export function SegmentedControl<T extends string>({
  label,
  value,
  options,
  onChange,
}: SegmentedControlProps<T>) {
  const selectedIndex = Math.max(0, options.findIndex((option) => option.value === value));

  return (
    <div className="segmented-control-field">
      <div
        className="segmented-control"
        role="group"
        aria-label={label}
        style={{
          ["--segment-index" as string]: selectedIndex,
          ["--segment-count" as string]: options.length,
        }}
      >
        <span className="segmented-control-thumb" aria-hidden="true" />
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            aria-pressed={value === option.value}
            onClick={() => onChange(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

interface ChoiceChipsProps<T extends string> {
  label: string;
  value: T;
  options: { value: T; label: string; description?: string; disabled?: boolean }[];
  disabled?: boolean;
  onChange: (value: T) => void;
}

export function ChoiceChips<T extends string>({
  label,
  value,
  options,
  disabled = false,
  onChange,
}: ChoiceChipsProps<T>) {
  const selectedIndex = Math.max(0, options.findIndex((option) => option.value === value));

  return (
    <fieldset className="room-choice-group" disabled={disabled}>
      <legend>{label}</legend>
      <div
        className="segmented-control room-choice-segmented"
        role="group"
        aria-label={label}
        style={{
          ["--segment-index" as string]: selectedIndex,
          ["--segment-count" as string]: options.length,
        }}
      >
        <span className="segmented-control-thumb" aria-hidden="true" />
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            aria-pressed={value === option.value}
            aria-label={
              option.description ? `${label}: ${option.label}. ${option.description}` : undefined
            }
            title={option.description}
            disabled={disabled || option.disabled}
            onClick={() => onChange(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>
    </fieldset>
  );
}

interface SwitchProps {
  label: string;
  hint?: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
}

export function Switch({ label, hint, checked, disabled = false, onChange }: SwitchProps) {
  return (
    <label className={`m3-switch-label${disabled ? " is-disabled" : ""}`}>
      <input
        type="checkbox"
        role="switch"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span className="m3-switch-text">
        {label}
        {hint && (
          <span className="m3-switch-hint-wrap">
            <button
              type="button"
              className="m3-switch-hint"
              aria-label={hint}
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
              }}
            >
              ?
            </button>
            <span className="m3-switch-hint-tooltip" role="tooltip">
              {hint}
            </span>
          </span>
        )}
      </span>
      <span className="m3-switch-track" aria-hidden="true">
        <span className="m3-switch-thumb" />
      </span>
    </label>
  );
}
