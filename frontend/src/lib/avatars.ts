import { apiRequest } from "./api";
import { AVATAR_SIZE, MAX_AVATAR_BYTES, centreSquare } from "./avatarCrop.ts";

export { AVATAR_SIZE, MAX_AVATAR_BYTES, centreSquare };

/**
 * A player's picture (#573): what the server takes, and how the browser
 * makes one from whatever file was chosen.
 *
 * The browser does the cropping and re-encoding - centre-square, AVATAR_SIZE
 * on a side, PNG - so the server never decodes an image: it checks the
 * bytes are a PNG of exactly that size under the cap, and serves them back
 * only ever as an image.
 */
export const ACCEPTED_INPUT_TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif"];
const MAX_INPUT_BYTES = 10 * 1024 * 1024;

export class AvatarInputError extends Error {}

function loadImage(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => {
      URL.revokeObjectURL(url);
      resolve(image);
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new AvatarInputError("That file could not be read as a picture."));
    };
    image.src = url;
  });
}

/**
 * Turn a chosen file into the PNG the server accepts, as base64.
 *
 * Drawn through a canvas, which is what strips metadata and settles the
 * format; a transparent source gets a transparent picture, which the disc
 * behind it paints its colour through.
 */
export async function preparePicture(file: File): Promise<{ base64: string; previewUrl: string }> {
  if (!ACCEPTED_INPUT_TYPES.includes(file.type)) {
    throw new AvatarInputError("Choose a PNG, JPEG, WebP or GIF picture.");
  }
  if (file.size > MAX_INPUT_BYTES) {
    throw new AvatarInputError("That picture is too large to read: 10 MB at most.");
  }
  const image = await loadImage(file);
  const { x, y, side } = centreSquare(image.naturalWidth, image.naturalHeight);
  if (side < 32) throw new AvatarInputError("That picture is too small to make anything of.");
  const canvas = document.createElement("canvas");
  canvas.width = AVATAR_SIZE;
  canvas.height = AVATAR_SIZE;
  const context = canvas.getContext("2d");
  if (!context) throw new AvatarInputError("This browser cannot resize pictures.");
  context.imageSmoothingQuality = "high";
  context.drawImage(image, x, y, side, side, 0, 0, AVATAR_SIZE, AVATAR_SIZE);
  const dataUrl = canvas.toDataURL("image/png");
  const base64 = dataUrl.slice(dataUrl.indexOf(",") + 1);
  if (Math.ceil((base64.length * 3) / 4) > MAX_AVATAR_BYTES) {
    throw new AvatarInputError(
      "That picture is too detailed to fit. Try a simpler one, or crop it first.",
    );
  }
  return { base64, previewUrl: dataUrl };
}

export function uploadAvatar(base64: string): Promise<{ avatarKey: string; avatarUrl: string }> {
  return apiRequest("/api/users/me/avatar", { method: "POST", body: { image: base64 } });
}

export function removeAvatar(): Promise<{ ok: boolean }> {
  return apiRequest("/api/users/me/avatar", { method: "DELETE" });
}
