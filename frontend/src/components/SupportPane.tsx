import { useEffect, useState, type ReactNode } from "react";

import { ui } from "../content/ui/index.ts";
import { useOpenSettings } from "../hooks/useSettingsRoute";
import { formatDate } from "../lib/clock";
import { refusalText } from "../lib/refusals";
import {
  extraMinorFrom,
  formatEuros,
  isLifetime,
  startCheckout,
  type SupportPlans,
  type SupportProduct,
} from "../lib/support";
import { useAuthStore } from "../store/authStore";
import { useSupportStore } from "../store/supportStore";
import { CheckIcon } from "./icons";
import { TipLink } from "./TipLink";
import { SupporterMark } from "./ui/SupporterMark";
import "../styles/lazy/support.css";

const EXTRA_CHIPS = [500, 1000, 2000];

function Perks() {
  const perks = [ui.support.perkMark, ui.support.perkLooks, ui.support.perkSolo];
  return (
    <ul className="support-perks">
      {perks.map((perk) => (
        <li key={perk}>
          <CheckIcon size={16} />
          <strong>{perk}</strong>
        </li>
      ))}
    </ul>
  );
}

function Pitch({ children }: { children: ReactNode }) {
  return (
    <>
      <header className="support-head">
        <h3>
          <SupporterMark size={20} /> {ui.support.title}
        </h3>
        <p>{ui.support.introLead}</p>
        <p>{ui.support.introPass}</p>
      </header>
      <Perks />
      {children}
    </>
  );
}

function PlanCard({
  title,
  price,
  note,
  selected,
  onSelect,
}: {
  title: string;
  price: string;
  note: string;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <label className={`support-plan${selected ? " is-selected" : ""}`}>
      <input type="radio" name="support-plan" checked={selected} onChange={onSelect} />
      <span className="support-plan-title">{title}</span>
      <span className="support-plan-price">{price}</span>
      <span className="support-plan-note">{note}</span>
    </label>
  );
}

function Checkout({ plans }: { plans: SupportPlans }) {
  const showMark = useSupportStore((state) => state.showMark);
  const setShowMark = useSupportStore((state) => state.setShowMark);
  const [product, setProduct] = useState<SupportProduct>("year");
  const [extra, setExtra] = useState<number | "other">(0);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Follows the account until touched: it may arrive after this mounts.
  const [chosenMark, setChosenMark] = useState<boolean | null>(null);
  const wantsMark = chosenMark ?? showMark;

  const extraMinor = extra === "other" ? extraMinorFrom(typed, plans.maxExtraMinor) : extra;

  const pay = async () => {
    setBusy(true);
    setError(null);
    try {
      if (wantsMark !== showMark) await setShowMark(wantsMark);
      // A navigation, not a frame: nothing of the provider's runs here (R-PLAT-20).
      window.location.assign(await startCheckout(product, extraMinor));
    } catch (failure) {
      setError(refusalText(failure, ui.support.checkoutFailed));
      setBusy(false);
    }
  };

  const chip = (value: number | "other", label: string) => (
    <button
      key={label}
      type="button"
      className={`support-chip${extra === value ? " is-selected" : ""}`}
      aria-pressed={extra === value}
      onClick={() => setExtra(value)}
    >
      {label}
    </button>
  );

  return (
    <>
      <div className="support-plans" role="radiogroup" aria-label={ui.support.title}>
        <PlanCard
          title={ui.support.planYear}
          price={plans.year.price}
          note={ui.support.yearNote}
          selected={product === "year"}
          onSelect={() => setProduct("year")}
        />
        <PlanCard
          title={ui.support.planLifetime}
          price={plans.lifetime.price}
          note={ui.support.lifetimeNote}
          selected={product === "lifetime"}
          onSelect={() => setProduct("lifetime")}
        />
      </div>
      <div className="support-extra">
        <p>
          <strong>{ui.support.extraAsk}</strong>
          {product === "year" && <span> {ui.support.extraNote}</span>}
        </p>
        <div className="support-chips">
          {chip(0, ui.support.extraNone)}
          {EXTRA_CHIPS.map((value) => chip(value, `+${formatEuros(value)}`))}
          {chip("other", ui.support.extraOther)}
        </div>
        {extra === "other" && (
          <input
            className="support-extra-input"
            inputMode="decimal"
            aria-label={ui.support.extraOtherLabel}
            placeholder="€"
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
          />
        )}
      </div>
      <label className="support-mark-choice">
        <input
          type="checkbox"
          checked={wantsMark}
          onChange={(event) => setChosenMark(event.target.checked)}
        />
        <span>
          <strong>{ui.support.showMark}</strong>
          <small>{ui.support.showMarkHint}</small>
        </span>
      </label>
      <div className="support-pay">
        <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void pay()}>
          {ui.support.checkout}
        </button>
        <small>{ui.support.checkoutBy}</small>
      </div>
      {error && (
        <p className="auth-error" role="alert">
          {error}
        </p>
      )}
    </>
  );
}

