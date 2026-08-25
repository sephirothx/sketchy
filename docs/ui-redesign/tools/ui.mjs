// Shared design tokens, icons and small components for the redesign canvas.
// Every artboard is generated from these so the system stays consistent.
//
// Colors are CSS custom properties with a light and a dark value, switched by
// a data-theme attribute on the artboard root. `T.<token>` interpolates as
// `var(--<token>)`, so every component is theme-aware for free.

export const PALETTES = {
  light: {
    paper: '#FAF6EF',        // warm page background
    well: '#FAF6EF',         // inset surface inside cards (same as paper in light)
    card: '#FFFFFF',
    field: '#FFFFFF',      // text inputs (recessed to the page ground in dark)
    ink: '#292520',          // warm near-black
    muted: '#6F6759',
    faint: '#A29883',
    line: '#E7DFD2',
    lineStrong: '#D3C8B4',
    track: '#F1EBE0',        // segmented-control well
    guestBg: '#F0EADD',      // guest avatar fill
    avatarInk: '#FFFFFF',    // avatar initial
    avMarta: '#0F766E', avBruno: '#C2410C', avYuki: '#7E22CE', avInes: '#0369A1', avGuest: '#5B6472',
    primaryEdgeSoft: '#C9CCF4',
    scrim: 'rgba(30, 27, 22, 0.5)',
    primary: '#5157D8',      // crayon indigo
    primarySoft: '#EEEFFB',
    primaryInk: '#3B41B5',   // text on primarySoft
    primaryEdge: '#3B41B5',  // primary button bottom edge
    warm: '#E8703A',         // marker orange — energy, timers, celebration
    warmSoft: '#FBEADF',
    warmInk: '#B5541F',
    warmEdge: '#C1521F',
    success: '#2F9E44',
    successSoft: '#E7F5EA',
    successInk: '#1F7A33',
    warning: '#B45309',
    warningSoft: '#FDF1DC',
    warningEdge: '#EBC98A',
    danger: '#C92A2A',
    dangerSoft: '#FBECEC',
    gold: '#8A6D0B', silver: '#5A6472', bronze: '#8A5A2E',
    // player name text (avatars keep the fixed account color)
    pcMarta: '#0F766E', pcBruno: '#C2410C', pcYuki: '#7E22CE', pcInes: '#0369A1', pcSparrow: '#8A8272',
  },
  // Dark grounds, borders and text reuse the shipped app's dark theme
  // (theme-overrides.css): slate #0f172a ground, #1e293b surfaces,
  // #334155/#475569 borders, #f8fafc/#94a3b8/#64748b text. Tint surfaces are
  // ALPHA washes of their accent so they blend into the slate instead of
  // reading as foreign opaque patches; insets recess with a translucent well.
  dark: {
    paper: '#0F172A',
    well: 'rgba(2, 6, 23, 0.35)',
    card: '#1E293B',
    field: '#0F172A',      // shipped dark input background (theme-overrides.css)
    ink: '#F8FAFC',
    muted: '#94A3B8',
    faint: '#64748B',
    line: '#334155',
    lineStrong: '#475569',
    track: 'rgba(2, 6, 23, 0.45)',
    guestBg: 'rgba(148, 163, 184, 0.18)',
    avatarInk: '#132036',    // dark initial on pastel avatar
    avMarta: '#5EE0C2', avBruno: '#F5B26B', avYuki: '#D9B8F5', avInes: '#82AACB', avGuest: '#C3CBD8',
    primaryEdgeSoft: 'rgba(102, 108, 228, 0.5)',
    scrim: 'rgba(2, 6, 23, 0.6)',
    primary: '#666CE4',
    primarySoft: 'rgba(102, 108, 228, 0.17)',
    primaryInk: '#C7CBFA',
    primaryEdge: '#3B41B5',
    warm: '#EE7E48',
    warmSoft: 'rgba(238, 126, 72, 0.15)',
    warmInk: '#FDBA74',
    warmEdge: '#9A3412',
    success: '#4ADE80',
    successSoft: 'rgba(74, 222, 128, 0.13)',
    successInk: '#86EFAC',
    warning: '#FBBF24',
    warningSoft: 'rgba(251, 191, 36, 0.13)',
    warningEdge: 'rgba(251, 191, 36, 0.4)',
    danger: '#F87171',
    dangerSoft: 'rgba(248, 113, 113, 0.14)',
    gold: '#F5CE62', silver: '#B9C4D4', bronze: '#DFA878',
    pcMarta: '#2BB3A0', pcBruno: '#F08A54', pcYuki: '#BF87ED', pcInes: '#4FA8E0', pcSparrow: '#A0A5B2',
  },
};

