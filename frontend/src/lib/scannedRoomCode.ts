/**
 * What a QR code read by the Join by code scanner has to say to be a room
 * (#1530): a link to `/room/<CODE>` on this site's own origin - what the
 * waiting room's invite draws (InviteQrDialog) - or a bare room code.
 *
 * Anything else is refused rather than followed. A scanner that opened
 * whatever it read would hand the page's navigation to any sticker in the
 * room, and one that accepted a `/room/` path on another host would send a
 * player into a lookalike site's room with this site's look around it.
 * Pure, so the rules have a test of their own.
 */

const CODE = /^[A-Z0-9]{6}$/;

export function roomCodeFromScan(text: string, origin: string): string | null {
  const value = text.trim();
  if (CODE.test(value.toUpperCase())) return value.toUpperCase();
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return null;
  }
  if (url.origin !== origin) return null;
  const match = /^\/room\/([A-Za-z0-9]{6})\/?$/.exec(url.pathname);
  return match ? match[1].toUpperCase() : null;
}
