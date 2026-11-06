import { useEffect, useState } from "react";

import { ui } from "../content/ui/index.ts";
import { euroSignFirst, extraMinorFrom, extraTypedAllowed, formatEuros } from "../lib/support";

const EXTRA_CHIPS = [500, 1000, 2000];

/** "Add a one-time extra?": the plan still decides the pass, and the extra earns
nothing. `renews` says whether there is a renewal for it to stay out of. */
export function ExtraChoice({
  renews,
  maxExtraMinor,
  onChange,
}: {
  renews: boolean;
  maxExtraMinor: number;
  onChange: (extraMinor: number) => void;
}) {
  const [extra, setExtra] = useState<number | "other">(0);
  const [typed, setTyped] = useState("");
  const extraMinor = extra === "other" ? extraMinorFrom(typed, maxExtraMinor) : extra;
  const signFirst = euroSignFirst(document.documentElement.lang);

  useEffect(() => {
    onChange(extraMinor);
  }, [extraMinor, onChange]);

  const chip = (value: number | "other", label: string) => (
    <button
      key={label}
      type="button"
      className={`support-chip${extra === value ? " is-selected" : ""}`}
      aria-pressed={extra === value}
      onClick={() => setExtra(value)}
    >
      {label}
    </button>
  );

  return (
    <div className="support-extra">
      <p>
        <strong>{ui.support.extraAsk}</strong>
        {renews && <span> {ui.support.extraNote}</span>}
      </p>
      <div className="support-chips">
        {chip(0, ui.support.extraNone)}
        {EXTRA_CHIPS.map((value) => chip(value, `+${formatEuros(value)}`))}
        {chip("other", ui.support.extraOther)}
      </div>
      {extra === "other" && (
        // The sign sits outside the input, where typing cannot remove it.
        <label className={`support-extra-field${signFirst ? "" : " is-sign-after"}`}>
          <span aria-hidden="true">€</span>
          <input
            inputMode="decimal"
            aria-label={ui.support.extraOtherLabel}
            value={typed}
            onChange={(event) => {
              const next = event.target.value.trim();
              if (extraTypedAllowed(next, maxExtraMinor)) setTyped(next);
            }}
          />
        </label>
      )}
    </div>
  );
}
