import { useCallback } from "react";

/** The tab strip for the operations workspace.

A real tablist rather than a row of buttons that swap a `<div>`: this page is
covered by the axe pass over the operator surfaces, and a screen reader needs
to be told these are alternatives to one another and which one is showing.
Arrow keys move between them because that is what a tablist promises. */

export interface OpsTab {
  id: string;
  label: string;
}

export function OpsTabs({
  tabs,
  current,
  idPrefix,
  onSelect,
}: {
  tabs: readonly OpsTab[];
  current: string;
  /** Shared with the panels, so `aria-controls` names an element that exists. */
  idPrefix: string;
  onSelect: (id: string) => void;
}) {
  const prefix = idPrefix;

  const move = useCallback(
    (from: number, delta: number) => {
      const next = (from + delta + tabs.length) % tabs.length;
      onSelect(tabs[next].id);
      document.getElementById(`${prefix}-tab-${tabs[next].id}`)?.focus();
    },
    [onSelect, prefix, tabs],
  );

  return (
    <div className="ops-tabs" role="tablist" aria-label="Server operations">
      {tabs.map((tab, index) => {
        const selected = tab.id === current;
        return (
          <button
            key={tab.id}
            id={`${prefix}-tab-${tab.id}`}
            type="button"
            role="tab"
            className="ops-tab"
            aria-selected={selected}
            // Only on the selected tab, because only its panel is in the DOM.
            // The panels are mounted on demand - the activity table is an
            // expensive read that the tab exists to defer, and the tuning and
            // control panels each fetch on mount - so pointing every tab at a
            // panel would leave four of the five references dangling, which is
            // invalid ARIA and something axe flags. A reference that exists
            // for the panel being shown says everything true here.
            aria-controls={selected ? `${prefix}-panel-${tab.id}` : undefined}
            // Roving tabindex: one stop for the whole strip, then arrow keys
            // inside it. Five separate tab stops would put the audit ledger
            // four presses from the page for somebody who only uses a keyboard.
            tabIndex={selected ? 0 : -1}
            onClick={() => onSelect(tab.id)}
            onKeyDown={(event) => {
              if (event.key === "ArrowRight") move(index, 1);
              else if (event.key === "ArrowLeft") move(index, -1);
              else if (event.key === "Home") move(index, -index);
              else if (event.key === "End") move(index, tabs.length - 1 - index);
              else return;
              event.preventDefault();
            }}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}

/** The panel one tab reveals, wired to it for anyone not looking at the screen. */
export function OpsTabPanel({
  id,
  current,
  idPrefix,
  labelledBy,
  children,
}: {
  id: string;
  current: string;
  idPrefix: string;
  labelledBy?: string;
  children: React.ReactNode;
}) {
  if (id !== current) return null;
  return (
    <div
      id={`${idPrefix}-panel-${id}`}
      aria-labelledby={labelledBy ?? `${idPrefix}-tab-${id}`}
      role="tabpanel"
      className="ops-tabpanel"
      tabIndex={0}
    >
      {children}
    </div>
  );
}
