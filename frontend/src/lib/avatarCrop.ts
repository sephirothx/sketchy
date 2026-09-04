/**
 * The shape of a player's picture, shared by the browser that makes one, the
 * crop dialog that lets the player frame it, and the tests that check the
 * arithmetic. No imports, so it loads anywhere.
 *
 * A crop is a square of the source picture: `zoom` 1 is the largest square
 * that fits, and the centre may sit anywhere that keeps the square inside.
 */
export const AVATAR_SIZE = 256;
export const MAX_AVATAR_BYTES = 128 * 1024;
/** Where the zoom slider stops: past this a 256-square is made of nothing. */
export const MAX_ZOOM = 4;
/** The smallest square worth scaling up to a picture. */
export const MIN_CROP_SIDE = 32;

export interface CropRect {
  x: number;
  y: number;
  side: number;
}

/** Where the player has framed the picture: how far in, and on what point. */
export interface CropState {
  zoom: number;
  centerX: number;
  centerY: number;
}

/** The square a picture is cut down to by default: the largest one centred on it. */
export function centreSquare(width: number, height: number): CropRect {
  const side = Math.min(width, height);
  return { x: Math.floor((width - side) / 2), y: Math.floor((height - side) / 2), side };
}

/** The furthest in a picture this size can be zoomed and still make a crop. */
export function maxZoomFor(width: number, height: number): number {
  return Math.max(1, Math.min(MAX_ZOOM, Math.min(width, height) / MIN_CROP_SIDE));
}

export function initialCrop(width: number, height: number): CropState {
  return { zoom: 1, centerX: width / 2, centerY: height / 2 };
}

/** The same framing with the centre pulled back inside the picture. */
export function clampCrop(width: number, height: number, crop: CropState): CropState {
  const zoom = Math.min(Math.max(crop.zoom, 1), maxZoomFor(width, height));
  const half = Math.min(width, height) / zoom / 2;
  const clamp = (value: number, max: number) => Math.min(Math.max(value, half), max - half);
  return { zoom, centerX: clamp(crop.centerX, width), centerY: clamp(crop.centerY, height) };
}

/** The pixels of the source a framing selects, as whole numbers inside it. */
export function cropRect(width: number, height: number, crop: CropState): CropRect {
  const framed = clampCrop(width, height, crop);
  const side = Math.max(1, Math.round(Math.min(width, height) / framed.zoom));
  const x = Math.min(Math.max(Math.round(framed.centerX - side / 2), 0), width - side);
  const y = Math.min(Math.max(Math.round(framed.centerY - side / 2), 0), height - side);
  return { x, y, side };
}

/**
 * How to draw the whole picture behind a square viewport of `viewport`
 * pixels so that the crop fills it: the scale, and the picture's top-left.
 */
export function viewportPlacement(
  width: number,
  height: number,
  crop: CropState,
  viewport: number,
): { scale: number; left: number; top: number } {
  const framed = clampCrop(width, height, crop);
  const scale = (viewport * framed.zoom) / Math.min(width, height);
  return {
    scale,
    left: viewport / 2 - framed.centerX * scale,
    top: viewport / 2 - framed.centerY * scale,
  };
}
