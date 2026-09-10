/* The redesign's stroke icon set (docs/ui-mockups/tools/ui.mjs), as React
 * components. All icons are 24×24 stroke drawings on currentColor and are
 * decorative by default (aria-hidden) — interactive elements carry their own
 * accessible names. */
import { useId } from "react";
import type { ReactNode } from "react";
import { NOT_FOUND_PATHS, NOT_FOUND_VIEWBOX } from "./notFoundArt";
import { CRASH_PATHS, CRASH_VIEWBOX } from "./crashArt";
import {
  FERRULE_PATHS,
  LETTERING_GRADIENT,
  LETTERING_PATH,
  SWOOSH_PATH,
  WORDMARK_ASPECT,
  WORDMARK_VIEWBOX,
} from "./brandArt";

interface IconProps {
  size?: number;
  strokeWidth?: number;
}

interface IconBaseProps extends IconProps {
  children: ReactNode;
}

interface MarkBaseProps extends IconBaseProps {
  /** The dark casing painted under the coloured line, in viewBox units. */
  casingWidth?: number;
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
export function HeartIcon(p: IconProps) { return <IconBase {...p}><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.6l-1-1a5.5 5.5 0 0 0-7.8 7.8l1 1L12 21l7.8-7.6 1-1a5.5 5.5 0 0 0 0-7.8Z" /></IconBase>; }
export function EyeIcon(p: IconProps) { return <IconBase {...p}><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" /><circle cx="12" cy="12" r="3" /></IconBase>; }
export function PencilIcon(p: IconProps) { return <IconBase {...p}><path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z" /></IconBase>; }
export function SunIcon(p: IconProps) { return <IconBase {...p}><circle cx="12" cy="12" r="4.5" /><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4" /></IconBase>; }
export function VolumeIcon(p: IconProps) { return <IconBase {...p}><path d="M11 5 6 9H2v6h4l5 4V5Z" /><path d="M15.5 8.5a5 5 0 0 1 0 7" /><path d="M18.5 5.5a9 9 0 0 1 0 13" /></IconBase>; }
export function EyeOffIcon(p: IconProps) { return <IconBase {...p}><path d="M3 3l18 18" /><path d="M10.6 10.6a2 2 0 0 0 2.8 2.8" /><path d="M9.9 5.2A10.7 10.7 0 0 1 12 5c6.5 0 10 7 10 7a17.5 17.5 0 0 1-3.2 4.1" /><path d="M6.6 6.6C3.9 8.5 2 12 2 12s3.5 7 10 7c1.6 0 3-.4 4.3-1" /></IconBase>; }
export function MoonIcon(p: IconProps) { return <IconBase {...p}><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" /></IconBase>; }
export function CrownIcon(p: IconProps) { return <IconBase {...p}><path d="M3 17h18l-1-9-4.5 3.5L12 6l-3.5 5.5L4 8l-1 9Z" /><path d="M4 21h16" /></IconBase>; }
/** An avatar-corner mark (#574): the same outline drawn twice, a dark casing
 * underneath the coloured line.
 *
 * The marks are stroke drawings like the rest of the set (#706) rather than
 * the filled silhouettes they started as. A stroke drawing on its own would
 * dissolve into an arbitrary player colour or an uploaded picture, so the
 * casing takes the job the fill used to do: it separates the mark from
 * whatever is under it while leaving the shape open, which is what makes it
 * read as the same icon language as every other glyph here. Drawing it as a
 * group underneath rather than as `paint-order: stroke` matters for a
 * multi-path glyph — the whole casing is laid down first, so the coloured
 * lines meet each other on top of it instead of each cutting into the next.
 *
 * Colours live in primitives.css (`.avatar-crown`, `.avatar-friend`); the two
 * widths are geometry and stay with the shape. */
function MarkBase({ size = 16, strokeWidth = 2.2, casingWidth = 4, children }: MarkBaseProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      style={{ flex: "none" }}
    >
      <g className="mark-casing" strokeWidth={casingWidth}>{children}</g>
      <g className="mark-line" strokeWidth={strokeWidth}>{children}</g>
    </svg>
  );
}

/** The crown alone, without its base line: the host mark on the avatar's
    top-right (#574). */
export function CrownMarkIcon({ size }: IconProps) {
  return <MarkBase size={size} strokeWidth={2.4} casingWidth={5}><path d="M3 18h18l-1-10-4.5 3.5L12 6l-3.5 5.5L4 8l-1 10Z" /></MarkBase>;
}

/** The friend mark: two heads and shoulders on the avatar's bottom-right.

Not `UsersIcon` at a smaller size. That one is drawn for a name line, where it
sits at 16px on a flat surface; this one has to survive a disc corner at 15px
over any colour. So the front figure is bigger and lower, the back one is
reduced to the two arcs that say "somebody else is there", and the gaps
between them are opened up until the casing underneath (see `MarkBase`) stops
welding them together. */
export function FriendMarkIcon({ size }: IconProps) {
  return (
    <MarkBase size={size} strokeWidth={2.1} casingWidth={3.8}>
      <circle cx="9.5" cy="9" r="4.3" />
      <path d="M2 20.6a7.5 7.5 0 0 1 15 0" />
      <path d="M17.6 6.4a3.4 3.4 0 0 1 0 6.4" />
      <path d="M19 15.4a5.6 5.6 0 0 1 3 4.6" />
    </MarkBase>
  );
}

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
/** The ferrule end sat at x=23.5 with a 2-unit stroke around it, so the tip
    was painted out to x=25.1 and the viewBox clipped it flat. The handle is
    the same drawing pulled 2.4 units back down its own 45° axis, which keeps
    the tip inside 24 with the ~1 unit of margin the rest of the set leaves. */
export function BrushIcon(p: IconProps) { return <IconBase {...p}><path d="M9.06 11.9 18.8 4.2a2 2 0 0 1 3 3l-7.7 9.74" /><path d="M9.5 12.5c-2.5 0-4.5 2-4.5 4.5 0 1.5-1 2.5-2.5 3 1 .8 2.3 1.5 4 1.5 3 0 5.5-2.5 5.5-5.5" /></IconBase>; }
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
export function InfoIcon(p: IconProps) { return <IconBase {...p}><circle cx="12" cy="12" r="9" /><path d="M12 11v5" /><path d="M12 7.5h.01" /></IconBase>; }
export function MailIcon(p: IconProps) { return <IconBase {...p}><rect x="2.5" y="5" width="19" height="14" rx="2" /><path d="m3 7 9 6.5L21 7" /></IconBase>; }
export function DevicesIcon(p: IconProps) { return <IconBase {...p}><rect x="2" y="4" width="15" height="10" rx="2" /><path d="M6 18h7" /><path d="M9.5 14v4" /><rect x="17.5" y="9" width="5" height="9" rx="1.5" /></IconBase>; }
export function ShieldIcon(p: IconProps) { return <IconBase {...p}><path d="M12 2.5 4.5 5.5v6c0 4.7 3.2 8.3 7.5 10 4.3-1.7 7.5-5.3 7.5-10v-6L12 2.5Z" /></IconBase>; }
export function KeyIcon(p: IconProps) { return <IconBase {...p}><circle cx="7.5" cy="15.5" r="4.5" /><path d="m10.7 12.3 9.8-9.8" /><path d="M15.5 7.5 19 11" /><path d="m18 5 3 3" /></IconBase>; }
export function BugIcon(p: IconProps) { return <IconBase {...p}><path d="m8 2 1.88 1.88" /><path d="M14.12 3.88 16 2" /><path d="M9 7.13v-1a3 3 0 1 1 6 0v1" /><path d="M12 20c-3.3 0-6-2.7-6-6v-3a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v3c0 3.3-2.7 6-6 6" /><path d="M12 20v-9" /><path d="M6.53 9C4.6 8.8 3 7.1 3 5" /><path d="M6 13H2" /><path d="M3 21c0-2.1 1.7-3.9 3.8-4" /><path d="M20.97 5c0 2.1-1.6 3.8-3.5 4" /><path d="M22 13h-4" /><path d="M17.2 17c2.1.1 3.8 1.9 3.8 4" /></IconBase>; }
export function ImageIcon(p: IconProps) { return <IconBase {...p}><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.6" /><path d="m21 15-4.5-4.5L6 21" /></IconBase>; }
export function FlagIcon(p: IconProps) { return <IconBase {...p}><path d="M5 21V4" /><path d="M5 4.5h11l-2 4 2 4H5" /></IconBase>; }
export function DiceIcon(p: IconProps) { return <IconBase {...p}><rect x="3" y="3" width="18" height="18" rx="3" /><circle cx="8.2" cy="8.2" r="1.1" fill="currentColor" stroke="none" /><circle cx="15.8" cy="8.2" r="1.1" fill="currentColor" stroke="none" /><circle cx="12" cy="12" r="1.1" fill="currentColor" stroke="none" /><circle cx="8.2" cy="15.8" r="1.1" fill="currentColor" stroke="none" /><circle cx="15.8" cy="15.8" r="1.1" fill="currentColor" stroke="none" /></IconBase>; }

/* ------------------------------------------------------ prompt-language flags
 * Drawn inline so they render identically on every OS. Simplified but
 * recognizable; one per supported prompt language (R-PROMPT registry). */
/* The flags, each in its own colours, taken down a stop.
 *
 * These sit at 18x13 on warm paper, beside crayon indigo, on every lobby card
 * and every row of the language list - and a flag drawn to specification is
 * drawn in the most saturated ink there is. Portugal's #FF0000 against
 * #FFFF00 was the brightest thing on the page by a wide margin.
 *
 * So each colour is mixed toward a warm white by how bright it already reads
 * - saturation times lightness, with a nudge through the yellow-green band
 * the eye takes hardest - which lands heavily on the primaries and barely
 * touches a navy or a deep crimson. Every flag keeps its own palette; nothing
 * is shared between them, because a Spanish red and a French red are not the
 * same red and this is not the place to decide they are. */
const FLAG = {
  ukNavy: "#29427B",
  ukRed: "#CF475C",
  deInk: "#232220",
  deRed: "#DF4342",
  deGold: "#F9DA5A",
  esRed: "#B54447",
  esGold: "#F0D15A",
  frBlue: "#334DA3",
  frRed: "#EC646E",
  itGreen: "#32A166",
  itRed: "#D35860",
  nlRed: "#B84951",
  nlBlue: "#456298",
  ptGreen: "#287927",
  ptRed: "#F84B4A",
  ptYellow: "#F9F85A",
  /* Warm rather than pure, so a white stripe still shows on a white panel. */
  white: "#FDFBF6",
} as const;

const FLAG_SHAPES: Record<string, ReactNode> = {
  en: (
    <>
      <rect width="18" height="13" fill={FLAG.ukNavy} />
      <path d="M0 0 18 13M18 0 0 13" stroke={FLAG.white} strokeWidth="2.6" />
      <path d="M0 0 18 13M18 0 0 13" stroke={FLAG.ukRed} strokeWidth="1.1" />
      <path d="M9 0v13M0 6.5h18" stroke={FLAG.white} strokeWidth="4" />
      <path d="M9 0v13M0 6.5h18" stroke={FLAG.ukRed} strokeWidth="2.2" />
    </>
  ),
  de: (
    <>
      <rect width="18" height="4.33" fill={FLAG.deInk} />
      <rect y="4.33" width="18" height="4.34" fill={FLAG.deRed} />
      <rect y="8.67" width="18" height="4.33" fill={FLAG.deGold} />
    </>
  ),
  es: (
    <>
      <rect width="18" height="13" fill={FLAG.esRed} />
      <rect y="3.25" width="18" height="6.5" fill={FLAG.esGold} />
    </>
  ),
  fr: (
    <>
      <rect width="6" height="13" fill={FLAG.frBlue} />
      <rect x="6" width="6" height="13" fill={FLAG.white} />
      <rect x="12" width="6" height="13" fill={FLAG.frRed} />
    </>
  ),
  it: (
    <>
      <rect width="6" height="13" fill={FLAG.itGreen} />
      <rect x="6" width="6" height="13" fill={FLAG.white} />
      <rect x="12" width="6" height="13" fill={FLAG.itRed} />
    </>
  ),
  nl: (
    <>
      <rect width="18" height="4.33" fill={FLAG.nlRed} />
      <rect y="4.33" width="18" height="4.34" fill={FLAG.white} />
      <rect y="8.67" width="18" height="4.33" fill={FLAG.nlBlue} />
    </>
  ),
  pt: (
    <>
      <rect width="7" height="13" fill={FLAG.ptGreen} />
      <rect x="7" width="11" height="13" fill={FLAG.ptRed} />
      <circle cx="7" cy="6.5" r="2.4" fill={FLAG.ptYellow} stroke={FLAG.ptGreen} strokeWidth="0.6" />
    </>
  ),
};

/**
 * `width` in CSS pixels; the 18x13 artwork scales with it.
 *
 * `fill` hands the sizing to whatever is around it: the flag takes the whole
 * box, keeps no ring and no corners of its own, and lets that box clip it.
 * That is how the language button wears one - the button *is* the flag - and
 * the 0.1% stretch a 61x44 frame asks of 18:13 is not visible at this size.
 */
export function Flag({
  language,
  width = 18,
  fill = false,
}: { language: string; width?: number; fill?: boolean }) {
  const shape = FLAG_SHAPES[language];
  if (!shape) return null;
  if (fill) {
    return (
      <svg
        width="100%"
        height="100%"
        viewBox="0 0 18 13"
        preserveAspectRatio="none"
        aria-hidden="true"
        style={{ display: "block" }}
      >
        {shape}
      </svg>
    );
  }
  return (
    <svg
      width={width}
      /* Exact, not rounded: a box a fraction taller than 18:13 makes the
         artwork letterbox itself inside its own ring, which reads as a gap
         down each side. */
      height={(width * 13) / 18}
      viewBox="0 0 18 13"
      aria-hidden="true"
      style={{
        flex: "none",
        borderRadius: Math.max(2.5, width / 7),
        boxShadow: "0 0 0 1px var(--flag-edge)",
      }}
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

/* The drawing nobody finished, for the not-found page. The geometry is
 * Stefano's Inkscape original, derived into `notFoundArt.ts` by
 * `scripts/brand/derive-assets.mjs` - the same pipeline as the wordmark, so
 * the app and the mockup artboards cannot drift apart.
 *
 * It carries its own colours rather than theme tokens, because it hangs on the
 * canvas sheet and that sheet is white in both themes; the paint is the game's
 * drawing palette, so this is a drawing a player could have made.
 *
 * Decoration, deliberately: the heading says what happened, and an unnamed
 * <svg> that is not aria-hidden is a serious axe violation. */
export function NotFoundDoodle() {
  return (
    <svg
      viewBox={NOT_FOUND_VIEWBOX}
      width="100%"
      height="100%"
      aria-hidden="true"
      style={{ display: "block" }}
    >
      {NOT_FOUND_PATHS.map(({ fill, d }) => (
        <path key={d} d={d} fill={fill} />
      ))}
    </svg>
  );
}

/** The ladybird on the crash page. Same pipeline and same rules as the 404
    drawing: authored in scripts/brand, painted in the drawing palette, hung on
    a white sheet. */
export function BugDoodle() {
  return (
    <svg
      viewBox={CRASH_VIEWBOX}
      width="100%"
      height="100%"
      aria-hidden="true"
      style={{ display: "block" }}
    >
      {CRASH_PATHS.map(({ fill, d }) => (
        <path key={d} d={d} fill={fill} />
      ))}
    </svg>
  );
}

export function Wordmark({ size = 30, decorative = false }: { size?: number; decorative?: boolean }) {
  /* The lockup this replaced was `size`px of display type over a 1px gap and an
   * 8px squiggle, so height tracks that box and the header keeps its metrics. */
  const height = size + 9;
  const width = Math.round(height * WORDMARK_ASPECT);
  /* Both call sites can render on one page; the gradient needs a unique id. */
  const gradientId = `${useId()}-wordmark`;
  return (
    <svg
      width={width}
      height={height}
      viewBox={WORDMARK_VIEWBOX}
      /* Labelled, not decorative, by default: AppHeader renders this as the
       * lobby's <h1>, and an unnamed svg there is an axe `svg-img-alt`
       * violation (serious) plus an empty heading. */
      {...(decorative ? { "aria-hidden": true } : { role: "img", "aria-label": "Sketchy" })}
      style={{ display: "block", color: "var(--brand-wordmark)" }}
    >
      <defs>
        {/* The authored fade from the lettering into the swoosh, retimed onto
          * theme tokens so it works on paper and on slate. */}
        <linearGradient id={gradientId} gradientUnits="userSpaceOnUse" {...LETTERING_GRADIENT}>
          <stop offset="0" stopColor="currentColor" />
          <stop offset="1" stopColor="var(--warm)" />
        </linearGradient>
      </defs>
      <path d={SWOOSH_PATH} style={{ fill: "var(--warm)" }} />
      <path d={LETTERING_PATH} fill={`url(#${gradientId})`} />
      {FERRULE_PATHS.map((d) => (
        <path key={d} d={d} style={{ fill: "var(--brand-ferrule)" }} />
      ))}
    </svg>
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