const varTokens = Object.fromEntries(Object.keys(PALETTES.light).map((k) => [k, `var(--${k})`]));

export const T = {
  ...varTokens,
  display: "'Fredoka', 'Trebuchet MS', system-ui, sans-serif",
  body: "'Nunito Sans', 'Segoe UI', system-ui, sans-serif",
  radius: '14px',
  radiusSm: '10px',
  shadow: '0 1px 2px rgba(20, 16, 10, 0.06)',
  shadowRaised: '0 10px 30px rgba(20, 16, 10, 0.14)',
};

export const cssVars = (theme) =>
  Object.entries(PALETTES[theme]).map(([k, v]) => `--${k}: ${v};`).join(' ');

// Player identity — avatar keeps the fixed account color from the shipped
// mockups; name text uses a theme-adjusted token so it stays legible on dark.
export const P = {
  marta:   { name: 'Marta',      av: 'var(--avMarta)', text: 'var(--pcMarta)',   guest: false },
  bruno:   { name: 'Bruno',      av: 'var(--avBruno)', text: 'var(--pcBruno)',   guest: false },
  yuki:    { name: 'Yuki',       av: 'var(--avYuki)',  text: 'var(--pcYuki)',    guest: false },
  ines:    { name: 'Ines',       av: 'var(--avInes)',  text: 'var(--pcInes)',    guest: false },
  sparrow: { name: 'Sparrow-14', av: 'var(--avGuest)', text: 'var(--pcSparrow)', guest: true },
};

const stroke = (paths, size = 16, sw = 2) =>
  `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${sw}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="flex: none">${paths}</svg>`;

