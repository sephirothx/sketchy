import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { useEscapeLayer } from "../hooks/useFocusTrap";
import { requestCanvasClear, requestCanvasUndo } from "../lib/canvasCommands";
import {
  DEFAULT_ALLOWED_TOOLS,
  DEFAULT_COLOR_MODE,
  allowsCustomColors,
  firstAllowedColor,
  firstAllowedTool,
  isColorAllowed,
  isPairedPalette,
  isToolAllowed,
  paletteForColorMode,
} from "../lib/drawingRules";
import { useCanvasBudgetStore } from "../store/canvasBudgetStore";
import { useGameStore } from "../store/gameStore";
import { type KeyBindings, useSettingsStore } from "../store/settingsStore";
import type { DrawTool } from "../types";
import { recordRender } from "../lib/renderDiagnostics";
import {
  BrushIcon,
  ChevronDownIcon,
  CircleIcon,
  EraserIcon,
  FillIcon,
  RectIcon,
  TrashIcon,
  TriangleIcon,
  UndoIcon,
} from "./icons";

const PRESET_WIDTHS = [2, 4, 6, 8, 12, 16, 24, 32];

type MobilePanel = "tool" | "color" | "size" | null;

interface ColorSwatchProps {
  color: string;
  selected: boolean;
  onSelect: () => void;
  variant?: string;
  label: string;
  title?: string;
}

/** One palette button. Four toolbars render these; the selected rule lives here. */
function ColorSwatch({ color, selected, onSelect, variant, label, title }: ColorSwatchProps) {
  return (
    <button
      type="button"
      className={`color-swatch${variant ? ` ${variant}` : ""}${selected ? " selected" : ""}`}
      style={{ backgroundColor: color }}
      onClick={onSelect}
      aria-label={label}
      title={title}
    />
  );
}

/** Keys bound to a tool.
 *
 * Every DrawTool names a KeyBindings field, so this indexes directly and a new
 * tool fails to compile until it is bound. It went through a lookup table while
 * the brush's binding was still stored under `pen`; nothing casts here now,
 * which is what keeps a rename from quietly yielding no shortcut.
 */
function toolKeys(bindings: KeyBindings, tool: DrawTool): string[] {
  return bindings[tool] ?? [];
}

