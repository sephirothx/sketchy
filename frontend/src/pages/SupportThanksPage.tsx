import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { AppHeader } from "../components/AppHeader";
import { SupporterMark } from "../components/ui/SupporterMark";
import { ui } from "../content/ui/index.ts";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { fetchSupporterStatus } from "../lib/support";
import { useAuthStore } from "../store/authStore";
import { useSupportStore } from "../store/supportStore";
import "../styles/lazy/support.css";

const POLL_MS = 2000;
const POLL_TRIES = 30;

/** Where the provider sends a buyer back to. It reads the answer from the server
and never from the URL, and says "still confirming" until the webhook has landed,
because the webhook may land after the redirect (#1475). */
export function SupportThanksPage() {
  useDocumentTitle(ui.support.thanksDocumentTitle);
  const user = useAuthStore((state) => state.user);
  const refresh = useSupportStore((state) => state.refresh);
  const [confirmed, setConfirmed] = useState(false);
  const [gaveUp, setGaveUp] = useState(false);

  useEffect(() => {
    let stopped = false;
    let timer = 0;
    let tries = 0;
    const ask = async () => {
      tries += 1;
      const status = await fetchSupporterStatus().catch(() => null);
      if (stopped) return;
      if (status?.active) {
        setConfirmed(true);
        void refresh();
        void useAuthStore.getState().fetchMe();
        return;
      }
      if (tries >= POLL_TRIES) {
        setGaveUp(true);
        return;
      }
      timer = window.setTimeout(() => void ask(), POLL_MS);
    };
    void ask();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [refresh]);

  return (
    <div className="support-page">
      <AppHeader />
      <main className="surface-card support-page-card" data-testid="support-thanks">
        {confirmed ? (
          <>
            <SupporterMark size={40} />
            <h1>{ui.support.thanksTitle({ name: user?.displayName ?? "" })}</h1>
            <p>{ui.support.thanksBody}</p>
          </>
        ) : (
          <>
            <h1>{ui.support.confirmingTitle}</h1>
            <p aria-live="polite">{gaveUp ? ui.support.confirmingSlow : ui.support.confirmingBody}</p>
          </>
        )}
        <Link className="btn btn-primary" to="/">
          {ui.support.backToLobby}
        </Link>
      </main>
    </div>
  );
}