export const icon = {
  copy: (s) => stroke('<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>', s),
  link: (s) => stroke('<path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/>', s),
  eye: (s) => stroke('<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>', s),
  pencil: (s) => stroke('<path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/>', s),
  moon: (s) => stroke('<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/>', s),
  crown: (s) => stroke('<path d="M3 17h18l-1-9-4.5 3.5L12 6l-3.5 5.5L4 8l-1 9Z"/><path d="M4 21h16"/>', s),
  check: (s) => stroke('<path d="M4 12.5 9.5 18 20 6.5"/>', s, 2.6),
  clock: (s) => stroke('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/>', s),
  user: (s) => stroke('<circle cx="12" cy="8" r="4"/><path d="M4.5 21a7.5 7.5 0 0 1 15 0"/>', s),
  users: (s) => stroke('<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 5a3.5 3.5 0 0 1 0 6.7"/><path d="M17.5 14.4a6.5 6.5 0 0 1 4 5.6"/>', s),
  rounds: (s) => stroke('<path d="M3 12a9 9 0 1 0 2.6-6.4"/><path d="M3 4v5h5"/>', s),
  gear: (s) => stroke('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.55V21a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1-1.55 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.7 1.7 0 0 0 .34-1.87 1.7 1.7 0 0 0-1.55-1H3a2 2 0 1 1 0-4h.09a1.7 1.7 0 0 0 1.55-1 1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.7 1.7 0 0 0 1.87.34h.09A1.7 1.7 0 0 0 10 3.09V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.55 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87v.09a1.7 1.7 0 0 0 1.55 1H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.55 1Z"/>', s),
  download: (s) => stroke('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>', s),
  leave: (s) => stroke('<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>', s),
  bulb: (s) => stroke('<path d="M9 18h6"/><path d="M10 22h4"/><path d="M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.4 1 2.3h6c0-.9.4-1.8 1-2.3A7 7 0 0 0 12 2Z"/>', s),
  trophy: (s) => stroke('<path d="M8 21h8"/><path d="M12 17v4"/><path d="M7 4h10v5a5 5 0 0 1-10 0V4Z"/><path d="M7 6H4a3 3 0 0 0 3 5"/><path d="M17 6h3a3 3 0 0 1-3 5"/>', s),
  zap: (s) => stroke('<path d="M13 2 4 14h6l-1 8 9-12h-6l1-8Z"/>', s),
  brush: (s) => stroke('<path d="M9.06 11.9 20.5 2.5a2 2 0 0 1 3 3l-9.4 11.44"/><path d="M9.5 12.5c-2.5 0-4.5 2-4.5 4.5 0 1.5-1 2.5-2.5 3 1 .8 2.3 1.5 4 1.5 3 0 5.5-2.5 5.5-5.5"/>', s),
  search: (s) => stroke('<circle cx="11" cy="11" r="7"/><path d="m21 21-4-4"/>', s),
  plus: (s) => stroke('<path d="M12 5v14"/><path d="M5 12h14"/>', s),
  x: (s) => stroke('<path d="M18 6 6 18"/><path d="m6 6 12 12"/>', s),
  send: (s) => stroke('<path d="m22 2-11 11"/><path d="M22 2 15 22l-4-9-9-4 20-7Z"/>', s),
  dots: (s) => stroke('<circle cx="5" cy="12" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="19" cy="12" r="1.4"/>', s),
  fill: (s) => stroke('<path d="m19 11-8-8-8.6 8.6a2 2 0 0 0 0 2.8l5.2 5.2a2 2 0 0 0 2.8 0L19 11Z"/><path d="m5 2 5 5"/><path d="M2 13h15"/><path d="M22 20a2 2 0 1 1-4 0c0-1.6 2-4 2-4s2 2.4 2 4Z"/>', s),
  eraser: (s) => stroke('<path d="m7 21-4.3-4.3a1 1 0 0 1 0-1.4l12-12a1 1 0 0 1 1.4 0l4.3 4.3a1 1 0 0 1 0 1.4L8.4 21a1 1 0 0 1-1.4 0Z"/><path d="M22 21H7"/><path d="m5 11 9 9"/>', s),
  rect: (s) => stroke('<rect x="3" y="3" width="18" height="18" rx="2"/>', s),
  triangle: (s) => stroke('<path d="M13.73 4a2 2 0 0 0-3.46 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/>', s),
  circle: (s) => stroke('<circle cx="12" cy="12" r="9"/>', s),
  undo: (s) => stroke('<path d="M3 7v6h6"/><path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13"/>', s),
  trash: (s) => stroke('<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>', s),
  alertCircle: (s) => stroke('<circle cx="12" cy="12" r="9"/><path d="M12 8v5"/><path d="M12 16.5h.01"/>', s),
  alert: (s) => stroke('<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>', s),
  chevD: (s) => stroke('<path d="m6 9 6 6 6-6"/>', s),
  chevR: (s) => stroke('<path d="m9 6 6 6-6 6"/>', s),
  back: (s) => stroke('<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>', s),
  medal: (s) => stroke('<circle cx="12" cy="15" r="5"/><path d="m8.5 10.5-3-7.5"/><path d="m15.5 10.5 3-7.5"/><path d="m9 3 3 6 3-6"/>', s),
  globe: (s) => stroke('<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3c2.5 2.3 4 5.5 4 9s-1.5 6.7-4 9c-2.5-2.3-4-5.5-4-9s1.5-6.7 4-9Z"/>', s),
  lock: (s) => stroke('<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>', s),
  dice: (s) => stroke('<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8.2" cy="8.2" r="1.1" fill="currentColor" stroke="none"/><circle cx="15.8" cy="8.2" r="1.1" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.1" fill="currentColor" stroke="none"/><circle cx="8.2" cy="15.8" r="1.1" fill="currentColor" stroke="none"/><circle cx="15.8" cy="15.8" r="1.1" fill="currentColor" stroke="none"/>', s),
  timerRing: (seconds, frac, color, size = 52, track = T.line) => {
    const r = (size - 6) / 2;
    const c = 2 * Math.PI * r;
    const sw = size <= 32 ? 3 : 5;
    const fz = size >= 52 ? 18 : size >= 40 ? 15 : 12;
    return `<span style="position: relative; display: inline-flex; align-items: center; justify-content: center; width: ${size}px; height: ${size}px; flex: none">
      <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" aria-hidden="true" style="position: absolute; inset: 0; transform: rotate(-90deg)">
        <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke-width="${sw}" style="stroke: ${track}"/>
        <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke-width="${sw}" stroke-linecap="round" stroke-dasharray="${(c * frac).toFixed(1)} ${c.toFixed(1)}" style="stroke: ${color}"/>
      </svg>
      <span style="position: relative; font-family: ${T.display}; font-weight: 600; font-size: ${fz}px; color: ${color}; font-variant-numeric: tabular-nums">${seconds}</span>
    </span>`;
  },
};

