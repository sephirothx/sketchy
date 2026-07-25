import { useEffect } from "react";
import { socket } from "../lib/socket";
import type { DrawTool } from "../types";

// Each pair is [light shade, dark shade] for the same color family, laid out
// as two rows of matching columns (mirroring skribbl.io's palette).
const COLOR_PAIRS: readonly (readonly [string, string])[] = [
  ["#ffffff", "#000000"],
  ["#c1c1c1", "#4c4c4c"],
  ["#ed1c24", "#7f0000"],
  ["#ff7f27", "#a0522d"],
  ["#fff200", "#c9a227"],
  ["#b5e61d", "#2d5b1e"],
  ["#22b14c", "#1c6b5a"],
  ["#7ac9e8", "#2e5090"],
  ["#3f48cc", "#1b1b6e"],
  ["#a349a4", "#5c2d91"],
  ["#ec6ea8", "#7b3f61"],
  ["#ffae85", "#a9714b"],
  ["#c69c6d", "#5b3a1e"],
];

const COLORS = COLOR_PAIRS.flat();

const WIDTHS = [2, 4, 8, 16];

const TOOLS: { value: DrawTool; label: string; glyph: React.ReactNode }[] = [
  { value: "pen", label: "Pen (P / 1)", glyph: "\u270e" },
  {
    value: "eraser",
    label: "Eraser (E / 2)",
    glyph: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="m7 21-4.3-4.3a1 1 0 0 1 0-1.4l12-12a1 1 0 0 1 1.4 0l4.3 4.3a1 1 0 0 1 0 1.4L8.4 21a1 1 0 0 1-1.4 0Z"/>
        <path d="m22 21-15 0"/>
        <path d="m5 11 9 9"/>
      </svg>
    ),
  },
  { value: "fill", label: "Fill (F / 3)", glyph: "\u{1FAA3}" },
  { value: "rectangle", label: "Rectangle (R / 4)", glyph: "\u25a1" },
  { value: "ellipse", label: "Ellipse (C / 5)", glyph: "\u25ef" },
  { value: "triangle", label: "Triangle (T / 6)", glyph: "\u25b3" },
];

interface ToolbarProps {
  color: string;
  onColorChange: (color: string) => void;
  brushWidth: number;
  onBrushWidthChange: (width: number) => void;
  tool: DrawTool;
  onToolChange: (tool: DrawTool) => void;
}

export function Toolbar({
  color,
  onColorChange,
  brushWidth,
  onBrushWidthChange,
  tool,
  onToolChange,
}: ToolbarProps) {
  const isCustomColor = !COLORS.includes(color);

  // Keyboard shortcuts (tool switching, brush sizing, Ctrl+Z undo) while drawing.
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) return;

      if ((e.metaKey || e.ctrlKey) && !e.shiftKey && e.key.toLowerCase() === "z") {
        e.preventDefault();
        socket.emit("undo_stroke", {});
        return;
      }

      if (e.metaKey || e.ctrlKey || e.altKey) return;

      const key = e.key.toLowerCase();
      if (key === "p" || key === "1") {
        onToolChange("pen");
      } else if (key === "e" || key === "2") {
        onToolChange("eraser");
      } else if (key === "f" || key === "3") {
        onToolChange("fill");
      } else if (key === "r" || key === "4") {
        onToolChange("rectangle");
      } else if (key === "c" || key === "5") {
        onToolChange("ellipse");
      } else if (key === "t" || key === "6") {
        onToolChange("triangle");
      } else if (key === "[") {
        const idx = WIDTHS.indexOf(brushWidth);
        if (idx > 0) onBrushWidthChange(WIDTHS[idx - 1]);
      } else if (key === "]") {
        const idx = WIDTHS.indexOf(brushWidth);
        if (idx >= 0 && idx < WIDTHS.length - 1) onBrushWidthChange(WIDTHS[idx + 1]);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [brushWidth, onBrushWidthChange, onToolChange]);

  return (
    <div className="toolbar">
      <div className="toolbar-tools">
        {TOOLS.map((t) => (
          <button
            key={t.value}
            className={`tool-button${t.value === tool ? " selected" : ""}`}
            onClick={() => onToolChange(t.value)}
            aria-label={t.label}
            title={t.label}
          >
            {t.glyph}
          </button>
        ))}
      </div>
      <div className="toolbar-colors">
        {COLORS.map((c) => (
          <button
            key={c}
            className={`color-swatch${c === color ? " selected" : ""}`}
            style={{ backgroundColor: c }}
            onClick={() => onColorChange(c)}
            aria-label={`color ${c}`}
          />
        ))}
        <label
          className={`color-swatch color-swatch-custom${isCustomColor ? " selected" : ""}`}
          style={isCustomColor ? { backgroundColor: color, backgroundImage: "none" } : undefined}
          title="Choose any color"
        >
          <input
            type="color"
            value={color}
            onChange={(e) => onColorChange(e.target.value)}
            aria-label="Choose any color"
          />
        </label>
      </div>
      <div className="toolbar-widths">
        {WIDTHS.map((w) => (
          <button
            key={w}
            className={`width-swatch${w === brushWidth ? " selected" : ""}`}
            onClick={() => onBrushWidthChange(w)}
          >
            <span style={{ width: w, height: w }} className="width-dot" />
          </button>
        ))}
      </div>
      <button
        className="toolbar-action-button"
        onClick={() => socket.emit("undo_stroke", {})}
        title="Undo (Ctrl+Z)"
      >
        Undo
      </button>
      <button className="toolbar-action-button" onClick={() => socket.emit("clear_canvas", {})}>
        Clear
      </button>
    </div>
  );
}
