/**
 * What a QR code read by the Join by code scanner has to say to be a room
 * (#1530): a web link whose path is `/room/<CODE>` - what the waiting room's
 * invite draws (InviteQrDialog) - or a bare room code.
 *
 * Anything else is refused rather than followed: a scanner that opened
 * whatever it read would hand the page's navigation to any sticker in the
 * room. Only the code is taken from a link, and it is joined on this server,
 * whatever address the link names: the invite is drawn with the address its
 * host opened the page on, which is not always the one the scanning player
 * did - localhost and a tunnel, a LAN address - and a bare code, accepted
 * from anywhere, already says no more than that. A code that matches no room
 * is refused by the join, as a typed one is. Pure, so the rules have a test
 * of their own.
 */

const CODE = /^[A-Z0-9]{6}$/;

export function roomCodeFromScan(text: string): string | null {
  const value = text.trim();
  if (CODE.test(value.toUpperCase())) return value.toUpperCase();
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return null;
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") return null;
  const match = /^\/room\/([A-Za-z0-9]{6})\/?$/.exec(url.pathname);
  return match ? match[1].toUpperCase() : null;
}
