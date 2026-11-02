import { useEffect, useState } from "react";

import { ui } from "../content/ui/index.ts";
import { refusalText } from "../lib/refusals";
import { startGift } from "../lib/support";
import { useSupportStore } from "../store/supportStore";
import { ExtraChoice } from "./ExtraChoice";
import { ModalShell } from "./ui/ModalShell";
import "../styles/lazy/support.css";

/** Gift a pass (#1540): reached from a profile or the Friends list, never from a
room, since nothing a supporter has may be noticed there (N-21). */
export function GiftPassDialog({
  recipientId,
  recipientName,
  onClose,
}: {
  recipientId: string;
  recipientName: string;
  onClose: () => void;
}) {
  const plans = useSupportStore((state) => state.plans);
  const loadPlans = useSupportStore((state) => state.loadPlans);
  const [anonymous, setAnonymous] = useState(false);
  const [extraMinor, setExtraMinor] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void loadPlans();
  }, [loadPlans]);

  if (!plans) return null;
  const pay = async () => {
    setBusy(true);
    setError(null);
    try {
      window.location.assign(await startGift(recipientId, anonymous, extraMinor));
    } catch (failure) {
      setError(refusalText(failure, ui.support.checkoutFailed));
      setBusy(false);
    }
  };
  return (
    <ModalShell title={ui.support.giftTitle({ name: recipientName })} onDismiss={onClose} testId="gift-pass-dialog">
      <div className="support-pane">
        <p className="support-gift-terms">
          <strong>{ui.support.giftPrice({ price: plans.gift.price })}</strong>{" "}
          {ui.support.giftTerms({ name: recipientName })}
        </p>
        <label className="support-mark-choice">
          <input
            type="checkbox"
            checked={anonymous}
            onChange={(event) => setAnonymous(event.target.checked)}
          />
          <span>
            <strong>{ui.support.giftAnonymous({ name: recipientName })}</strong>
          </span>
        </label>
        <ExtraChoice renews={false} maxExtraMinor={plans.maxExtraMinor} onChange={setExtraMinor} />
        {error && (
          <p className="auth-error" role="alert">
            {error}
          </p>
        )}
        <div className="support-pay support-gift-actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            {ui.support.giftCancel}
          </button>
          <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void pay()}>
            {ui.support.checkout}
          </button>
        </div>
      </div>
    </ModalShell>
  );
}