const TOOLS: { value: DrawTool; name: string; glyph: React.ReactNode }[] = [
  { value: "brush", name: "Brush", glyph: <BrushIcon size={18} /> },
  { value: "fill", name: "Fill", glyph: <FillIcon size={18} /> },
  { value: "eraser", name: "Eraser", glyph: <EraserIcon size={18} /> },
  { value: "rectangle", name: "Rectangle", glyph: <RectIcon size={18} /> },
  { value: "triangle", name: "Triangle", glyph: <TriangleIcon size={18} /> },
  { value: "ellipse", name: "Ellipse", glyph: <CircleIcon size={18} /> },
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
  recordRender("toolbar");
  const isMobile = useMediaQuery("(max-width: 900px)");
  const fillAvailable = useCanvasBudgetStore((state) => state.fillAvailable);
  const strokeAvailable = useCanvasBudgetStore((state) => state.strokeAvailable);
  // The room's drawing rules. The server refuses a tool or color the host took
  // away, so everything below only spares the drawer from meeting that refusal
  // as a stroke that disappears.
  const allowedTools = useGameStore((state) => state.allowedTools) ?? DEFAULT_ALLOWED_TOOLS;
  const colorMode = useGameStore((state) => state.colorMode) ?? DEFAULT_COLOR_MODE;
  const tools = useMemo(
    () => TOOLS.filter((entry) => isToolAllowed(entry.value, allowedTools)),
    [allowedTools],
  );
  const colors = paletteForColorMode(colorMode);
  const customColorsAllowed = allowsCustomColors(colorMode);
  const paletteClass = isPairedPalette(colorMode) ? "" : " is-flat";
  const disabledReason = (value: DrawTool): string | null => {
    if (value === "fill" && !fillAvailable) {
      return "Fill is unavailable for the rest of this turn";
    }
    // Shapes cost no points, so they outlive the brush.
    if ((value === "brush" || value === "eraser") && !strokeAvailable) {
      return "Drawing by hand is unavailable for the rest of this turn";
    }
    return null;
  };
  const isCustomColor = !colors.includes(color);
  // The eraser paints white regardless of the palette, so nothing reads as chosen.
  const isSelectedColor = (candidate: string) => candidate === color && tool !== "eraser";
  const activeColor = tool === "eraser" ? "#6c757d" : color;
  const [sizePickerOpen, setSizePickerOpen] = useState(false);
  const [mobilePanel, setMobilePanel] = useState<MobilePanel>(null);
  const sizePickerRef = useRef<HTMLDivElement | null>(null);
  const mobileToolbarRef = useRef<HTMLDivElement | null>(null);
  const keyBindings = useSettingsStore((s) => s.keyBindings);

  const prevColorRef = useRef<string>("#ffffff");
  const [recentColors, setRecentColors] = useState<string[]>(["#000000", "#ffffff"]);
  // Kept rather than pruned: a host who turns a restriction back off should
  // find the recent colors where they left them.
  const shownRecentColors = useMemo(
    () => recentColors.filter((c) => isColorAllowed(c, colorMode)),
    [recentColors, colorMode],
  );

  const handleSelectColor = useCallback(
    (newColor: string) => {
      if (newColor !== color) {
        prevColorRef.current = color;
        setRecentColors((prev) => [newColor, ...prev.filter((c) => c !== newColor)].slice(0, 6));
      }
      onColorChange(newColor);
      if (tool === "eraser") onToolChange("brush");
    },
    [color, onColorChange, tool, onToolChange],
  );

  function getToolBadge(toolValue: DrawTool): string {
    const keys = toolKeys(keyBindings, toolValue);
    return keys.length > 0 ? keys[0].toUpperCase() : "";
  }

  function getToolLabel(toolValue: DrawTool, name: string): string {
    const keyStr = toolKeys(keyBindings, toolValue).map((k) => k.toUpperCase()).join(" / ");
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
  const activeTool = tools.find((t) => t.value === tool) ?? tools[0];

  const handleWidthChange = useCallback(
    (newWidth: number) => {
      onBrushWidthChange(newWidth);
      if (tool === "fill") {
        onToolChange("brush");
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
        if (!isColorAllowed(targetColor, colorMode)) return;
        prevColorRef.current = color;
        onColorChange(targetColor);
        if (tool === "eraser") onToolChange("brush");
        return;
      }

      const boundTool = tools.find((entry) => toolKeys(kb, entry.value).includes(key));
      if (boundTool) {
        onToolChange(boundTool.value);
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
  }, [brushWidth, color, colorMode, defaultIdx, handleWidthChange, onColorChange, onToolChange, tool, tools]);

  // The host can tighten the rules while the toolbar is on screen, and a
  // drawer arriving mid-turn brings whatever they last held. Either way the
  // selection can be something this room no longer offers, so put it back on
  // something it does - otherwise the next stroke is one the server refuses.
  useEffect(() => {
    if (!isToolAllowed(tool, allowedTools)) onToolChange(firstAllowedTool(allowedTools));
  }, [allowedTools, onToolChange, tool]);

  useEffect(() => {
    if (!isColorAllowed(color, colorMode)) onColorChange(firstAllowedColor(colorMode));
  }, [color, colorMode, onColorChange]);

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
    const dock = typeof document !== "undefined"
      ? document.getElementById("room-shell-dock")
      : null;
    // Collapsed controls, as before: one chip opens the tools, one the
    // colours, one the size. The dock still renders after the chat region,
    // so the strip sits at the bottom of the screen under the thumb.
    const mobileToolbar = (
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
              <span className="toolbar-mobile-chip-caret" aria-hidden="true"><ChevronDownIcon size={12} /></span>
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
              <span className="toolbar-mobile-chip-caret" aria-hidden="true"><ChevronDownIcon size={12} /></span>
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
              <UndoIcon size={18} />
            </button>
            <button
              type="button"
              className="toolbar-mobile-chip toolbar-mobile-clear"
              aria-label="Clear canvas"
              title="Clear canvas"
              onClick={requestCanvasClear}
            >
              <TrashIcon size={18} />
            </button>
          </div>

          {mobilePanel === "tool" && (
            <div id={mobileToolPanelId} className="toolbar-mobile-popover" role="group" aria-label="Choose tool">
              <div className="toolbar-mobile-tools">
                {tools.map((t) => (
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
                {colors.map((c) => (
                  <ColorSwatch
                    key={c}
                    color={c}
                    selected={isSelectedColor(c)}
                    variant="toolbar-mobile-swatch-btn"
                    label={`color ${c}`}
                    onSelect={() => {
                      handleSelectColor(c);
                      setMobilePanel(null);
                    }}
                  />
                ))}
                {customColorsAllowed && (
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
                )}
              </div>
              {shownRecentColors.length > 0 && (
                <div className="toolbar-mobile-recent" aria-label="Recent colors">
                  {shownRecentColors.map((c) => (
                    <ColorSwatch
                      key={c}
                      color={c}
                      selected={isSelectedColor(c)}
                      variant="toolbar-mobile-swatch-btn"
                      label={`Recent color ${c}`}
                      onSelect={() => {
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
    return dock ? createPortal(mobileToolbar, dock) : mobileToolbar;
  }

  return (
    <div className="toolbar-container">
        <div className="toolbar">
          <div className="toolbar-group toolbar-tools" aria-label="Drawing tools">
            {tools.map((t) => {
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

          <div className={`toolbar-group toolbar-colors${paletteClass}`} aria-label="Color palette">
            {colors.map((c) => (
              <ColorSwatch
                key={c}
                color={c}
                selected={isSelectedColor(c)}
                label={`color ${c}`}
                title={`Color ${c}`}
                onSelect={() => handleSelectColor(c)}
              />
            ))}
            {customColorsAllowed && (
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
            )}
          </div>

          {shownRecentColors.length > 0 && (
            <>
              <div className="toolbar-divider" />
              <div className="toolbar-group recent-colors-group" aria-label="Recent colors" title="Recent colors (Press X to swap color)">
                <span className="recent-colors-label">Recent:</span>
                {shownRecentColors.map((c) => (
                  <ColorSwatch
                    key={c}
                    color={c}
                    selected={isSelectedColor(c)}
                    variant="recent-swatch"
                    label={`Recent color ${c}`}
                    title={`Recent color ${c} (Press X to swap)`}
                    onSelect={() => handleSelectColor(c)}
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
              <UndoIcon size={18} />
              <span>Undo</span>
            </button>
            <button
              className="toolbar-action-button clear-button"
              onClick={requestCanvasClear}
              title="Clear canvas"
            >
              <TrashIcon size={18} />
              <span>Clear</span>
            </button>
          </div>
        </div>
      </div>
  );
}
