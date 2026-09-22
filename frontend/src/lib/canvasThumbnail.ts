/** A drawing's pixels, made small without a canvas ever being read (R-DRAW-19).

Thumbnails used to be scaled by drawing onto a canvas and reading it back with
`toBlob`. A browser is free to answer that read with other pixels than it
painted, and privacy protections do: Firefox's `privacy.resistFingerprinting`
(Tor Browser, Mullvad Browser, LibreWolf) answers with noise, so every gallery
card showed static. So the scaling is done here, on the pixels the game owns,
and the result is encoded by `pngEncode.ts` - the same route Save image takes.

Each target pixel is the average of the source pixels its area covers: a box
filter, which is what a downscale by a whole factor or more needs to keep thin
strokes from vanishing between samples. */

/** `source` (sourceWidth x sourceHeight RGBA) averaged down to `width` x `height`. */
export function downscalePixels(
  source: Uint8ClampedArray,
  sourceWidth: number,
  sourceHeight: number,
  width: number,
  height: number,
): Uint8ClampedArray {
  const out = new Uint8ClampedArray(width * height * 4);
  const scaleX = sourceWidth / width;
  const scaleY = sourceHeight / height;
  for (let y = 0; y < height; y++) {
    const top = Math.floor(y * scaleY);
    const bottom = Math.max(top + 1, Math.min(sourceHeight, Math.ceil((y + 1) * scaleY)));
    for (let x = 0; x < width; x++) {
      const left = Math.floor(x * scaleX);
      const right = Math.max(left + 1, Math.min(sourceWidth, Math.ceil((x + 1) * scaleX)));
      let r = 0;
      let g = 0;
      let b = 0;
      let a = 0;
      for (let sy = top; sy < bottom; sy++) {
        let index = (sy * sourceWidth + left) * 4;
        for (let sx = left; sx < right; sx++) {
          r += source[index];
          g += source[index + 1];
          b += source[index + 2];
          a += source[index + 3];
          index += 4;
        }
      }
      const count = (bottom - top) * (right - left);
      const target = (y * width + x) * 4;
      out[target] = r / count;
      out[target + 1] = g / count;
      out[target + 2] = b / count;
      out[target + 3] = a / count;
    }
  }
  return out;
}
