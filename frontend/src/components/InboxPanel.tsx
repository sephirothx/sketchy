import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { BottomSheet } from "./ui/BottomSheet";
import { ConfirmationDialog } from "./ConfirmationDialog";
import {
  AlertCircleIcon,
  CheckIcon,
  CrownIcon,
  ImageIcon,
  InboxIcon,
  SendIcon,
  UserIcon,
  UsersIcon,
} from "./icons";
import { useFriendInviteAnswer } from "../hooks/useFriendInviteAnswer";
import { useOpenSettings } from "../hooks/useSettingsRoute";
import { galleryAge, withdrawFromGallery } from "../lib/gallery";
import { invitationStillOpen, type InboxEntry, type InboxPerson } from "../lib/inbox";
import { roleNoticeText } from "../lib/operatorAccess";
import { playerNameClass, playerNameStyle } from "../lib/playerName";
import { useToast } from "../lib/toast";
import { ruleAnchorFor } from "../content/rules/anchors.ts";
import { useFriendsStore } from "../store/friendsStore";
import { useInboxStore } from "../store/inboxStore";
import { usePinsStore } from "../store/pinsStore";
import { ui } from "../content/ui/index.ts";
import { fill } from "../content/ui/slots.tsx";
import "../styles/lazy/inbox.css";

interface InboxPanelProps {
  /** A sheet on a phone, a panel under the bell elsewhere. */
  asSheet: boolean;
  onClose: () => void;
}

/** The inbox's list (#1436): newest first, unread first among them, each row
saying what happened and leading to where it can be acted on. Acting on a row
reads it; so does **Mark all as read**. */
export default function InboxPanel({ asSheet, onClose }: InboxPanelProps) {
  const entries = useInboxStore((state) => state.entries);
  const unread = useInboxStore((state) => state.unreadCount);
  const next = useInboxStore((state) => state.next);
  const loadingMore = useInboxStore((state) => state.loadingMore);
  const loadMore = useInboxStore((state) => state.loadMore);
  const markAllRead = useInboxStore((state) => state.markAllRead);

  const fresh = entries.filter((entry) => !entry.read);
  const earlier = entries.filter((entry) => entry.read);
  const markAll =
    unread > 0 ? (
      <button type="button" className="inbox-link" onClick={() => void markAllRead()} data-testid="inbox-mark-all">
        {ui.inbox.markAllRead}
      </button>
    ) : null;

  const body =
    entries.length === 0 ? (
      <div className="inbox-empty" data-testid="inbox-empty">
        <span className="inbox-kind" aria-hidden="true">
          <InboxIcon size={22} />
        </span>
        <p>
          <strong>{ui.inbox.nothingHereYet}</strong>
          {ui.inbox.whatArrivesHere}
        </p>
      </div>
    ) : (
      <div className="inbox-list" data-testid="inbox-list">
        {fresh.length > 0 && <Group label={ui.inbox.newGroup} entries={fresh} onClose={onClose} />}
        {earlier.length > 0 && <Group label={ui.inbox.earlierGroup} entries={earlier} onClose={onClose} />}
        {next && (
          <div className="inbox-more">
            <button type="button" className="btn btn-secondary btn-compact" disabled={loadingMore} onClick={() => void loadMore()}>
              {ui.inbox.showOlder}
            </button>
          </div>
        )}
      </div>
    );

  if (asSheet) {
    return (
      <BottomSheet
        title={ui.inbox.inbox}
        onDismiss={onClose}
        closeLabel={ui.inbox.close}
        className="inbox-sheet"
        height="92dvh"
        headerAction={markAll}
        testId="inbox-panel"
      >
        {body}
      </BottomSheet>
    );
  }
  return (
    <div className="inbox-panel" role="dialog" aria-labelledby="inbox-title" data-testid="inbox-panel">
      <div className="inbox-head">
        <h2 id="inbox-title">{ui.inbox.inbox}</h2>
        {markAll}
      </div>
      {body}
    </div>
  );
}

