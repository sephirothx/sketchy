/**
 * What a QR code read by the Join by code scanner has to say to be a room
 * (#1530): a link to `/room/<CODE>` on this site's own origin - what the
 * waiting room's invite draws (InviteQrDialog) - or a bare room code.
 *
 * Anything else is refused rather than followed: a scanner that opened
 * whatever it read would hand the page's navigation to any sticker in the
 * room. The code is only ever joined here, so a link to another host carries
 * no risk; it is refused because it is not this site's invitation - a code
 * that happens to sit in some other site's `/room/` path is no reason to seat
 * the player anywhere. The cost is a code shown by a server on another
 * address (a LAN or localhost copy), which has to be typed. Pure, so the
 * rules have a test of their own.
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