// Prompt-language flags, drawn inline so they render identically everywhere.
const flagWrap = (inner) =>
  `<svg width="18" height="13" viewBox="0 0 18 13" aria-hidden="true" style="flex: none; border-radius: 2.5px; box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.15)">${inner}</svg>`;
export const flag = {
  en: flagWrap('<rect width="18" height="13" fill="#012169"/><path d="M0 0 18 13M18 0 0 13" stroke="#fff" stroke-width="2.6"/><path d="M0 0 18 13M18 0 0 13" stroke="#C8102E" stroke-width="1.1"/><path d="M9 0v13M0 6.5h18" stroke="#fff" stroke-width="4"/><path d="M9 0v13M0 6.5h18" stroke="#C8102E" stroke-width="2.2"/>'),
  it: flagWrap('<rect width="6" height="13" fill="#009246"/><rect x="6" width="6" height="13" fill="#fff"/><rect x="12" width="6" height="13" fill="#CE2B37"/>'),
  de: flagWrap('<rect width="18" height="4.33" fill="#111"/><rect y="4.33" width="18" height="4.34" fill="#DD0000"/><rect y="8.67" width="18" height="4.33" fill="#FFCE00"/>'),
};

// A small squiggle underline used under the wordmark and section moments.
export const squiggle = (w = 96, color = T.warm) =>
  `<svg width="${w}" height="8" viewBox="0 0 ${w} 8" fill="none" aria-hidden="true" style="display: block"><path d="M2 5 C ${w * 0.14} 1, ${w * 0.22} 7, ${w * 0.36} 4 C ${w * 0.5} 1, ${w * 0.62} 7, ${w * 0.76} 4 C ${w * 0.86} 2, ${w * 0.94} 5, ${w - 2} 3" stroke-width="2.5" stroke-linecap="round" style="stroke: ${color}"/></svg>`;

export const wordmark = (size = 30) =>
  `<span style="display: inline-flex; flex-direction: column; gap: 1px; width: fit-content">
    <span style="font-family: ${T.display}; font-weight: 600; font-size: ${size}px; letter-spacing: 0.01em; color: ${T.ink}; line-height: 1">Sketchy</span>
    ${squiggle(Math.round(size * 2.6))}
  </span>`;

export const avatar = (p, size = 28) => {
  const fz = Math.round(size * 0.48);
  return `<span aria-hidden="true" style="display: inline-flex; align-items: center; justify-content: center; width: ${size}px; height: ${size}px; border-radius: 50%; background: ${p.av}; color: ${T.avatarInk}; font-weight: 800; font-size: ${fz}px; flex: none">${p.name[0]}</span>`;
};

export const pname = (p, extra = '') =>
  p.guest
    ? `<span style="color: ${p.text}; font-style: italic; font-weight: 700${extra}">${p.name}</span>`
    : `<span style="color: ${p.text}; font-weight: 800${extra}">${p.name}</span>`;

