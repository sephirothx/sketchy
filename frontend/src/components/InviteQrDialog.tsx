import { lazy, Suspense } from "react";
import { ModalShell } from "./ui/ModalShell";
import { ui } from "../content/ui/index.ts";

const QrCode = lazy(() => import("./QrCode"));

/**
 * The room's invite link as a code a phone camera reads, opened from the
 * waiting room's invite card (#864).
 *
 * For a room whose players are in it: the laptop on the table, the phone
 * held up to the person on the next seat. It encodes the room's own address
 * rather than the address bar, so nothing else the bar happens to hold - a
 * query, a fragment - goes along, and a room has no language prefix to carry
 * (lib/localePath.ts). Somebody not seated who opens it gets the room's
 * invite page, the same as from a pasted link.
 *
 * Behind a button rather than on the card: the encoder is fetched only when
 * somebody asks for a code, not by every host of every room. ModalShell
 * gives it Escape, the scrim and Back (R-UX-15).
 */
export function InviteQrDialog({ code, onClose }: { code: string; onClose: () => void }) {
  const url = `${window.location.origin}/room/${encodeURIComponent(code)}`;
  return (
    <ModalShell title={ui.inviteQrDialog.title} cardClassName="invite-qr-dialog" onDismiss={onClose}>
      <div className="invite-qr-frame">
        <Suspense fallback={<p className="modal-hint">{ui.inviteQrDialog.drawingCode}</p>}>
          <QrCode value={url} label={ui.inviteQrDialog.qrLabel({ code })} className="invite-qr" />
        </Suspense>
      </div>
      <p className="waiting-code invite-qr-code" aria-hidden="true">{code}</p>
      <p className="modal-hint invite-qr-hint">{ui.inviteQrDialog.opensInvitePage}</p>
    </ModalShell>
  );
}
