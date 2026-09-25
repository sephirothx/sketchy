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
 *
 * `heading` makes the title the page's `<h1>`, for a page whose whole content
 * is the empty state - a drawing that is not in the Gallery, a profile that
 * does not exist - and which would otherwise have no heading at all.
 */
export function EmptyState({
  title,
  body,
  action,
  compact = false,
  heading = false,
  className,
  testId,
}: {
  title: ReactNode;
  body?: ReactNode;
  action?: ReactNode;
  compact?: boolean;
  heading?: boolean;
  className?: string;
  testId?: string;
}) {
  const classes = ["empty-state", compact ? "is-compact" : "", className ?? ""].filter(Boolean).join(" ");
  return (
    <div className={classes} data-testid={testId}>
      {heading ? <h1 className="empty-state-title">{title}</h1> : <p className="empty-state-title">{title}</p>}
      {body && <p className="empty-state-body">{body}</p>}
      {action && <div className="empty-state-action">{action}</div>}
    </div>
  );
}