export const btn = {
  primary: (label, opts = {}) =>
    `<button type="button" style="display: inline-flex; align-items: center; justify-content: center; gap: 8px; background: ${T.primary}; color: #fff; border: 0; border-radius: ${T.radiusSm}; padding: ${opts.big ? '13px 22px' : '11px 18px'}; font-family: ${T.body}; font-size: ${opts.big ? 16 : 14.5}px; font-weight: 800; min-height: 44px; box-shadow: 0 2px 0 ${T.primaryEdge}${opts.style ? '; ' + opts.style : ''}">${opts.iconL ?? ''}${label}</button>`,
  warm: (label, opts = {}) =>
    `<button type="button" style="display: inline-flex; align-items: center; justify-content: center; gap: 8px; background: ${T.warm}; color: #fff; border: 0; border-radius: ${T.radiusSm}; padding: ${opts.big ? '13px 22px' : '11px 18px'}; font-family: ${T.body}; font-size: ${opts.big ? 16 : 14.5}px; font-weight: 800; min-height: 44px; box-shadow: 0 2px 0 ${T.warmEdge}${opts.style ? '; ' + opts.style : ''}">${opts.iconL ?? ''}${label}</button>`,
  secondary: (label, opts = {}) =>
    `<button type="button" style="display: inline-flex; align-items: center; justify-content: center; gap: 8px; background: ${T.card}; color: ${T.ink}; border: 1.5px solid ${T.lineStrong}; border-radius: ${T.radiusSm}; padding: 10px 16px; font-family: ${T.body}; font-size: 14.5px; font-weight: 800; min-height: 44px; box-shadow: ${T.shadow}${opts.style ? '; ' + opts.style : ''}">${opts.iconL ?? ''}${label}</button>`,
  ghost: (label, opts = {}) =>
    `<button type="button" style="display: inline-flex; align-items: center; justify-content: center; gap: 7px; background: transparent; color: ${T.muted}; border: 0; border-radius: ${T.radiusSm}; padding: 10px 12px; font-family: ${T.body}; font-size: 14px; font-weight: 800; min-height: 44px${opts.style ? '; ' + opts.style : ''}">${opts.iconL ?? ''}${label}</button>`,
  dangerGhost: (label, opts = {}) =>
    `<button type="button" style="display: inline-flex; align-items: center; justify-content: center; gap: 7px; background: transparent; color: ${T.danger}; border: 0; border-radius: ${T.radiusSm}; padding: 10px 12px; font-family: ${T.body}; font-size: 14px; font-weight: 800; min-height: 44px${opts.style ? '; ' + opts.style : ''}">${opts.iconL ?? ''}${label}</button>`,
  iconOnly: (svg, label, size = 44) =>
    `<button type="button" aria-label="${label}" title="${label}" style="display: inline-flex; align-items: center; justify-content: center; width: ${size}px; height: ${size}px; background: ${T.card}; color: ${T.muted}; border: 1.5px solid ${T.line}; border-radius: ${T.radiusSm}; box-shadow: ${T.shadow}">${svg}</button>`,
};

export const chip = (label, kind = 'neutral') => {
  const k = {
    neutral: [T.well, T.muted, T.line],
    primary: [T.primarySoft, T.primaryInk, 'transparent'],
    success: [T.successSoft, T.successInk, 'transparent'],
    warning: [T.warningSoft, T.warning, 'transparent'],
    danger: [T.dangerSoft, T.danger, 'transparent'],
    warm: [T.warmSoft, T.warmInk, 'transparent'],
  }[kind];
  return `<span style="display: inline-flex; align-items: center; gap: 5px; background: ${k[0]}; color: ${k[1]}; border: 1px solid ${k[2]}; border-radius: 999px; padding: 4px 11px; font-size: 12px; font-weight: 800; white-space: nowrap">${label}</span>`;
};

export const card = (inner, opts = {}) =>
  `<section style="background: ${T.card}; border: 1.5px solid ${T.line}; border-radius: ${T.radius}; padding: ${opts.pad ?? '20px 22px'}; box-shadow: ${T.shadow}${opts.style ? '; ' + opts.style : ''}">${inner}</section>`;

export const sectionLabel = (text) =>
  `<p style="color: ${T.faint}; font-size: 11.5px; font-weight: 800; letter-spacing: 0.09em; margin: 0; text-transform: uppercase">${text}</p>`;

