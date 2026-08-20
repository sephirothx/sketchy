import { useCallback, useEffect, useRef, useState } from "react";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { useEscapeLayer } from "../hooks/useFocusTrap";
import { requestCanvasClear, requestCanvasUndo } from "../lib/canvasCommands";
import { useCanvasBudgetStore } from "../store/canvasBudgetStore";
import { type KeyBindings, useSettingsStore } from "../store/settingsStore";
import type { DrawTool } from "../types";
import { recordRender } from "../lib/renderDiagnostics";

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

const PRESET_WIDTHS = [2, 4, 6, 8, 12, 16, 24, 32];

type MobilePanel = "tool" | "color" | "size" | null;

const TOOLS: { value: DrawTool; name: string; glyph: React.ReactNode }[] = [
  {
    value: "pen",
    name: "Pen",
    glyph: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z" />
      </svg>
    ),
  },
  {
    value: "fill",
    name: "Fill",
    glyph: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="m19 11-8-8-8.6 8.6a2 2 0 0 0 0 2.8l5.2 5.2a2 2 0 0 0 2.8 0L19 11Z" />
        <path d="m5 2 5 5" />
        <path d="M2 13h15" />
        <path d="M22 20a2 2 0 1 1-4 0c0-1.6 2-4 2-4s2 2.4 2 4Z" />
      </svg>
    ),
  },
  {
    value: "eraser",
    name: "Eraser",
    glyph: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="m7 21-4.3-4.3a1 1 0 0 1 0-1.4l12-12a1 1 0 0 1 1.4 0l4.3 4.3a1 1 0 0 1 0 1.4L8.4 21a1 1 0 0 1-1.4 0Z" />
        <path d="m22 21-15 0" />
        <path d="m5 11 9 9" />
      </svg>
    ),
  },
  {
    value: "rectangle",
    name: "Rectangle",
    glyph: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="3" width="18" height="18" rx="2" />
      </svg>
    ),
  },
  {
    value: "triangle",
    name: "Triangle",
    glyph: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M13.73 4a2 2 0 0 0-3.46 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
      </svg>
    ),
  },
  {
    value: "ellipse",
    name: "Ellipse",
    glyph: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="9" />
      </svg>
    ),
  },
];

interface ToolbarProps {
  color: string;
  onColorChange: (color: string) => void;
  brushWidth: number;
  onBrushWidthChange: (width: number) => void;
  tool: DrawTool;
  onToolChange: (tool: DrawTool) => void;
}

function UndoIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 7v6h6" />
      <path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13" />
    </svg>
  );
}

function ClearIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 6h18" />
      <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" />
      <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" />
    </svg>
  );
}

