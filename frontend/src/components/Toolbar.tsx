import { socket } from "../lib/socket";
import type { DrawTool } from "../types";

const COLORS = [
  "#000000",
  "#ffffff",
  "#e03131",
  "#f08c00",
  "#f5d400",
  "#2f9e44",
  "#1971c2",
  "#7048e8",
  "#a3384a",
  "#5c5f66",
];

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
      <button className="clear-button" onClick={() => socket.emit("clear_canvas", {})}>
        Clear
      </button>
    </div>
  );
}
