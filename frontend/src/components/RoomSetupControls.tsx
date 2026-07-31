function clampInt(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  return Math.min(max, Math.max(min, Math.round(value)));
}

function stepDiscrete(value: number, direction: -1 | 1, options: readonly number[]): number {
  if (direction === 1) {
    return options.find((option) => option > value) ?? options[options.length - 1];
  }
  for (let index = options.length - 1; index >= 0; index -= 1) {
    if (options[index] < value) return options[index];
  }
  return options[0];
}

export function FieldHint({ hint }: { hint: string }) {
  return (
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
  );
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
  const low = options ? options[0] : min;
  const high = options ? options[options.length - 1] : max;
  const atMin = value <= low;
  const atMax = value >= high;

  function commit(raw: number) {
    onChange(clampInt(raw, low, high));
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
            onChange(options ? stepDiscrete(value, -1, options) : clampInt(value - 1, low, high))
          }
        >
          −
        </button>
        <input
          type="number"
          inputMode="numeric"
          min={low}
          max={high}
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
            onChange(options ? stepDiscrete(value, 1, options) : clampInt(value + 1, low, high))
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
  hint?: string;
  showLabel?: boolean;
}

export function SegmentedControl<T extends string>({
  label,
  value,
  options,
  onChange,
  hint,
  showLabel = false,
}: SegmentedControlProps<T>) {
  const selectedIndex = Math.max(0, options.findIndex((option) => option.value === value));

  const control = (
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
  );

  if (!showLabel) {
    return <div className="segmented-control-field">{control}</div>;
  }

  return (
    <div className="segmented-control-field is-labeled">
      <span className="segmented-control-label">
        {label}
        {hint ? <FieldHint hint={hint} /> : null}
      </span>
      {control}
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
        {hint ? <FieldHint hint={hint} /> : null}
      </span>
      <span className="m3-switch-track" aria-hidden="true">
        <span className="m3-switch-thumb" />
      </span>
    </label>
  );
}