export function Toolbar({
  color,
  onColorChange,
  brushWidth,
  onBrushWidthChange,
  tool,
  onToolChange,
}: ToolbarProps) {
  recordRender("toolbar");
  const isMobile = useMediaQuery("(max-width: 900px)");
  const fillAvailable = useCanvasBudgetStore((state) => state.fillAvailable);
  const disabledReason = (value: DrawTool): string | null => (
    value === "fill" && !fillAvailable
      ? "Fill is unavailable for the rest of this turn"
      : null
  );
  const isCustomColor = !COLORS.includes(color);
  const activeColor = tool === "eraser" ? "#6c757d" : color;
  const [sizePickerOpen, setSizePickerOpen] = useState(false);
  const [mobilePanel, setMobilePanel] = useState<MobilePanel>(null);
  const sizePickerRef = useRef<HTMLDivElement | null>(null);
  const mobileToolbarRef = useRef<HTMLDivElement | null>(null);
  const keyBindings = useSettingsStore((s) => s.keyBindings);

  const prevColorRef = useRef<string>("#ffffff");
  const [recentColors, setRecentColors] = useState<string[]>(["#000000", "#ffffff"]);

  const handleSelectColor = useCallback(
    (newColor: string) => {
      if (newColor !== color) {
        prevColorRef.current = color;
        setRecentColors((prev) => [newColor, ...prev.filter((c) => c !== newColor)].slice(0, 6));
      }
      onColorChange(newColor);
      if (tool === "eraser") onToolChange("pen");
    },
    [color, onColorChange, tool, onToolChange],
  );

  function getToolBadge(toolValue: DrawTool): string {
    const keys = keyBindings[toolValue as keyof KeyBindings];
    return keys && keys.length > 0 ? keys[0].toUpperCase() : "";
  }

  function getToolLabel(toolValue: DrawTool, name: string): string {
    const keys = keyBindings[toolValue as keyof KeyBindings];
    const keyStr = keys && keys.length > 0 ? keys.map((k) => k.toUpperCase()).join(" / ") : "";
    return keyStr ? `${name} (${keyStr})` : name;
  }

  const labelPrefix = tool === "eraser" ? "Eraser" : "Brush";
  const sizePickerId = "brush-size-popover";
  const mobileToolPanelId = "toolbar-mobile-tool-panel";
  const mobileColorPanelId = "toolbar-mobile-color-panel";
  const mobileSizePanelId = "toolbar-mobile-size-panel";
  const currentIdx = PRESET_WIDTHS.indexOf(brushWidth);
  const defaultIdx = tool === "eraser" ? 6 : 2;
  const sliderValue = currentIdx !== -1 ? currentIdx : defaultIdx;
  const activeTool = TOOLS.find((t) => t.value === tool) ?? TOOLS[0];

  const handleWidthChange = useCallback(
    (newWidth: number) => {
      onBrushWidthChange(newWidth);
      if (tool === "fill") {
        onToolChange("pen");
      }
    },
    [onBrushWidthChange, tool, onToolChange],
  );

  const toggleMobilePanel = useCallback((panel: Exclude<MobilePanel, null>) => {
    setMobilePanel((prev) => (prev === panel ? null : panel));
  }, []);

  useEscapeLayer(sizePickerOpen || mobilePanel !== null, () => {
    setSizePickerOpen(false);
    setMobilePanel(null);
  });

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      const target = e.target as Node;
      if (sizePickerRef.current && !sizePickerRef.current.contains(target)) {
        setSizePickerOpen(false);
      }
      if (mobileToolbarRef.current && !mobileToolbarRef.current.contains(target)) {
        setMobilePanel(null);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) return;

      const kb = useSettingsStore.getState().keyBindings;
      const key = e.key.toLowerCase();

      const isUndo =
        ((e.metaKey || e.ctrlKey) && !e.shiftKey && key === "z") ||
        (kb.undo && kb.undo.includes(key));
      if (isUndo) {
        e.preventDefault();
        requestCanvasUndo();
        return;
      }

      if (e.metaKey || e.ctrlKey || e.altKey) return;

      if (key === "x") {
        const targetColor = prevColorRef.current;
        prevColorRef.current = color;
        onColorChange(targetColor);
        if (tool === "eraser") onToolChange("pen");
        return;
      }

      if (kb.pen.includes(key)) {
        onToolChange("pen");
      } else if (kb.eraser.includes(key)) {
        onToolChange("eraser");
      } else if (kb.fill.includes(key)) {
        onToolChange("fill");
      } else if (kb.rectangle.includes(key)) {
        onToolChange("rectangle");
      } else if (kb.ellipse.includes(key)) {
        onToolChange("ellipse");
      } else if (kb.triangle.includes(key)) {
        onToolChange("triangle");
      } else if (kb.brushDecrease.includes(key)) {
        const idx = PRESET_WIDTHS.indexOf(brushWidth);
        if (idx > 0) {
          handleWidthChange(PRESET_WIDTHS[idx - 1]);
        } else if (idx === -1) {
          handleWidthChange(PRESET_WIDTHS[0]);
        }
      } else if (kb.brushIncrease.includes(key)) {
        const idx = PRESET_WIDTHS.indexOf(brushWidth);
        if (idx >= 0 && idx < PRESET_WIDTHS.length - 1) {
          handleWidthChange(PRESET_WIDTHS[idx + 1]);
        } else if (idx === -1) {
          handleWidthChange(PRESET_WIDTHS[defaultIdx]);
        }
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [brushWidth, color, defaultIdx, handleWidthChange, onColorChange, onToolChange, tool]);

  const sizePreview = (
    <span
      style={{
        width: Math.max(5, Math.min(20, brushWidth * 0.65 + 3)),
        height: Math.max(5, Math.min(20, brushWidth * 0.65 + 3)),
        backgroundColor: activeColor,
      }}
      className="width-dot"
    />
  );

  const sizeSlider = (
    <div className="brush-slider-popover" id={sizePickerId} role="group" aria-label={`Adjust ${labelPrefix.toLowerCase()} size`}>
      <div className="slider-top-preview">
        <span
          className="preview-dot"
          style={{
            width: Math.max(4, Math.min(26, brushWidth * 0.7 + 3)),
            height: Math.max(4, Math.min(26, brushWidth * 0.7 + 3)),
            backgroundColor: activeColor,
          }}
        />
        <span className="preview-readout">{brushWidth}px</span>
      </div>
      <div className="slider-track-wrapper">
        <input
          type="range"
          min="0"
          max={PRESET_WIDTHS.length - 1}
          step="1"
          value={sliderValue}
          onChange={(e) => handleWidthChange(PRESET_WIDTHS[Number(e.target.value)])}
          className="vertical-brush-slider"
          aria-label={`${labelPrefix} size snapping slider`}
        />
      </div>
    </div>
  );

  if (isMobile) {
    return (
      <div className="toolbar-container toolbar-mobile" ref={mobileToolbarRef} data-testid="toolbar-mobile">
          <div className="toolbar toolbar-mobile-strip" role="toolbar" aria-label="Drawing tools">
            <button
              type="button"
              className={`toolbar-mobile-chip toolbar-mobile-tool-chip${mobilePanel === "tool" ? " active" : ""}`}
              aria-label={`Choose tool, current: ${activeTool.name}`}
              aria-expanded={mobilePanel === "tool"}
              aria-haspopup="true"
              aria-controls={mobileToolPanelId}
              title="Choose tool"
              onClick={() => toggleMobilePanel("tool")}
            >
              <span className="tool-glyph">{activeTool.glyph}</span>
              <span className="toolbar-mobile-chip-caret" aria-hidden="true">▾</span>
            </button>

            <button
              type="button"
              className={`toolbar-mobile-chip toolbar-mobile-color-chip${mobilePanel === "color" ? " active" : ""}`}
              aria-label={`Choose color, current ${color}`}
              aria-expanded={mobilePanel === "color"}
              aria-haspopup="true"
              aria-controls={mobileColorPanelId}
              title="Choose color"
              onClick={() => toggleMobilePanel("color")}
            >
              <span className="toolbar-mobile-swatch" style={{ backgroundColor: activeColor }} />
              <span className="toolbar-mobile-chip-caret" aria-hidden="true">▾</span>
            </button>

            <button
              type="button"
              className={`toolbar-mobile-chip${mobilePanel === "size" ? " active" : ""}`}
              aria-label={`${labelPrefix} size ${brushWidth}px`}
              aria-expanded={mobilePanel === "size"}
              aria-haspopup="true"
              aria-controls={mobileSizePanelId}
              onClick={() => toggleMobilePanel("size")}
            >
              {sizePreview}
              <span className="size-text-readout">{brushWidth}</span>
            </button>

            <span className="toolbar-mobile-sep" aria-hidden="true" />

            <button
              type="button"
              className="toolbar-mobile-chip"
              aria-label="Undo last stroke"
              title="Undo"
              onClick={requestCanvasUndo}
            >
              <UndoIcon />
            </button>
            <button
              type="button"
              className="toolbar-mobile-chip toolbar-mobile-clear"
              aria-label="Clear canvas"
              title="Clear canvas"
              onClick={requestCanvasClear}
            >
              <ClearIcon />
            </button>
          </div>

          {mobilePanel === "tool" && (
            <div id={mobileToolPanelId} className="toolbar-mobile-popover" role="group" aria-label="Choose tool">
              <div className="toolbar-mobile-tools">
                {TOOLS.map((t) => (
                  <button
                    key={t.value}
                    type="button"
                    className={`tool-button toolbar-mobile-tool${t.value === tool ? " selected" : ""}`}
                    disabled={disabledReason(t.value) !== null}
                    aria-label={disabledReason(t.value) ?? t.name}
                    onClick={() => {
                      onToolChange(t.value);
                      setMobilePanel(null);
                    }}
                  >
                    <span className="tool-glyph">{t.glyph}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {mobilePanel === "color" && (
            <div id={mobileColorPanelId} className="toolbar-mobile-popover" role="group" aria-label="Choose color">
              <div className="toolbar-mobile-colors">
                {COLORS.map((c) => (
                  <button
                    key={c}
                    type="button"
                    className={`color-swatch toolbar-mobile-swatch-btn${c === color && tool !== "eraser" ? " selected" : ""}`}
                    style={{ backgroundColor: c }}
                    aria-label={`color ${c}`}
                    onClick={() => {
                      handleSelectColor(c);
                      setMobilePanel(null);
                    }}
                  />
                ))}
                <label
                  className={`color-swatch color-swatch-custom toolbar-mobile-swatch-btn${isCustomColor && tool !== "eraser" ? " selected" : ""}`}
                  style={isCustomColor ? { backgroundColor: color, backgroundImage: "none" } : undefined}
                  title="Choose custom color"
                >
                  <input
                    type="color"
                    value={color}
                    onChange={(e) => {
                      handleSelectColor(e.target.value);
                      setMobilePanel(null);
                    }}
                    aria-label="Choose custom color"
                  />
                </label>
              </div>
              {recentColors.length > 0 && (
                <div className="toolbar-mobile-recent" aria-label="Recent colors">
                  {recentColors.map((c) => (
                    <button
                      key={c}
                      type="button"
                      className={`color-swatch toolbar-mobile-swatch-btn${c === color && tool !== "eraser" ? " selected" : ""}`}
                      style={{ backgroundColor: c }}
                      aria-label={`Recent color ${c}`}
                      onClick={() => {
                        handleSelectColor(c);
                        setMobilePanel(null);
                      }}
                    />
                  ))}
                </div>
              )}
            </div>
          )}

          {mobilePanel === "size" && (
            <div id={mobileSizePanelId} className="toolbar-mobile-popover toolbar-mobile-size-popover">
              {sizeSlider}
            </div>
          )}
      </div>
    );
  }

  return (
    <div className="toolbar-container">
        <div className="toolbar">
          <div className="toolbar-group toolbar-tools" aria-label="Drawing tools">
            {TOOLS.map((t) => {
              const unavailable = disabledReason(t.value);
              const label = unavailable ?? getToolLabel(t.value, t.name);
              const badge = getToolBadge(t.value);
              return (
                <button
                  key={t.value}
                  className={`tool-button${t.value === tool ? " selected" : ""}`}
                  onClick={() => onToolChange(t.value)}
                  disabled={unavailable !== null}
                  aria-label={label}
                  title={label}
                >
                  <span className="tool-glyph">{t.glyph}</span>
                  {badge && <span className="shortcut-badge">{badge}</span>}
                </button>
              );
            })}
          </div>

          <div className="toolbar-divider" />

          <div className="toolbar-group brush-size-dropdown" ref={sizePickerRef}>
            <button
              type="button"
              className={`brush-size-trigger${sizePickerOpen ? " active" : ""}`}
              onClick={() => setSizePickerOpen((prev) => !prev)}
              aria-label={`${labelPrefix} size ${brushWidth}px`}
              aria-expanded={sizePickerOpen}
              aria-haspopup="true"
              aria-controls={sizePickerId}
              title={`${labelPrefix} size: ${brushWidth}px ([ / ])`}
            >
              {sizePreview}
              <span className="size-text-readout">{brushWidth}px</span>
            </button>
            {sizePickerOpen && sizeSlider}
          </div>

          <div className="toolbar-divider" />

          <div className="toolbar-group toolbar-colors" aria-label="Color palette">
            {COLORS.map((c) => (
              <button
                key={c}
                className={`color-swatch${c === color && tool !== "eraser" ? " selected" : ""}`}
                style={{ backgroundColor: c }}
                onClick={() => handleSelectColor(c)}
                aria-label={`color ${c}`}
                title={`Color ${c}`}
              />
            ))}
            <label
              className={`color-swatch color-swatch-custom${isCustomColor && tool !== "eraser" ? " selected" : ""}`}
              style={isCustomColor ? { backgroundColor: color, backgroundImage: "none" } : undefined}
              title="Choose custom color"
            >
              <input
                type="color"
                value={color}
                onChange={(e) => handleSelectColor(e.target.value)}
                aria-label="Choose custom color"
              />
            </label>
          </div>

          {recentColors.length > 0 && (
            <>
              <div className="toolbar-divider" />
              <div className="toolbar-group recent-colors-group" aria-label="Recent colors" title="Recent colors (Press X to swap color)">
                <span className="recent-colors-label">Recent:</span>
                {recentColors.map((c) => (
                  <button
                    key={c}
                    type="button"
                    className={`color-swatch recent-swatch${c === color && tool !== "eraser" ? " selected" : ""}`}
                    style={{ backgroundColor: c }}
                    onClick={() => handleSelectColor(c)}
                    aria-label={`Recent color ${c}`}
                    title={`Recent color ${c} (Press X to swap)`}
                  />
                ))}
              </div>
            </>
          )}

          <div className="toolbar-divider" />

          <div className="toolbar-group toolbar-actions" aria-label="Canvas actions">
            <button
              className="toolbar-action-button undo-button"
              onClick={requestCanvasUndo}
              title="Undo last stroke (Ctrl+Z)"
            >
              <UndoIcon />
              <span>Undo</span>
            </button>
            <button
              className="toolbar-action-button clear-button"
              onClick={requestCanvasClear}
              title="Clear canvas"
            >
              <ClearIcon />
              <span>Clear</span>
            </button>
          </div>
        </div>
      </div>
  );
}
