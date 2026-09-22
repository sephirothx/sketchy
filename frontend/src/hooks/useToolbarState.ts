import { useCallback, useEffect, useState } from "react";
import { useCanvasBudgetStore } from "../store/canvasBudgetStore";
import { useGameStore } from "../store/gameStore";
import { useSettingsStore } from "../store/settingsStore";
import { DEFAULT_ERASER_SIZE } from "../lib/brushSizes";
import type { DrawTool } from "../types";
import { ui } from "../content/ui/index.ts";

export function useToolbarState(isDrawer: boolean) {
  const [color, setColor] = useState("#000000");
  // The player's own default (Settings -> Appearance): every turn resets the
  // toolbar, so whoever always draws at another size would otherwise reach
  // for the slider at the start of every turn, with the clock running.
  const defaultBrushSize = useSettingsStore((state) => state.defaultBrushSize);
  const [brushWidth, setBrushWidth] = useState<number>(defaultBrushSize);
  const [eraserWidth, setEraserWidth] = useState<number>(DEFAULT_ERASER_SIZE);
  const [tool, setTool] = useState<DrawTool>("brush");
  const [wasDrawer, setWasDrawer] = useState(false);

  // This render-time transition is intentional: the first enabled drawing
  // render must never expose controls left over from an earlier turn.
  if (isDrawer !== wasDrawer) {
    setWasDrawer(isDrawer);
    if (isDrawer) {
      setColor("#000000");
      setTool("brush");
      setBrushWidth(defaultBrushSize);
      setEraserWidth(DEFAULT_ERASER_SIZE);
    }
  }

  // The fill tool greys out once this turn's replay budget can no longer
  // afford one. Holding a tool that is no longer selectable would leave the
  // pointer doing nothing, so hand the drawer back the brush.
  const fillAvailable = useCanvasBudgetStore((state) => state.fillAvailable);
  const strokeAvailable = useCanvasBudgetStore((state) => state.strokeAvailable);
  if (!fillAvailable && tool === "fill" && strokeAvailable) setTool("brush");

  // Said once, and to the drawer alone: on a phone there is no tooltip to
  // hover, so a disabled button on its own explains nothing.
  useEffect(() => {
    if (!isDrawer || fillAvailable) return;
    useGameStore.getState().addMessage({
      id: `${Date.now()}-fill-budget`,
      nickname: "",
      text: ui.useToolbarState.fillIsUnavailableForThe,
      correct: false,
      system: true,
    });
  }, [fillAvailable, isDrawer]);

  useEffect(() => {
    if (!isDrawer || strokeAvailable) return;
    useGameStore.getState().addMessage({
      id: `${Date.now()}-stroke-budget`,
      nickname: "",
      text: ui.useToolbarState.drawingByHandIsUnavailable,
      correct: false,
      system: true,
    });
  }, [isDrawer, strokeAvailable]);

  const activeWidth = tool === "eraser" ? eraserWidth : brushWidth;

  // Stable per tool, so the memoised Toolbar is not re-rendered - and its
  // layout re-measured - by a new function on every gameplay render (#987).
  const handleWidthChange = useCallback((newWidth: number) => {
    if (tool === "eraser") setEraserWidth(newWidth);
    else setBrushWidth(newWidth);
  }, [tool]);

  return {
    color,
    setColor,
    brushWidth: activeWidth,
    onBrushWidthChange: handleWidthChange,
    tool,
    setTool,
  };
}
