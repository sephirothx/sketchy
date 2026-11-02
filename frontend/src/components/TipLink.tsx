import { ui } from "../content/ui/index.ts";
import { tipHost } from "../lib/support";

const KOFI_HOST = "ko-fi.com";

/** A tip with nothing in return (#1471): a plain outbound link, with no script
and no data, that never counts toward a pass. Ko-fi's own badge when the link
goes there, served from this origin (R-PLAT-20), and plain words otherwise, so
changing `SUPPORT_TIP_URL` changes nothing else. */
export function TipLink({ url }: { url: string }) {
  const host = tipHost(url);
  if (!host) return null;
  return (
    <div className="support-tip">
      <p>
        <strong>{ui.support.tipAsk}</strong> <span>{ui.support.tipNote}</span>
      </p>
      <div className="support-tip-action">
        <a href={url} target="_blank" rel="noopener noreferrer">
          {host === KOFI_HOST ? (
            <img src="/support/kofi-badge.svg" alt={ui.support.tipBadge} width="190" height="40" />
          ) : (
            ui.support.tipLabel
          )}
        </a>
        <small>{ui.support.opens({ host })}</small>
      </div>
    </div>
  );
}
