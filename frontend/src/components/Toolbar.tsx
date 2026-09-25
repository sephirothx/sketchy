import { memo, useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { useEscapeLayer } from "../hooks/useFocusTrap";
import { useToolbarLayout } from "../hooks/useToolbarLayout";
import { requestCanvasClear, requestCanvasUndo } from "../lib/canvasCommands";
import { ARRANGEMENTS, arrangementOf, type ToolbarGroup } from "../lib/toolbarLayout";
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
  DownloadIcon,
  EraserIcon,
  FillIcon,
  RectIcon,
  TrashIcon,
  TriangleIcon,
  UndoIcon,
} from "./icons";
import { ui } from "../content/ui/index.ts";
import { BRUSH_SIZES, DEFAULT_ERASER_SIZE, isBrushSize, stopPosition } from "../lib/brushSizes";
import { useLocaleRerender } from "../hooks/useLocaleRerender";
import "../styles/lazy/toolbar.css";


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

/** Whether the platform's own undo is Command-Z rather than Ctrl-Z. */
function onApplePlatform(): boolean {
  if (typeof navigator === "undefined") return false;
  const platform = (navigator as Navigator & { userAgentData?: { platform?: string } }).userAgentData?.platform
    ?? navigator.platform ?? "";
  return /mac|iphone|ipad/i.test(platform);
}

/** The keys that undo, as a title shows them: the player's own binding (they
    are rebindable, so never a literal), then the platform's shortcut, which the
    handler below always honours as well. */
function undoKeys(bindings: KeyBindings): string {
  // Not copy: the Command key's symbol, the same in every language.
  const platformUndo = onApplePlatform() ? "\u2318Z" : `${ui.toolbar.ctrlKey}+Z`;
  return [...bindings.undo.map((key) => key.toUpperCase()), platformUndo].join(" / ");
}

/** The keys that step the size down and up, from the player's bindings. */
function sizeKeys(bindings: KeyBindings): string {
  return [...bindings.brushDecrease, ...bindings.brushIncrease].map((key) => key.toUpperCase()).join(" / ");
}

const TOOLS: { value: DrawTool; name: string; glyph: React.ReactNode }[] = [
  { value: "brush", get name() { return ui.toolbar.brush; }, glyph: <BrushIcon size={18} /> },
  { value: "fill", get name() { return ui.toolbar.fill; }, glyph: <FillIcon size={18} /> },
  { value: "eraser", get name() { return ui.toolbar.eraser; }, glyph: <EraserIcon size={18} /> },
  { value: "rectangle", get name() { return ui.toolbar.rectangle; }, glyph: <RectIcon size={18} /> },
  { value: "triangle", get name() { return ui.toolbar.triangle; }, glyph: <TriangleIcon size={18} /> },
  { value: "ellipse", get name() { return ui.toolbar.ellipse; }, glyph: <CircleIcon size={18} /> },
];

interface ToolbarProps {
  color: string;
  onColorChange: (color: string) => void;
  brushWidth: number;
  onBrushWidthChange: (width: number) => void;
  tool: DrawTool;
  onToolChange: (tool: DrawTool) => void;
  /**
   * For the scratch pad (#829): every tool and colour whatever room this is,
   * no turn's budget, and drawn where it is mounted rather than in the phone
   * room's dock - which is under the card the pad sits on.
   */
  scratchPad?: boolean;
  /** A Save beside Undo and Clear, for a canvas with no room menu to save it from. */
  onSave?: () => void;
}

