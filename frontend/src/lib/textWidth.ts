/** How wide a piece of text is in an element's font, without laying it out.

For layouts that have to know whether words fit before choosing how to lay
them out - how many room facts to a row (RoomFacts), whether the waiting
room's footer holds its long labels on one line (WaitingRoomPanel) - where
laying the text out to find out would move the page it is measuring. One
canvas for the tab; a pixel or so off the layout's own rounding, which the
callers allow for. */

let context: CanvasRenderingContext2D | null | undefined;

export function textWidth(text: string, element: Element): number {
  context ??= document.createElement("canvas").getContext("2d");
  if (!context) return 0;
  const style = getComputedStyle(element);
  context.font = `${style.fontStyle} ${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
  return context.measureText(text).width;
}
