// The one header every screen wears, in three slots (#580).
//
//   1 · where you are — the wordmark, always the way back to the lobby, then
//       the place: a page name as a crumb, or the room chip (name · code,
//       one press copies the invite link).
//   2 · what is going on — the room's phase. Empty outside a room.
//   3 · you — at most three controls, and the last two never move: the
//       place's one action, Player settings, the identity chip.
//
// Every artboard calls this rather than composing a bar of its own, which is
// the whole point: a page that wants a fourth control has to put it in the
// place's one menu, not in the bar. It mirrors
// `frontend/src/components/AppHeader.tsx`, so a change there is a change here.
import { T, icon, avatar, P, wordmark } from './ui.mjs';

// The identity chip. Compact in a room, where the bar is carrying a room
// chip and a phase as well and the name would not survive the squeeze.
export const identityChip = (p = P.marta, { compact = false, open = false } = {}) => `
<button type="button"${open ? ' aria-expanded="true"' : ''} style="display: inline-flex; align-items: center; gap: ${compact ? 4 : 8}px; border: 1.5px solid ${T.line}; background: ${T.card}; border-radius: 999px; padding: ${compact ? '4px 8px 4px 4px' : '5px 14px 5px 5px'}; min-height: ${compact ? 38 : 44}px; font-family: ${T.body}; box-shadow: ${T.shadow}">
  ${avatar(p, compact ? 28 : 30)}
  ${compact ? '' : `<span style="font-weight: 800; font-size: 14px; color: ${T.ink}">${p.name}</span>`}
  <span style="display: inline-flex; color: ${T.faint}">${icon.chevD(compact ? 13 : 14)}</span>
</button>`;

// The gear: Player settings, second-from-last and never anywhere else.
const gearButton = `
<button type="button" aria-label="Player settings" title="Player settings" style="display: inline-flex; align-items: center; justify-content: center; width: 38px; height: 38px; background: ${T.card}; color: ${T.muted}; border: 1.5px solid ${T.line}; border-radius: ${T.radiusSm}; box-shadow: ${T.shadow}">${icon.gear(18)}</button>`;

// A back arrow, on every sub-page and on both devices.
const backButton = `
<button type="button" aria-label="Back" title="Back" style="display: inline-flex; align-items: center; justify-content: center; width: 38px; height: 38px; background: transparent; color: ${T.muted}; border: 0; border-radius: ${T.radiusSm}; flex: none">${icon.back(18)}</button>`;

const divider = `<span aria-hidden="true" style="width: 1.5px; height: 20px; background: ${T.line}; flex: none"></span>`;

// The room chip: which room this is, and the code, as one control — because
// pressing it does one thing, copy the invite link.
export const roomChip = (room) => `
<button type="button" title="Copy the invite link" style="display: inline-flex; align-items: center; gap: 9px; min-width: 0; background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: 999px; padding: 6px 13px; font-family: ${T.body}; box-shadow: ${T.shadow}">
  <span style="font-weight: 800; font-size: 14px; color: ${T.ink}; white-space: nowrap; overflow: hidden; text-overflow: ellipsis">${room.name}</span>
  ${divider}
  <span style="font-size: 12.5px; font-weight: 800; color: ${T.muted}; letter-spacing: 0.08em">${room.code}</span>
  <span style="display: inline-flex; color: ${T.faint}">${icon.copy(13)}</span>
</button>`;

/**
 * @param page   a sub-page's name, shown as a crumb after a back arrow.
 * @param room   `{ name, code }` — shown as the room chip instead of a crumb.
 * @param center what is going on: the room's phase. Empty everywhere else.
 * @param action the place's one action: Create room, or the Room menu.
 * @param menu   a menu drawn open under the actions, so an artboard can
 *               document its rows rather than just its button.
 */
export const appHeader = ({ page = '', room = null, center = '', action = '', menu = '', gap = 22 } = {}) => `
<header style="display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); align-items: center; gap: 16px; margin-bottom: ${gap}px; min-height: 44px">
  <div style="display: flex; align-items: center; gap: 10px; min-width: 0">
    ${page ? backButton : ''}
    ${wordmark(28)}
    ${page ? `${divider}<span style="font-family: ${T.display}; font-weight: 600; font-size: 17px; color: ${T.ink}; white-space: nowrap">${page}</span>` : ''}
    ${room ? roomChip(room) : ''}
  </div>
  ${center ? `<div style="display: flex; align-items: center; gap: 10px; flex: none">${center}</div>` : '<span></span>'}
  <div style="position: relative; display: flex; align-items: center; gap: 8px; flex: none; justify-self: end">
    ${action}
    ${gearButton}
    ${identityChip(P.marta, { compact: Boolean(room), open: Boolean(menu) && !room })}
    ${menu}
  </div>
</header>`;