export const segmented = (options, activeIdx, opts = {}) => {
  const w = opts.w ? `width: ${opts.w}px; ` : '';
  return `<div style="display: inline-flex; gap: 3px; background: ${T.track}; border-radius: 999px; padding: 4px; width: fit-content">
    ${options.map((o, i) => i === activeIdx
      ? `<button type="button" aria-pressed="true" style="${w}display: inline-flex; align-items: center; justify-content: center; gap: 6px; background: ${T.card}; border: 0; border-radius: 999px; color: ${T.ink}; font-family: ${T.body}; font-size: 13.5px; font-weight: 800; padding: 8px 16px; box-shadow: 0 1px 3px rgba(20, 16, 10, 0.14); white-space: nowrap">${o}</button>`
      : `<button type="button" aria-pressed="false" style="${w}display: inline-flex; align-items: center; justify-content: center; gap: 6px; background: transparent; border: 0; border-radius: 999px; color: ${T.muted}; font-family: ${T.body}; font-size: 13.5px; font-weight: 700; padding: 8px 16px; white-space: nowrap">${o}</button>`
    ).join('')}
  </div>`;
};

// An on/off toggle switch with its label; `hint` renders muted after the label.
export const switchCtl = (label, on, hint = '') => `
<label style="display: inline-flex; align-items: center; gap: 10px; cursor: pointer">
  <span role="switch" aria-checked="${on}" style="display: inline-flex; align-items: center; width: 42px; height: 24px; border-radius: 999px; padding: 3px; background: ${on ? T.primary : T.lineStrong}; flex: none">
    <span style="width: 18px; height: 18px; border-radius: 50%; background: #fff; box-shadow: 0 1px 2px rgba(20, 16, 10, 0.25); transform: translateX(${on ? '18px' : '0'})"></span>
  </span>
  <span style="font-size: 13.5px; font-weight: 800; color: ${T.ink}">${label}${hint ? ` <span style="font-weight: 600; color: ${T.faint}">${hint}</span>` : ''}</span>
</label>`;

export const selectBox = (label) =>
  `<span style="display: inline-flex; align-items: center; justify-content: space-between; gap: 10px; background: ${T.field}; border: 1.5px solid ${T.lineStrong}; border-radius: ${T.radiusSm}; padding: 9px 12px; font-size: 14px; font-weight: 700; color: ${T.ink}; min-height: 42px">${label}<span style="color: ${T.faint}; display: inline-flex">${icon.chevD(14)}</span></span>`;

export const input = (opts = {}) =>
  `<input type="text" ${opts.value ? `value="${opts.value}" ` : ''}${opts.placeholder ? `placeholder="${opts.placeholder}" ` : ''}style="background: ${T.field}; border: 1.5px solid ${T.lineStrong}; border-radius: ${T.radiusSm}; padding: 10px 12px; font-family: ${T.body}; font-size: 14.5px; color: ${T.ink}; min-height: 42px; width: 100%${opts.style ? '; ' + opts.style : ''}">`;

// Theme-scoped style rules shared by the artboards and the explorer.
export const themeStyles = `
    [data-theme="light"] { ${cssVars('light')} }
    [data-theme="dark"] { ${cssVars('dark')} }
    [data-theme] input::placeholder, [data-theme] textarea::placeholder { color: var(--faint); }
    [data-theme] a { color: var(--primary); text-decoration: none; font-weight: 700; }
    [data-theme] a:hover { color: var(--primaryInk); }`;

// Wrap an artboard body in the Design Component skeleton. Every artboard
// carries a light/dark theme tweak, switched by data-theme on the root.
export const dcWrap = (body, { width, height }) => `<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fredoka:wght@500;600&family=Nunito+Sans:opsz,wght@6..12,400;6..12,600;6..12,700;6..12,800&display=swap">
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; }
${themeStyles}
    h1, h2, h3, h4, p, ul, ol, fieldset, legend { margin: 0; }
    button { cursor: pointer; }
    summary { cursor: pointer; }
    summary.plain { list-style: none; }
    summary.plain::-webkit-details-marker { display: none; }
  </style>
</helmet>
<div data-theme="{{theme}}" style="min-height: 100vh; background: ${T.paper}; color: ${T.ink}; font-family: ${T.body}">
${body}
</div>
</x-dc>
<script data-dc-script data-props='{"theme": {"editor": "enum", "options": ["light", "dark"], "default": "light"}, "$preview": {"width": ${width}, "height": ${height}}}'>
class Component extends DCLogic {
  renderVals() {
    return { theme: this.props.theme ?? 'light' };
  }
}
</script>
</body>
</html>
`;
