import type { RefObject } from "react";

import { CheckIcon, ChevronDownIcon } from "../icons";
import { usePickerPopup } from "../../hooks/usePickerPopup";
import { ui } from "../../content/ui/index.ts";

export interface PickerOption<V extends string> {
  value: V;
  label: string;
  /** A heading the option is listed under. Options sharing one are given in
      a run, and each run is introduced by its heading: a long list - the
      prompt lists, by language (#1424) - is found by its groups. */
  group?: string;
}

interface PickerProps<V extends string> {
  /** What is being chosen - "Reason", "Sort". The trigger's accessible name
      is this and the choice ("Sort: Hardest first"); the list's is this. */
  label: string;
  options: readonly PickerOption<V>[];
  value: V;
  onChange: (value: V) => void;
  /** The trigger's id, so a visible `<label htmlFor>` reaches it. */
  id?: string;
  disabled?: boolean;
  /** Where it stands. `field`: a row of a form, as wide as the fields around
      it. `compact`: beside its label in a row of controls, sized to its
      word. `pill`: one of a bar's filters, a chip rather than a field, naming
      the filter before the choice and tinted while the choice is not the
      filter's rest. */
  variant?: "field" | "compact" | "pill";
  /** A pill's rest: the choice that filters nothing, which the pill does not
      tint for. The first option unless said otherwise; the current value,
      where every choice is as much of a rest as any other. */
  restValue?: V;
  /** What a pill says before the choice: its label, unless it stands where
      the choice says enough on its own (null). */
  prefix?: string | null;
  /** A ref on the trigger, for whoever has to focus it from outside: a
      dialog opening on its first field. */
  triggerRef?: RefObject<HTMLButtonElement | null>;
}

/**
 * One choice from a short list, wherever one is made (#1433).
 *
 * The native `<select>` was the one control the operating system drew rather
 * than the game: its closed face took the field recipe well enough, but its
 * popup was the platform's - a grey system menu in the middle of a form of
 * warm paper and indigo. The language picker had already left it for that
 * reason, and this is that picker's mechanism (`usePickerPopup`) with a plain
 * face: a trigger that reads as a field or as a chip, and a raised list of
 * rows with a tick on the chosen one.
 *
 * A trigger has no value of its own the way a select does, so its accessible
 * name carries the choice: "Reason: Harassment". A visible label still points
 * at it with `htmlFor`, which makes the label's click open the list.
 */
export function Picker<V extends string>({
  label,
  options,
  value,
  onChange,
  id,
  disabled = false,
  variant = "field",
  restValue,
  prefix = label,
  triggerRef: externalTriggerRef,
}: PickerProps<V>) {
  const { open, toggle, close, triggerRef, listRef, rootRef, handleListKeyDown } = usePickerPopup({
    triggerRef: externalTriggerRef,
  });
  const listId = id !== undefined ? `${id}-list` : undefined;
  const current = options.find((option) => option.value === value) ?? options[0];
  const rest = restValue ?? options[0]?.value;
  const set = variant === "pill" && current !== undefined && current.value !== rest;

  function choose(next: V) {
    onChange(next);
    close();
  }

  function renderOption(option: PickerOption<V>) {
    const selected = option.value === value;
    return (
      <button
        key={option.value}
        type="button"
        role="option"
        aria-selected={selected}
        data-value={option.value}
        className={`picker-option${selected ? " is-selected" : ""}`}
        onClick={() => choose(option.value)}
      >
        <span className="picker-option-label">{option.label}</span>
        <span className="picker-check" aria-hidden="true">
          {selected && <CheckIcon size={13} />}
        </span>
      </button>
    );
  }

  return (
    <div className={`picker is-${variant}${open ? " is-open" : ""}`} ref={rootRef}>
      <button
        ref={triggerRef}
        id={id}
        type="button"
        className={`picker-trigger${set ? " is-set" : ""}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-label={ui.picker.currentChoice({ label, value: current?.label ?? "" })}
        data-value={current?.value}
        disabled={disabled}
        onClick={toggle}
      >
        <span className="picker-value">
          {variant === "pill" && prefix !== null && <span className="picker-prefix">{prefix} · </span>}
          {current?.label}
        </span>
        <span className="picker-chevron" aria-hidden="true">
          <ChevronDownIcon size={14} />
        </span>
      </button>

      {open && (
        <div
          id={listId}
          ref={listRef}
          className="picker-list"
          role="listbox"
          aria-label={label}
          onKeyDown={handleListKeyDown}
        >
          {groupRuns(options).map(({ group, members }) =>
            group === undefined ? (
              members.map(renderOption)
            ) : (
              <div key={group} role="group" aria-label={group} className="picker-group">
                <div className="picker-group-label section-label" aria-hidden="true">{group}</div>
                {members.map(renderOption)}
              </div>
            ),
          )}
        </div>
      )}
    </div>
  );
}

/** The options in runs of one group each, in the order given. */
function groupRuns<V extends string>(
  options: readonly PickerOption<V>[],
): { group: string | undefined; members: PickerOption<V>[] }[] {
  const runs: { group: string | undefined; members: PickerOption<V>[] }[] = [];
  for (const option of options) {
    const last = runs[runs.length - 1];
    if (last && last.group === option.group) last.members.push(option);
    else runs.push({ group: option.group, members: [option] });
  }
  return runs;
}
