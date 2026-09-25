import { useId, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";

import { ui } from "../content/ui/index.ts";
import { chooseDoodle } from "../lib/avatars";
import {
  DOODLE_SPRITE,
  DOODLES,
  doodleLabel,
  doodleNameOf,
  type DoodleName,
} from "../lib/avatarDoodles";
import { refusalText } from "../lib/refusals.ts";
import { useAuthStore } from "../store/authStore";
import { Avatar } from "./ui/Avatar";
import { ModalShell } from "./ui/ModalShell";
import "../styles/lazy/settings.css";

/**
 * Pick one of our doodles to wear (#579).
 *
 * Every tile is drawn on the player's own disc in their own colour, so what is
 * picked is what everyone will see. Picking applies at once and closes, the
 * way every other row in Player settings applies as it changes; the one worn
 * now is marked, and focus starts on it. The arrow keys move through the grid.
 */
export function AvatarDoodleDialog({
  name,
  nameColor,
  currentUrl,
  onClose,
}: {
  name: string;
  nameColor: string | undefined;
  currentUrl: string | null | undefined;
  onClose: () => void;
}) {
  const introId = useId();
  const gridRef = useRef<HTMLDivElement | null>(null);
  const wearing = doodleNameOf(currentUrl);
  const startRef = useRef<HTMLButtonElement | null>(null);
  const [busy, setBusy] = useState<DoodleName | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function pick(doodle: DoodleName) {
    if (busy) return;
    if (doodle === wearing) {
      onClose();
      return;
    }
    setBusy(doodle);
    setError(null);
    try {
      await chooseDoodle(doodle);
      await useAuthStore.getState().fetchMe();
      onClose();
    } catch (failure) {
      setError(refusalText(failure, ui.avatarDoodleDialog.couldNotChoose));
      setBusy(null);
    }
  }

  function moveFocus(event: ReactKeyboardEvent<HTMLDivElement>) {
    const grid = gridRef.current;
    if (!grid) return;
    // Read from the grid as laid out, because a phone gets fewer columns.
    const columns = getComputedStyle(grid).gridTemplateColumns.split(" ").length || 1;
    const step = {
      ArrowRight: 1,
      ArrowLeft: -1,
      ArrowDown: columns,
      ArrowUp: -columns,
    }[event.key];
    if (step === undefined) return;
    const tiles = [...grid.querySelectorAll<HTMLButtonElement>("button")];
    const index = tiles.indexOf(document.activeElement as HTMLButtonElement);
    if (index < 0) return;
    const next = index + step;
    if (next < 0 || next >= tiles.length) return;
    event.preventDefault();
    tiles[next].focus();
  }

  return (
    <ModalShell
      title={ui.avatarDoodleDialog.title}
      describedBy={introId}
      cardClassName="doodle-picker-card"
      onDismiss={onClose}
      initialFocusRef={startRef}
    >
      <p id={introId} className="modal-body">
        {ui.avatarDoodleDialog.intro}
      </p>
      <div ref={gridRef} className="doodle-picker-grid" onKeyDown={moveFocus}>
        {DOODLES.map((doodle, index) => {
          const worn = doodle === wearing;
          return (
            <button
              key={doodle}
              ref={worn || (!wearing && index === 0) ? startRef : undefined}
              type="button"
              className="doodle-picker-tile"
              aria-pressed={worn}
              aria-busy={busy === doodle || undefined}
              disabled={Boolean(busy)}
              data-doodle={doodle}
              onClick={() => void pick(doodle)}
            >
              <Avatar
                name={name}
                nameColor={nameColor}
                avatarUrl={`${DOODLE_SPRITE}#${doodle}`}
                size={48}
              />
              <span className="doodle-picker-label">{doodleLabel(doodle)}</span>
              {worn && (
                <span className="visually-hidden">{ui.avatarDoodleDialog.wearing}</span>
              )}
            </button>
          );
        })}
      </div>
      {error && (
        <p className="auth-error" role="alert">
          {error}
        </p>
      )}
    </ModalShell>
  );
}