function Group({ label, entries, onClose }: { label: string; entries: InboxEntry[]; onClose: () => void }) {
  return (
    <section aria-label={label}>
      <p className="section-label inbox-group">{label}</p>
      <ul className="inbox-rows">
        {entries.map((entry) => (
          <Row key={entry.id} entry={entry} onClose={onClose} />
        ))}
      </ul>
    </section>
  );
}

function Name({ person }: { person: Pick<InboxPerson, "displayName" | "nameColor"> & { isAnonymous?: boolean } }) {
  return (
    <strong
      className={playerNameClass(person.isAnonymous)}
      style={playerNameStyle(person.nameColor ?? undefined, person.isAnonymous)}
    >
      {person.displayName}
    </strong>
  );
}

function when(createdAt: string): string {
  const age = galleryAge(createdAt);
  return age ? ui.galleryPage.ago(age) : ui.galleryPage.justNow;
}

function Row({ entry, onClose }: { entry: InboxEntry; onClose: () => void }) {
  const markRead = useInboxStore((state) => state.markRead);
  const refresh = useInboxStore((state) => state.refresh);
  const owner = useInboxStore((state) => state.owner);
  const accept = useFriendsStore((state) => state.accept);
  const remove = useFriendsStore((state) => state.remove);
  const openSettings = useOpenSettings();
  const { invite, join } = useFriendInviteAnswer();
  const { notify } = useToast();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  const read = () => void markRead([entry.id]);
  async function act(action: () => Promise<unknown>) {
    if (busy) return;
    setBusy(true);
    read();
    try {
      await action();
    } catch {
      notify(ui.dialog.couldNotSave, "error");
    } finally {
      setBusy(false);
      if (owner) void refresh(owner);
    }
  }

  let icon: ReactNode;
  let tone = "";
  let text: ReactNode;
  let meta = when(entry.createdAt);
  let actions: ReactNode = null;

  switch (entry.kind) {
    case "warning": {
      tone = "is-danger";
      const removal = entry.warning.kind === "avatar_removal";
      icon = removal ? <UserIcon size={18} /> : <AlertCircleIcon size={18} />;
      text = removal ? (
        <strong>{ui.warningNotice.yourPictureWasRemoved}</strong>
      ) : (
        <>
          <strong>{ui.warningNotice.aModeratorWarning}</strong>
          {entry.warning.reason && <span className="inbox-quote">{entry.warning.reason}</span>}
        </>
      );
      if (entry.warning.acknowledged) meta = `${meta} · ${ui.inbox.acknowledged}`;
      actions = removal ? (
        <button
          type="button"
          className="inbox-link"
          onClick={() => {
            read();
            onClose();
            openSettings("account");
          }}
        >
          {ui.inbox.chooseAnotherPicture}
        </button>
      ) : (
        <Link
          className="inbox-link"
          to={entry.warning.category ? ruleAnchorFor(entry.warning.category) : "/rules"}
          onClick={() => {
            read();
            onClose();
          }}
        >
          {ui.inbox.readTheRules}
        </Link>
      );
      break;
    }
    case "drawing_shared": {
      tone = "is-primary";
      icon = <ImageIcon size={18} />;
      const prompt = <strong>{entry.drawing.prompt}</strong>;
      text = entry.drawing.sharedBy
        ? fill(ui.inbox.sharedYourDrawing, { sharer: <Name person={entry.drawing.sharedBy} />, prompt })
        : fill(ui.inbox.yourDrawingWasShared, { prompt });
      if (!entry.drawing.inGallery) {
        meta = `${meta} · ${ui.inbox.noLongerInTheGallery}`;
      } else {
        actions = (
          <>
            <Link
              className="btn btn-secondary btn-compact"
              to={`/gallery/${encodeURIComponent(entry.drawing.turnId)}`}
              onClick={() => {
                read();
                onClose();
              }}
            >
              {ui.inbox.view}
            </Link>
            <button type="button" className="btn btn-ghost btn-compact" disabled={busy} onClick={() => setConfirming(true)}>
              {ui.inbox.takeItOut}
            </button>
          </>
        );
      }
      break;
    }
    case "friend_request": {
      tone = "is-primary";
      icon = <UsersIcon size={18} />;
      text = fill(ui.inbox.wantsToBeFriends, { name: <Name person={entry.person} /> });
      if (entry.state === "pending") {
        actions = (
          <>
            <button type="button" className="btn btn-primary btn-compact" disabled={busy} onClick={() => void act(() => accept(entry.person.userId))}>
              {ui.inbox.accept}
            </button>
            <button type="button" className="btn btn-secondary btn-compact" disabled={busy} onClick={() => void act(() => remove(entry.person.userId))}>
              {ui.inbox.decline}
            </button>
          </>
        );
      } else {
        meta = `${meta} · ${entry.state === "friends" ? ui.inbox.friendsNow : ui.inbox.noLongerWaiting}`;
      }
      break;
    }
    case "friend_accepted":
      tone = "is-success";
      icon = <CheckIcon size={18} />;
      text = fill(ui.inbox.acceptedYourRequest, { name: <Name person={entry.person} /> });
      break;
    case "game_invite": {
      tone = "is-warm";
      icon = <SendIcon size={18} />;
      text = fill(ui.inbox.invitedYouToPlay, { name: <Name person={entry.person} /> });
      if (invitationStillOpen(entry.expiresAt, entry.person.userId, invite)) {
        actions = (
          <button
            type="button"
            className="btn btn-primary btn-compact"
            onClick={() => {
              read();
              onClose();
              join();
            }}
          >
            {ui.inbox.join}
          </button>
        );
      } else {
        meta = `${meta} · ${ui.inbox.expired}`;
      }
      break;
    }
    case "reports_reviewed":
      tone = "is-success";
      icon = <CheckIcon size={18} />;
      text = ui.inbox.reportsReviewed({ count: entry.count });
      break;
    case "role": {
      tone = "is-primary";
      icon = <CrownIcon size={18} />;
      // The account's own words for it, never the administrator's reason,
      // which was written for other administrators and stays in the ledger.
      const said = roleNoticeText(entry.role, { pending: entry.change === "offered" });
      text = (
        <>
          <strong>{said.title}</strong>
          <span className="inbox-detail">{said.body}</span>
        </>
      );
      if (entry.change === "offered") {
        if (entry.offerOpen) {
          actions = (
            <button
              type="button"
              className="btn btn-primary btn-compact"
              onClick={() => {
                read();
                onClose();
                openSettings("account");
              }}
            >
              {ui.inbox.setUpTwoFactor}
            </button>
          );
        } else {
          meta = `${meta} · ${ui.inbox.offerEnded}`;
        }
      }
      break;
    }
  }

  return (
    <li
      className={`inbox-item${entry.read ? "" : " is-unread"}`}
      data-testid="inbox-entry"
      data-kind={entry.kind}
      onClick={(event) => {
        // A press on the row reads it; its own buttons and links say so too.
        if (!entry.read && !(event.target as HTMLElement).closest("button, a")) read();
      }}
    >
      <span className={`inbox-kind ${tone}`} aria-hidden="true">
        {icon}
      </span>
      <div>
        <p className="inbox-text">{text}</p>
        <div className="inbox-meta">{meta}</div>
        {actions && <div className="inbox-actions">{actions}</div>}
      </div>
      {confirming && entry.kind === "drawing_shared" && (
        <ConfirmationDialog
          title={ui.shareControl.takeOutTitle}
          description={ui.shareControl.takeOutDescription}
          confirmLabel={ui.shareControl.takeOutConfirm}
          onCancel={() => setConfirming(false)}
          onConfirm={() => {
            setConfirming(false);
            const turnId = entry.drawing.turnId;
            void act(async () => {
              await withdrawFromGallery(turnId);
              usePinsStore.getState().forget(turnId);
            });
          }}
        />
      )}
    </li>
  );
}
