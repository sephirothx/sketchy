/**
 * Solo's drawings decoded this visit, by serve (#1496 review).
 *
 * A drawing is shown only as the drawing door gives it now: whether it may
 * still be shown - its drawer opted out or took it out, a moderator hid it,
 * it was erased - is the door's to say, every time (R-SOLO-04, R-SOLO-16).
 * So this cache never answers on its own. It is asked with the bytes the door
 * has just given, and spares only the decoding: the same bytes give back the
 * drawing already decoded, other bytes are decoded afresh, and a door that
 * refuses forgets the drawing. Asking the door again costs little, since it
 * answers a browser that has the bytes with a 304.
 */

/** FNV-1a over the bytes, with their length: enough to tell one drawing's
    bytes from another's under the same serve, not a checksum anything else
    relies on. */
function fingerprint(bytes: ArrayBuffer): string {
  const view = new Uint8Array(bytes);
  let hash = 0x811c9dc5;
  for (const byte of view) {
    hash ^= byte;
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return `${view.length}:${hash.toString(16)}`;
}

export class DecodedDrawings<T> {
  private readonly entries = new Map<string, { key: string; value: T }>();
  private readonly kept: number;

  constructor(kept = 24) {
    this.kept = kept;
  }

  /** The drawing the door just gave for `serveId`, decoded once per set of
      bytes; null when the bytes do not decode. */
  decode(serveId: string, bytes: ArrayBuffer, decode: (bytes: ArrayBuffer) => T | null): T | null {
    const key = fingerprint(bytes);
    const kept = this.entries.get(serveId);
    this.entries.delete(serveId);
    if (kept && kept.key === key) {
      this.entries.set(serveId, kept);
      return kept.value;
    }
    const value = decode(bytes);
    if (value === null) return null;
    this.entries.set(serveId, { key, value });
    while (this.entries.size > this.kept) {
      const oldest = this.entries.keys().next().value;
      if (oldest === undefined) break;
      this.entries.delete(oldest);
    }
    return value;
  }

  /** The door refused it: nothing of it is kept. */
  forget(serveId: string): void {
    this.entries.delete(serveId);
  }

  /** Another account's page, or none: nothing of the last one's is kept. */
  clear(): void {
    this.entries.clear();
  }

  get size(): number {
    return this.entries.size;
  }
}