function SupporterView() {
  const status = useSupportStore((state) => state.status);
  const showMark = useSupportStore((state) => state.showMark);
  const setShowMark = useSupportStore((state) => state.setShowMark);
  const [saveFailed, setSaveFailed] = useState(false);
  const until = status?.until ? formatDate(new Date(status.until)) : null;
  const line = isLifetime(status)
    ? ui.support.lifetimePass
    : status?.renews && until
      ? ui.support.yearRenews({ date: until })
      : until
        ? ui.support.passEnds({ date: until })
        : "";
  return (
    <>
      <header className="support-head">
        <h3>
          <SupporterMark size={20} /> {ui.support.supporterTitle}
        </h3>
        <p>{line}</p>
      </header>
      <label className="support-mark-choice">
        <input
          type="checkbox"
          checked={showMark}
          onChange={(event) => {
            setSaveFailed(false);
            void setShowMark(event.target.checked).catch(() => setSaveFailed(true));
          }}
        />
        <span>
          <strong>{ui.support.showMark}</strong>
          <small>{ui.support.showMarkOff}</small>
        </span>
      </label>
      {saveFailed && (
        <p className="auth-error" role="alert">
          {ui.support.markNotSaved}
        </p>
      )}
      <div className="support-links">
        {/* A new tab, because this overlay can be open over a room in play. */}
        {status?.renews && (
          <a
            className="support-cancel-link"
            href="/support/cancel"
            target="_blank"
            rel="noopener noreferrer"
          >
            {ui.support.cancelRenewal}
          </a>
        )}
        <small>{ui.support.receipts}</small>
      </div>
    </>
  );
}

/** Settings → Support (#1475): the pitch, the guest's version of it, or a
supporter's own pass. */
export function SupportPane() {
  const user = useAuthStore((state) => state.user);
  const plans = useSupportStore((state) => state.plans);
  const status = useSupportStore((state) => state.status);
  const refresh = useSupportStore((state) => state.refresh);
  const isRegistered = Boolean(user && !user.isAnonymous);
  const openSettings = useOpenSettings();

  useEffect(() => {
    if (isRegistered) void refresh();
  }, [isRegistered, refresh]);

  if (!plans) return null;
  const body = isRegistered && status?.active ? (
    <SupporterView />
  ) : (
    <Pitch>
      {isRegistered ? (
        <Checkout plans={plans} />
      ) : (
        <div className="support-account">
          <p>{ui.support.needAccount}</p>
          {/* Not a link: leaving this overlay's page would unmount a room the
              guest is seated in, without leaving it (R-UX-15). */}
          <button type="button" className="btn btn-primary" onClick={() => openSettings("account")}>
            {ui.support.createAccount}
          </button>
        </div>
      )}
    </Pitch>
  );
  return (
    <div className="support-pane" data-testid="support-pane">
      {body}
      {plans.tipUrl && <TipLink url={plans.tipUrl} />}
    </div>
  );
}
