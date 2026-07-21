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

const TOOLS: { value: DrawTool; label: string; glyph: string }[] = [
  { value: "pen", label: "Pen", glyph: "\u270e" },
  { value: "rectangle", label: "Rectangle", glyph: "\u25a1" },
  { value: "ellipse", label: "Ellipse", glyph: "\u25ef" },
  { value: "triangle", label: "Triangle", glyph: "\u25b3" },
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

  // Ctrl+Z / Cmd+Z triggers undo, mirroring the toolbar button. This effect
  // is only mounted while the toolbar itself is (i.e. while it's this
  // player's turn to draw), so it can never fire for guessers.
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (!(e.metaKey || e.ctrlKey) || e.shiftKey || e.key.toLowerCase() !== "z") return;
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")) return;
      e.preventDefault();
      socket.emit("undo_stroke", {});
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

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
