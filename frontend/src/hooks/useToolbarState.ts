import { useEffect, useState } from "react";
import { useCanvasBudgetStore } from "../store/canvasBudgetStore";
import { useGameStore } from "../store/gameStore";
import type { DrawTool } from "../types";

export function useToolbarState(isDrawer: boolean) {
  const [color, setColor] = useState("#000000");
  const [brushWidth, setBrushWidth] = useState(6);
  const [eraserWidth, setEraserWidth] = useState(24);
  const [tool, setTool] = useState<DrawTool>("brush");
  const [wasDrawer, setWasDrawer] = useState(false);

  // This render-time transition is intentional: the first enabled drawing
  // render must never expose controls left over from an earlier turn.
  if (isDrawer !== wasDrawer) {
    setWasDrawer(isDrawer);
    if (isDrawer) {
      setColor("#000000");
      setTool("brush");
      setBrushWidth(6);
      setEraserWidth(24);
    }
  }

  // The fill tool greys out once this turn's replay budget can no longer
  // afford one. Holding a tool that is no longer selectable would leave the
  // pointer doing nothing, so hand the drawer back the pen.
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
      text: "Fill is unavailable for the rest of this turn.",
      correct: false,
      system: true,
    });
  }, [fillAvailable, isDrawer]);

  useEffect(() => {
    if (!isDrawer || strokeAvailable) return;
    useGameStore.getState().addMessage({
      id: `${Date.now()}-stroke-budget`,
      nickname: "",
      text: "Drawing by hand is unavailable for the rest of this turn. Shapes still work.",
      correct: false,
      system: true,
    });
  }, [isDrawer, strokeAvailable]);

  const activeWidth = tool === "eraser" ? eraserWidth : brushWidth;

  function handleWidthChange(newWidth: number) {
    if (tool === "eraser") setEraserWidth(newWidth);
    else setBrushWidth(newWidth);
  }

  return {
    color,
    setColor,
    brushWidth: activeWidth,
    onBrushWidthChange: handleWidthChange,
    tool,
    setTool,
  };
}
