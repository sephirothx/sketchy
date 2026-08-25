/* The redesign's stroke icon set (docs/ui-redesign/tools/ui.mjs), as React
 * components. All icons are 24×24 stroke drawings on currentColor and are
 * decorative by default (aria-hidden) — interactive elements carry their own
 * accessible names. */
import type { CSSProperties, ReactNode } from "react";

interface IconProps {
  size?: number;
  strokeWidth?: number;
}

interface IconBaseProps extends IconProps {
  children: ReactNode;
}

function IconBase({ size = 16, strokeWidth = 2, children }: IconBaseProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ flex: "none" }}
    >
      {children}
    </svg>
  );
}

export function CopyIcon(p: IconProps) { return <IconBase {...p}><rect x="9" y="9" width="12" height="12" rx="2" /><path d="M5 15V5a2 2 0 0 1 2-2h10" /></IconBase>; }
export function LinkIcon(p: IconProps) { return <IconBase {...p}><path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7" /><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7" /></IconBase>; }
export function EyeIcon(p: IconProps) { return <IconBase {...p}><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" /><circle cx="12" cy="12" r="3" /></IconBase>; }
export function PencilIcon(p: IconProps) { return <IconBase {...p}><path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z" /></IconBase>; }
export function MoonIcon(p: IconProps) { return <IconBase {...p}><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" /></IconBase>; }
export function CrownIcon(p: IconProps) { return <IconBase {...p}><path d="M3 17h18l-1-9-4.5 3.5L12 6l-3.5 5.5L4 8l-1 9Z" /><path d="M4 21h16" /></IconBase>; }
export function CheckIcon(p: IconProps) { return <IconBase {...p}><path d="M4 12.5 9.5 18 20 6.5" /></IconBase>; }
export function ClockIcon(p: IconProps) { return <IconBase {...p}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3.5 2" /></IconBase>; }
export function UserIcon(p: IconProps) { return <IconBase {...p}><circle cx="12" cy="8" r="4" /><path d="M4.5 21a7.5 7.5 0 0 1 15 0" /></IconBase>; }
export function UsersIcon(p: IconProps) { return <IconBase {...p}><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20a6.5 6.5 0 0 1 13 0" /><path d="M16 5a3.5 3.5 0 0 1 0 6.7" /><path d="M17.5 14.4a6.5 6.5 0 0 1 4 5.6" /></IconBase>; }
export function RoundsIcon(p: IconProps) { return <IconBase {...p}><path d="M3 12a9 9 0 1 0 2.6-6.4" /><path d="M3 4v5h5" /></IconBase>; }
export function GearIcon(p: IconProps) { return <IconBase {...p}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.55V21a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1-1.55 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.7 1.7 0 0 0 .34-1.87 1.7 1.7 0 0 0-1.55-1H3a2 2 0 1 1 0-4h.09a1.7 1.7 0 0 0 1.55-1 1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.7 1.7 0 0 0 1.87.34h.09A1.7 1.7 0 0 0 10 3.09V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.55 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87v.09a1.7 1.7 0 0 0 1.55 1H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.55 1Z" /></IconBase>; }
export function DownloadIcon(p: IconProps) { return <IconBase {...p}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="m7 10 5 5 5-5" /><path d="M12 15V3" /></IconBase>; }
export function LeaveIcon(p: IconProps) { return <IconBase {...p}><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><path d="m16 17 5-5-5-5" /><path d="M21 12H9" /></IconBase>; }
export function BulbIcon(p: IconProps) { return <IconBase {...p}><path d="M9 18h6" /><path d="M10 22h4" /><path d="M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.4 1 2.3h6c0-.9.4-1.8 1-2.3A7 7 0 0 0 12 2Z" /></IconBase>; }
export function TrophyIcon(p: IconProps) { return <IconBase {...p}><path d="M8 21h8" /><path d="M12 17v4" /><path d="M7 4h10v5a5 5 0 0 1-10 0V4Z" /><path d="M7 6H4a3 3 0 0 0 3 5" /><path d="M17 6h3a3 3 0 0 1-3 5" /></IconBase>; }
export function ZapIcon(p: IconProps) { return <IconBase {...p}><path d="M13 2 4 14h6l-1 8 9-12h-6l1-8Z" /></IconBase>; }
export function BrushIcon(p: IconProps) { return <IconBase {...p}><path d="M9.06 11.9 20.5 2.5a2 2 0 0 1 3 3l-9.4 11.44" /><path d="M9.5 12.5c-2.5 0-4.5 2-4.5 4.5 0 1.5-1 2.5-2.5 3 1 .8 2.3 1.5 4 1.5 3 0 5.5-2.5 5.5-5.5" /></IconBase>; }
export function SearchIcon(p: IconProps) { return <IconBase {...p}><circle cx="11" cy="11" r="7" /><path d="m21 21-4-4" /></IconBase>; }
export function PlusIcon(p: IconProps) { return <IconBase {...p}><path d="M12 5v14" /><path d="M5 12h14" /></IconBase>; }
export function XIcon(p: IconProps) { return <IconBase {...p}><path d="M18 6 6 18" /><path d="m6 6 12 12" /></IconBase>; }
export function SendIcon(p: IconProps) { return <IconBase {...p}><path d="m22 2-11 11" /><path d="M22 2 15 22l-4-9-9-4 20-7Z" /></IconBase>; }
export function DotsIcon(p: IconProps) { return <IconBase {...p}><circle cx="5" cy="12" r="1.4" /><circle cx="12" cy="12" r="1.4" /><circle cx="19" cy="12" r="1.4" /></IconBase>; }
export function FillIcon(p: IconProps) { return <IconBase {...p}><path d="m19 11-8-8-8.6 8.6a2 2 0 0 0 0 2.8l5.2 5.2a2 2 0 0 0 2.8 0L19 11Z" /><path d="m5 2 5 5" /><path d="M2 13h15" /><path d="M22 20a2 2 0 1 1-4 0c0-1.6 2-4 2-4s2 2.4 2 4Z" /></IconBase>; }
export function EraserIcon(p: IconProps) { return <IconBase {...p}><path d="m7 21-4.3-4.3a1 1 0 0 1 0-1.4l12-12a1 1 0 0 1 1.4 0l4.3 4.3a1 1 0 0 1 0 1.4L8.4 21a1 1 0 0 1-1.4 0Z" /><path d="M22 21H7" /><path d="m5 11 9 9" /></IconBase>; }
export function RectIcon(p: IconProps) { return <IconBase {...p}><rect x="3" y="3" width="18" height="18" rx="2" /></IconBase>; }
export function TriangleIcon(p: IconProps) { return <IconBase {...p}><path d="M13.73 4a2 2 0 0 0-3.46 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" /></IconBase>; }
export function CircleIcon(p: IconProps) { return <IconBase {...p}><circle cx="12" cy="12" r="9" /></IconBase>; }
export function UndoIcon(p: IconProps) { return <IconBase {...p}><path d="M3 7v6h6" /><path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13" /></IconBase>; }
export function TrashIcon(p: IconProps) { return <IconBase {...p}><path d="M3 6h18" /><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" /><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" /></IconBase>; }
export function AlertIcon(p: IconProps) { return <IconBase {...p}><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" /><path d="M12 9v4" /><path d="M12 17h.01" /></IconBase>; }
export function AlertCircleIcon(p: IconProps) { return <IconBase {...p}><circle cx="12" cy="12" r="9" /><path d="M12 8v5" /><path d="M12 16.5h.01" /></IconBase>; }
export function KeyboardIcon(p: IconProps) { return <IconBase {...p}><rect x="2" y="6" width="20" height="12" rx="2" /><path d="M6 10h.01" /><path d="M10 10h.01" /><path d="M14 10h.01" /><path d="M18 10h.01" /><path d="M6 14h.01" /><path d="M18 14h.01" /><path d="M9 14h6" /></IconBase>; }
export function ChevronDownIcon(p: IconProps) { return <IconBase {...p}><path d="m6 9 6 6 6-6" /></IconBase>; }
export function ChevronUpIcon(p: IconProps) { return <IconBase {...p}><path d="m6 15 6-6 6 6" /></IconBase>; }
export function ChevronRightIcon(p: IconProps) { return <IconBase {...p}><path d="m9 6 6 6-6 6" /></IconBase>; }
export function BackIcon(p: IconProps) { return <IconBase {...p}><path d="m12 19-7-7 7-7" /><path d="M19 12H5" /></IconBase>; }
export function MedalIcon(p: IconProps) { return <IconBase {...p}><circle cx="12" cy="15" r="5" /><path d="m8.5 10.5-3-7.5" /><path d="m15.5 10.5 3-7.5" /><path d="m9 3 3 6 3-6" /></IconBase>; }
export function GlobeIcon(p: IconProps) { return <IconBase {...p}><circle cx="12" cy="12" r="9" /><path d="M3 12h18" /><path d="M12 3c2.5 2.3 4 5.5 4 9s-1.5 6.7-4 9c-2.5-2.3-4-5.5-4-9s1.5-6.7 4-9Z" /></IconBase>; }
export function LockIcon(p: IconProps) { return <IconBase {...p}><rect x="4" y="11" width="16" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></IconBase>; }
export function MailIcon(p: IconProps) { return <IconBase {...p}><rect x="2.5" y="5" width="19" height="14" rx="2" /><path d="m3 7 9 6.5L21 7" /></IconBase>; }
export function DevicesIcon(p: IconProps) { return <IconBase {...p}><rect x="2" y="4" width="15" height="10" rx="2" /><path d="M6 18h7" /><path d="M9.5 14v4" /><rect x="17.5" y="9" width="5" height="9" rx="1.5" /></IconBase>; }
export function ShieldIcon(p: IconProps) { return <IconBase {...p}><path d="M12 2.5 4.5 5.5v6c0 4.7 3.2 8.3 7.5 10 4.3-1.7 7.5-5.3 7.5-10v-6L12 2.5Z" /></IconBase>; }
export function KeyIcon(p: IconProps) { return <IconBase {...p}><circle cx="7.5" cy="15.5" r="4.5" /><path d="m10.7 12.3 9.8-9.8" /><path d="M15.5 7.5 19 11" /><path d="m18 5 3 3" /></IconBase>; }
export function DiceIcon(p: IconProps) { return <IconBase {...p}><rect x="3" y="3" width="18" height="18" rx="3" /><circle cx="8.2" cy="8.2" r="1.1" fill="currentColor" stroke="none" /><circle cx="15.8" cy="8.2" r="1.1" fill="currentColor" stroke="none" /><circle cx="12" cy="12" r="1.1" fill="currentColor" stroke="none" /><circle cx="8.2" cy="15.8" r="1.1" fill="currentColor" stroke="none" /><circle cx="15.8" cy="15.8" r="1.1" fill="currentColor" stroke="none" /></IconBase>; }

/* ------------------------------------------------------ prompt-language flags
 * Drawn inline so they render identically on every OS. Simplified but
 * recognizable; one per supported prompt language (R-PROMPT registry). */
const FLAG_SHAPES: Record<string, ReactNode> = {
  en: (
    <>
      <rect width="18" height="13" fill="#012169" />
      <path d="M0 0 18 13M18 0 0 13" stroke="#fff" strokeWidth="2.6" />
      <path d="M0 0 18 13M18 0 0 13" stroke="#C8102E" strokeWidth="1.1" />
      <path d="M9 0v13M0 6.5h18" stroke="#fff" strokeWidth="4" />
      <path d="M9 0v13M0 6.5h18" stroke="#C8102E" strokeWidth="2.2" />
    </>
  ),
  de: (
    <>
      <rect width="18" height="4.33" fill="#111" />
      <rect y="4.33" width="18" height="4.34" fill="#DD0000" />
      <rect y="8.67" width="18" height="4.33" fill="#FFCE00" />
    </>
  ),
  es: (
    <>
      <rect width="18" height="13" fill="#AA151B" />
      <rect y="3.25" width="18" height="6.5" fill="#F1BF00" />
    </>
  ),
  fr: (
    <>
      <rect width="6" height="13" fill="#002395" />
      <rect x="6" width="6" height="13" fill="#fff" />
      <rect x="12" width="6" height="13" fill="#ED2939" />
    </>
  ),
  it: (
    <>
      <rect width="6" height="13" fill="#009246" />
      <rect x="6" width="6" height="13" fill="#fff" />
      <rect x="12" width="6" height="13" fill="#CE2B37" />
    </>
  ),
  nl: (
    <>
      <rect width="18" height="4.33" fill="#AE1C28" />
      <rect y="4.33" width="18" height="4.34" fill="#fff" />
      <rect y="8.67" width="18" height="4.33" fill="#21468B" />
    </>
  ),
  pt: (
    <>
      <rect width="7" height="13" fill="#006600" />
      <rect x="7" width="11" height="13" fill="#FF0000" />
      <circle cx="7" cy="6.5" r="2.4" fill="#FFFF00" stroke="#006600" strokeWidth="0.6" />
    </>
  ),
};

export function Flag({ language }: { language: string }) {
  const shape = FLAG_SHAPES[language];
  if (!shape) return null;
  return (
    <svg
      width="18"
      height="13"
      viewBox="0 0 18 13"
      aria-hidden="true"
      style={{ flex: "none", borderRadius: 2.5, boxShadow: "0 0 0 1px rgba(0, 0, 0, 0.15)" }}
    >
      {shape}
    </svg>
  );
}

/* ------------------------------------------------------------- brand marks */
export function Squiggle({ width = 96, color = "var(--warm)" }: { width?: number; color?: string }) {
  const w = width;
  return (
    <svg width={w} height="8" viewBox={`0 0 ${w} 8`} fill="none" aria-hidden="true" style={{ display: "block" }}>
      <path
        d={`M2 5 C ${w * 0.14} 1, ${w * 0.22} 7, ${w * 0.36} 4 C ${w * 0.5} 1, ${w * 0.62} 7, ${w * 0.76} 4 C ${w * 0.86} 2, ${w * 0.94} 5, ${w - 2} 3`}
        stroke={color}
        strokeWidth="2.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function Wordmark({ size = 30 }: { size?: number }) {
  const style: CSSProperties = {
    fontFamily: "var(--font-display)",
    fontWeight: 600,
    fontSize: size,
    letterSpacing: "0.01em",
    color: "var(--ink)",
    lineHeight: 1,
  };
  return (
    <span style={{ display: "inline-flex", flexDirection: "column", gap: 1, width: "fit-content" }}>
      <span style={style}>Sketchy</span>
      <Squiggle width={Math.round(size * 2.6)} />
    </span>
  );
}

/* -------------------------------------------------------------- timer ring */
interface TimerRingProps {
  seconds: number;
  /** Fraction of the phase remaining, 0..1. */
  fraction: number;
  color?: string;
  size?: number;
  track?: string;
}

export function TimerRing({
  seconds,
  fraction,
  color = "var(--warm)",
  size = 40,
  track = "var(--line)",
}: TimerRingProps) {
  const radius = (size - 6) / 2;
  const circumference = 2 * Math.PI * radius;
  const clamped = Math.max(0, Math.min(1, fraction));
  const strokeWidth = size <= 32 ? 3 : 5;
  const fontSize = size >= 52 ? 18 : size >= 40 ? 15 : 12;
  return (
    <span
      style={{
        position: "relative",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: size,
        height: size,
        flex: "none",
      }}
    >
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        aria-hidden="true"
        style={{ position: "absolute", inset: 0, transform: "rotate(-90deg)" }}
      >
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" strokeWidth={strokeWidth} style={{ stroke: track }} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={`${(circumference * clamped).toFixed(1)} ${circumference.toFixed(1)}`}
          style={{ stroke: color }}
        />
      </svg>
      <span
        style={{
          position: "relative",
          fontFamily: "var(--font-display)",
          fontWeight: 600,
          fontSize,
          color,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {seconds}
      </span>
    </span>
  );
}