export const Toolbar = memo(function Toolbar({
  color,
  onColorChange,
  brushWidth,
  onBrushWidthChange,
  tool,
  onToolChange,
  scratchPad = false,
  onSave,
}: ToolbarProps) {
  useLocaleRerender();
  recordRender("toolbar");
  const isMobile = useMediaQuery("(max-width: 900px)");
  const fillAvailable = useCanvasBudgetStore((state) => scratchPad || state.fillAvailable);
  const strokeAvailable = useCanvasBudgetStore((state) => scratchPad || state.strokeAvailable);
  // The room's drawing rules. The server refuses a tool or color the host took
  // away, so everything below only spares the drawer from meeting that refusal
  // as a stroke that disappears.
  const roomTools = useGameStore((state) => state.allowedTools);
  const roomColorMode = useGameStore((state) => state.colorMode);
  const allowedTools = (scratchPad ? null : roomTools) ?? DEFAULT_ALLOWED_TOOLS;
  const colorMode = (scratchPad ? null : roomColorMode) ?? DEFAULT_COLOR_MODE;
  const tools = useMemo(
    () => TOOLS.filter((entry) => isToolAllowed(entry.value, allowedTools)),
    [allowedTools],
  );
  const colors = paletteForColorMode(colorMode);
  const customColorsAllowed = allowsCustomColors(colorMode);
  const paletteClass = isPairedPalette(colorMode) ? "" : " is-flat";
  const disabledReason = (value: DrawTool): string | null => {
    if (value === "fill" && !fillAvailable) {
      return ui.toolbar.fillIsUnavailableForThe;
    }
    // Shapes cost no points, so they outlive the brush.
    if ((value === "brush" || value === "eraser") && !strokeAvailable) {
      return ui.toolbar.drawingByHandIsUnavailable;
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
  const cardRef = useRef<HTMLDivElement | null>(null);
  const keyBindings = useSettingsStore((s) => s.keyBindings);
  // Above the breakpoint the column decides: the full toolbar in whichever
  // arrangement fits, or the phone's strip where not even the palette does.
  const layout = useToolbarLayout(!isMobile, cardRef, mobileToolbarRef);
  const compact = isMobile || layout === "compact";

  // Each form has its own popovers. One left open while the other is on
  // screen would be invisible, and still holding Escape.
  if (!compact && mobilePanel !== null) setMobilePanel(null);
  if (compact && sizePickerOpen) setSizePickerOpen(false);

  const handleSelectColor = useCallback(
    (newColor: string) => {
      onColorChange(newColor);
      if (tool === "eraser") onToolChange("brush");
    },
    [onColorChange, tool, onToolChange],
  );

  function getToolBadge(toolValue: DrawTool): string {
    const keys = toolKeys(keyBindings, toolValue);
    return keys.length > 0 ? keys[0].toUpperCase() : "";
  }

  function getToolLabel(toolValue: DrawTool, name: string): string {
    const keyStr = toolKeys(keyBindings, toolValue).map((k) => k.toUpperCase()).join(" / ");
    return keyStr ? `${name} (${keyStr})` : name;
  }

  const labelPrefix = tool === "eraser" ? ui.toolbar.eraser : ui.toolbar.brush;
  // Two toolbars can be mounted at once (the game's and the pad's), so the
  // popovers' ids are this one's own.
  const idBase = useId();
  const sizePickerId = `brush-size-popover${idBase}`;
  const mobileToolPanelId = `toolbar-mobile-tool-panel${idBase}`;
  const mobileColorPanelId = `toolbar-mobile-color-panel${idBase}`;
  const mobileSizePanelId = `toolbar-mobile-size-panel${idBase}`;
  // What the size goes back to: the player's own default for the brush
  // (Settings -> Appearance), and the eraser's fixed one.
  const defaultBrushSize = useSettingsStore((state) => state.defaultBrushSize);
  const defaultSize = tool === "eraser" ? DEFAULT_ERASER_SIZE : defaultBrushSize;
  const currentIdx = isBrushSize(brushWidth) ? BRUSH_SIZES.indexOf(brushWidth) : -1;
  const defaultIdx = BRUSH_SIZES.indexOf(defaultSize);
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

  // Anything pressed outside a popover closes it - starting a stroke most of
  // all, since the size popover sits over the canvas's edge. `pointerdown`,
  // not `mousedown`: a finger drawing on a canvas with `touch-action: none`
  // never produces a mouse event, and neither do some pen drivers, so the
  // popover stayed open over the drawing for exactly the people most likely
  // to have it in the way. In the capture phase, so that nothing that stops
  // the event on its way up can keep a popover open.
  useEffect(() => {
    function handlePressOutside(e: PointerEvent) {
      const target = e.target as Node;
      if (sizePickerRef.current && !sizePickerRef.current.contains(target)) {
        setSizePickerOpen(false);
      }
      if (mobileToolbarRef.current && !mobileToolbarRef.current.contains(target)) {
        setMobilePanel(null);
      }
    }
    document.addEventListener("pointerdown", handlePressOutside, true);
    return () => {
      document.removeEventListener("pointerdown", handlePressOutside, true);
    };
  }, []);

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) return;
      // A toolbar under a card that has taken the stage - the paused game's,
      // with the scratch pad's own toolbar on it - is not the one being used,
      // and answering too would undo twice.
      const root = cardRef.current ?? mobileToolbarRef.current;
      if (root?.closest("[inert]")) return;

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

      const boundTool = tools.find((entry) => toolKeys(kb, entry.value).includes(key));
      if (boundTool) {
        onToolChange(boundTool.value);
      } else if (kb.brushDecrease.includes(key)) {
        const idx = currentIdx;
        if (idx > 0) {
          handleWidthChange(BRUSH_SIZES[idx - 1]);
        } else if (idx === -1) {
          handleWidthChange(BRUSH_SIZES[0]);
        }
      } else if (kb.brushIncrease.includes(key)) {
        const idx = currentIdx;
        if (idx >= 0 && idx < BRUSH_SIZES.length - 1) {
          handleWidthChange(BRUSH_SIZES[idx + 1]);
        } else if (idx === -1) {
          handleWidthChange(BRUSH_SIZES[defaultIdx]);
        }
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [currentIdx, defaultIdx, handleWidthChange, onToolChange, tools]);

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
    <div className="brush-slider-popover" id={sizePickerId} role="group" aria-label={ui.toolbar.adjustSize({ tool: labelPrefix.toLowerCase() })}>
      <div className="slider-top-preview">
        <span
          className="preview-dot"
          style={{
            width: Math.max(4, Math.min(26, brushWidth * 0.7 + 3)),
            height: Math.max(4, Math.min(26, brushWidth * 0.7 + 3)),
            backgroundColor: activeColor,
          }}
        />
        <span className="preview-readout">{ui.toolbar.widthReadout({ width: brushWidth })}</span>
      </div>
      <div className="slider-track-wrapper">
        <input
          type="range"
          min="0"
          max={BRUSH_SIZES.length - 1}
          step="1"
          value={sliderValue}
          onChange={(e) => handleWidthChange(BRUSH_SIZES[Number(e.target.value)])}
          // The desktop habit for "put it back": the same as the button below.
          onDoubleClick={() => handleWidthChange(defaultSize)}
          className="vertical-brush-slider"
          aria-label={ui.toolbar.sizeSlider({ tool: labelPrefix })}
        />
        {/* Where the slider stops, with the default marked: a stop is a
            place the thumb lands, and the default is the one to find again. */}
        <div className="slider-stops" aria-hidden="true">
          {BRUSH_SIZES.map((size) => (
            <span
              key={size}
              className={`slider-stop${size === defaultSize ? " is-default" : ""}`}
              style={{ ["--stop" as string]: stopPosition(size) }}
            />
          ))}
        </div>
      </div>
      <button
        type="button"
        className="slider-default-button"
        onClick={() => handleWidthChange(defaultSize)}
        aria-pressed={brushWidth === defaultSize}
        aria-label={ui.toolbar.backToDefaultSize({ width: defaultSize })}
        title={ui.toolbar.backToDefaultSize({ width: defaultSize })}
      >
        <span className="slider-default-mark" aria-hidden="true" />
        {ui.toolbar.defaultSize}
      </button>
    </div>
  );

  if (compact) {
    const dock = isMobile && !scratchPad && typeof document !== "undefined"
      ? document.getElementById("room-shell-dock")
      : null;
    // Collapsed controls, as before: one chip opens the tools, one the
    // colours, one the size. On a phone the dock still renders after the chat
    // region, so the strip sits at the bottom of the screen under the thumb;
    // in a desktop column too narrow for the palette it stays under the canvas.
    const mobileToolbar = (
      <div
        className={`toolbar-container toolbar-mobile${isMobile ? "" : " toolbar-compact"}`}
        ref={mobileToolbarRef}
        data-testid="toolbar-mobile"
      >
          <div className="toolbar toolbar-mobile-strip" role="toolbar" aria-label={ui.toolbar.drawingTools}>
            <button
              type="button"
              className={`toolbar-mobile-chip toolbar-mobile-tool-chip${mobilePanel === "tool" ? " active" : ""}`}
              aria-label={ui.toolbar.chooseToolCurrent({ tool: activeTool.name })}
              aria-expanded={mobilePanel === "tool"}
              aria-haspopup="true"
              aria-controls={mobileToolPanelId}
              title={ui.toolbar.chooseTool}
              onClick={() => toggleMobilePanel("tool")}
            >
              <span className="tool-glyph">{activeTool.glyph}</span>
              <span className="toolbar-mobile-chip-caret" aria-hidden="true"><ChevronDownIcon size={12} /></span>
            </button>

            <button
              type="button"
              className={`toolbar-mobile-chip toolbar-mobile-color-chip${mobilePanel === "color" ? " active" : ""}`}
              aria-label={ui.toolbar.chooseColorCurrent({ color })}
              aria-expanded={mobilePanel === "color"}
              aria-haspopup="true"
              aria-controls={mobileColorPanelId}
              title={ui.toolbar.chooseColor}
              onClick={() => toggleMobilePanel("color")}
            >
              <span className="toolbar-mobile-swatch" style={{ backgroundColor: activeColor }} />
              <span className="toolbar-mobile-chip-caret" aria-hidden="true"><ChevronDownIcon size={12} /></span>
            </button>

            <button
              type="button"
              className={`toolbar-mobile-chip${mobilePanel === "size" ? " active" : ""}`}
              aria-label={ui.toolbar.sizeWithWidth({ tool: labelPrefix, width: brushWidth })}
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
              aria-label={ui.toolbar.undo}
              title={ui.toolbar.undoWithShortcut({ keys: undoKeys(keyBindings) })}
              onClick={requestCanvasUndo}
            >
              <UndoIcon size={18} />
            </button>
            <button
              type="button"
              className="toolbar-mobile-chip toolbar-mobile-clear"
              aria-label={ui.toolbar.clear}
              title={ui.toolbar.clearCanvas}
              onClick={requestCanvasClear}
            >
              <TrashIcon size={18} />
            </button>
            {onSave && (
              <button
                type="button"
                className="toolbar-mobile-chip toolbar-mobile-save"
                aria-label={ui.scratchPad.save}
                title={ui.scratchPad.save}
                onClick={onSave}
              >
                <DownloadIcon size={18} />
              </button>
            )}
          </div>

          {mobilePanel === "tool" && (
            <div id={mobileToolPanelId} className="toolbar-mobile-popover" role="group" aria-label={ui.toolbar.chooseTool}>
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
            <div id={mobileColorPanelId} className="toolbar-mobile-popover" role="group" aria-label={ui.toolbar.chooseColor}>
              <div className="toolbar-mobile-colors">
                {colors.map((c) => (
                  <ColorSwatch
                    key={c}
                    color={c}
                    selected={isSelectedColor(c)}
                    variant="toolbar-mobile-swatch-btn"
                    label={ui.toolbar.colorOption({ color: c })}
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
                    title={ui.toolbar.chooseCustomColor}
                  >
                    <input
                      type="color"
                      value={color}
                      onChange={(e) => {
                        handleSelectColor(e.target.value);
                        setMobilePanel(null);
                      }}
                      aria-label={ui.toolbar.chooseCustomColor}
                    />
                  </label>
                )}
              </div>
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

  const arrangement = arrangementOf(layout) ?? ARRANGEMENTS[0];
  const groups: Record<ToolbarGroup, React.ReactNode> = {
    tools: (
      <div key="tools" className="toolbar-group toolbar-tools" aria-label={ui.toolbar.drawingTools}>
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
    ),
    size: (
      <div key="size" className="toolbar-group brush-size-dropdown" ref={sizePickerRef}>
        <button
          type="button"
          className={`brush-size-trigger${sizePickerOpen ? " active" : ""}`}
          onClick={() => setSizePickerOpen((prev) => !prev)}
          aria-label={ui.toolbar.sizeWithWidth({ tool: labelPrefix, width: brushWidth })}
          aria-expanded={sizePickerOpen}
          aria-haspopup="true"
          aria-controls={sizePickerId}
          title={ui.toolbar.sizeShortcutHint({ tool: labelPrefix, width: brushWidth, keys: sizeKeys(keyBindings) })}
        >
          {sizePreview}
          <span className="size-text-readout">{ui.toolbar.widthReadout({ width: brushWidth })}</span>
        </button>
        {sizePickerOpen && sizeSlider}
      </div>
    ),
    palette: (
      <div key="palette" className={`toolbar-group toolbar-colors${paletteClass}`} aria-label={ui.toolbar.colorPalette}>
        {colors.map((c) => (
          <ColorSwatch
            key={c}
            color={c}
            selected={isSelectedColor(c)}
            label={ui.toolbar.colorOption({ color: c })}
            title={ui.toolbar.colorSwatch({ color: c })}
            onSelect={() => handleSelectColor(c)}
          />
        ))}
        {customColorsAllowed && (
          <label
            className={`color-swatch color-swatch-custom${isCustomColor && tool !== "eraser" ? " selected" : ""}`}
            style={isCustomColor ? { backgroundColor: color, backgroundImage: "none" } : undefined}
            title={ui.toolbar.chooseCustomColor}
          >
            <input
              type="color"
              value={color}
              onChange={(e) => handleSelectColor(e.target.value)}
              aria-label={ui.toolbar.chooseCustomColor}
            />
          </label>
        )}
      </div>
    ),
    // Named by aria-label as well as by their text, because the icon-only
    // arrangement hides the text.
    actions: (
      <div key="actions" className="toolbar-group toolbar-actions" aria-label={ui.toolbar.canvasActions}>
        <button
          className="toolbar-action-button undo-button"
          onClick={requestCanvasUndo}
          title={ui.toolbar.undoWithShortcut({ keys: undoKeys(keyBindings) })}
          aria-label={ui.toolbar.undo}
        >
          <UndoIcon size={18} />
          <span className="toolbar-action-label">{ui.toolbar.undo}</span>
        </button>
        <button
          className="toolbar-action-button clear-button"
          onClick={requestCanvasClear}
          title={ui.toolbar.clearCanvas}
          aria-label={ui.toolbar.clear}
        >
          <TrashIcon size={18} />
          <span className="toolbar-action-label">{ui.toolbar.clear}</span>
        </button>
        {onSave && (
          <button
            className="toolbar-action-button save-button"
            onClick={onSave}
            title={ui.scratchPad.save}
            aria-label={ui.scratchPad.save}
          >
            <DownloadIcon size={18} />
            <span className="toolbar-action-label">{ui.scratchPad.save}</span>
          </button>
        )}
      </div>
    ),
  };

  // Line after line, with a divider only between two groups on the same one.
  // One flat keyed list, so a new arrangement moves these elements rather
  // than mounting fresh ones.
  return (
    <div className="toolbar-container" ref={cardRef}>
      <div className="toolbar" data-layout={arrangement.layout}>
        {arrangement.rows.flatMap((row, line) => [
          ...(line > 0 ? [<div key={`break-${row[0]}`} className="toolbar-break" />] : []),
          ...row.flatMap((group, index) => [
            ...(index > 0 ? [<div key={`divider-${group}`} className="toolbar-divider" />] : []),
            groups[group],
          ]),
        ])}
      </div>
    </div>
  );
});
