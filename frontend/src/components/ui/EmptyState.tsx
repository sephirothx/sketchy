import type { ReactNode } from "react";

/**
 * What a list says when it has nothing in it: one recipe for every page.
 *
 * There were four - bare ink text in the lobby's rooms, muted text in the
 * chat and the online list, a solid card in the Community catalogue, a dashed
 * card with a button in the Gallery - on four neighbouring pages, so the same
 * situation looked like four different kinds of news. The Gallery's dashed
 * card won: it reads as a place something will go rather than as an error.
 *
 * `title` is the fact, `body` what to do about it, `action` the one control
 * that does it. `compact` is the size for a list inside a panel - the chat,
 * who is online, the Gallery's rail - where the page-sized card would be
 * louder than the panel around it.
 */
export function EmptyState({
  title,
  body,
  action,
  compact = false,
  className,
  testId,
}: {
  title: ReactNode;
  body?: ReactNode;
  action?: ReactNode;
  compact?: boolean;
  className?: string;
  testId?: string;
}) {
  const classes = ["empty-state", compact ? "is-compact" : "", className ?? ""].filter(Boolean).join(" ");
  return (
    <div className={classes} data-testid={testId}>
      <p className="empty-state-title">{title}</p>
      {body && <p className="empty-state-body">{body}</p>}
      {action && <div className="empty-state-action">{action}</div>}
    </div>
  );
}
