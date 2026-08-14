export function getCanvasDownloadName(solutionWord: string | null): string {
  const date = new Date();
  const datePart = [
    String(date.getFullYear()).slice(-2),
    String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0"),
    String(date.getHours()).padStart(2, "0"),
    String(date.getMinutes()).padStart(2, "0"),
  ].join("");
  const prompt = solutionWord
    ? solutionWord.trim().toLowerCase().replace(/\s+/g, "-").replace(/[^a-z0-9_-]/g, "")
    : "";
  return `sketchy-${datePart}${prompt ? `-${prompt}` : ""}.png`;
}

export function saveCanvasImage(
  canvas: HTMLCanvasElement | null,
  solutionWord: string | null,
): void {
  if (!canvas) return;
  const link = document.createElement("a");
  link.download = getCanvasDownloadName(solutionWord);
  link.href = canvas.toDataURL("image/png");
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}
