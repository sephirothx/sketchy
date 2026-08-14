import { useState } from "react";
import type { DrawTool } from "../types";

export function useToolbarState(isDrawer: boolean) {
  const [color, setColor] = useState("#000000");
  const [brushWidth, setBrushWidth] = useState(6);
  const [eraserWidth, setEraserWidth] = useState(24);
  const [tool, setTool] = useState<DrawTool>("pen");
  const [wasDrawer, setWasDrawer] = useState(false);

  // This render-time transition is intentional: the first enabled drawing
  // render must never expose controls left over from an earlier turn.
  if (isDrawer !== wasDrawer) {
    setWasDrawer(isDrawer);
    if (isDrawer) {
      setColor("#000000");
      setTool("pen");
      setBrushWidth(6);
      setEraserWidth(24);
    }
  }

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
