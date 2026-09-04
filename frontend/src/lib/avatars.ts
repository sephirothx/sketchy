import { apiRequest } from "./api";
import { AVATAR_SIZE, MAX_AVATAR_BYTES, type CropRect } from "./avatarCrop.ts";

export { AVATAR_SIZE, MAX_AVATAR_BYTES };

/**
 * A player's picture (#573): what the server takes, and how the browser
 * makes one from whatever file was chosen.
 *
 * The browser does the cropping and re-encoding - the square the player
 * framed, AVATAR_SIZE on a side, WebP where it can encode one and PNG where
 * it cannot - so the server never decodes an image: it reads the header of
 * either, checks the size and the cap, and serves the bytes back only ever
 * as an image.
 */
export const ACCEPTED_INPUT_TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif"];
const MAX_INPUT_BYTES = 10 * 1024 * 1024;
/** WebP at this quality is ~22 KiB for a photograph; lossless PNG is ~136 KiB. */
const WEBP_QUALITY = 0.85;

export class AvatarInputError extends Error {}

/** The chosen file decoded, plus the object URL it is drawn from until `release`. */
export interface LoadedPicture {
  image: HTMLImageElement;
  width: number;
  height: number;
  release: () => void;
}

/** Read the chosen file into an image the crop dialog can show, or say why not. */
export async function loadPicture(file: File): Promise<LoadedPicture> {
  if (!ACCEPTED_INPUT_TYPES.includes(file.type)) {
    throw new AvatarInputError("Choose a PNG, JPEG, WebP or GIF picture.");
  }
  if (file.size > MAX_INPUT_BYTES) {
    throw new AvatarInputError("That picture is too large to read: 10 MB at most.");
  }
  const url = URL.createObjectURL(file);
  const release = () => URL.revokeObjectURL(url);
  const image = await new Promise<HTMLImageElement>((resolve, reject) => {
    const element = new Image();
    element.onload = () => resolve(element);
    element.onerror = () => {
      release();
      reject(new AvatarInputError("That file could not be read as a picture."));
    };
    element.src = url;
  });
  if (Math.min(image.naturalWidth, image.naturalHeight) < 32) {
    release();
    throw new AvatarInputError("That picture is too small to make anything of.");
  }
  return { image, width: image.naturalWidth, height: image.naturalHeight, release };
}

/**
 * Turn a loaded picture into the bytes the server accepts, as base64.
 *
 * Drawn through a canvas, which is what strips metadata and settles the
 * format; a transparent source gets a transparent picture, which the disc
 * behind it paints its colour through. WebP first: a browser that cannot
 * encode it answers `toDataURL` with a PNG instead, which the server also
 * takes, so the fallback is the browser's own.
 */
export function encodePicture(
  image: CanvasImageSource,
  crop: CropRect,
): { base64: string; previewUrl: string; contentType: string } {
  const canvas = document.createElement("canvas");
  canvas.width = AVATAR_SIZE;
  canvas.height = AVATAR_SIZE;
  const context = canvas.getContext("2d");
  if (!context) throw new AvatarInputError("This browser cannot resize pictures.");
  context.imageSmoothingQuality = "high";
  context.drawImage(image, crop.x, crop.y, crop.side, crop.side, 0, 0, AVATAR_SIZE, AVATAR_SIZE);
  const dataUrl = canvas.toDataURL("image/webp", WEBP_QUALITY);
  const contentType = dataUrl.startsWith("data:image/webp") ? "image/webp" : "image/png";
  const base64 = dataUrl.slice(dataUrl.indexOf(",") + 1);
  if (Math.ceil((base64.length * 3) / 4) > MAX_AVATAR_BYTES) {
    throw new AvatarInputError(
      "That picture is too detailed to fit. Try a simpler one, or zoom in on part of it.",
    );
  }
  return { base64, previewUrl: dataUrl, contentType };
}

export function uploadAvatar(base64: string): Promise<{ avatarKey: string; avatarUrl: string }> {
  return apiRequest("/api/users/me/avatar", { method: "POST", body: { image: base64 } });
}

/** Wear one of the deployment's own drawings instead (R-AVA-06). */
export function chooseDoodle(name: string): Promise<{ avatarKey: string; avatarUrl: string }> {
  return apiRequest("/api/users/me/avatar/doodle", { method: "PUT", body: { name } });
}

export function removeAvatar(): Promise<{ ok: boolean }> {
  return apiRequest("/api/users/me/avatar", { method: "DELETE" });
}
