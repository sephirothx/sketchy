/** Thumbnails drawn off the page's thread (#1282).

One job at a time, in the order they come: `lib/thumbnailQueue.ts` sends a
job only when the previous one has answered, so this holds one history, one
full-size buffer and one scaled copy at most. The PNG goes back transferred,
not copied. */

import { renderThumbnail } from "../lib/thumbnailRender.ts";

export interface ThumbnailJob {
  id: number;
  bytes: ArrayBuffer;
  pixelWidth: number;
}

export type ThumbnailAnswer =
  | { id: number; png: ArrayBuffer; width: number; height: number }
  | { id: number; png: null };

const scope = self as unknown as {
  onmessage: ((event: MessageEvent<ThumbnailJob>) => void) | null;
  postMessage(message: ThumbnailAnswer, transfer?: Transferable[]): void;
};

scope.onmessage = (event) => {
  const { id, bytes, pixelWidth } = event.data;
  void renderThumbnail(bytes, pixelWidth).then(
    (image) => {
      if (!image) {
        scope.postMessage({ id, png: null });
        return;
      }
      const png = image.png.buffer.byteLength === image.png.byteLength
        ? (image.png.buffer as ArrayBuffer)
        : image.png.slice().buffer;
      scope.postMessage({ id, png, width: image.width, height: image.height }, [png]);
    },
    () => scope.postMessage({ id, png: null }),
  );
};
