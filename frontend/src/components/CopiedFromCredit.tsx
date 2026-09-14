import { Link } from "react-router-dom";
import { fill } from "../content/ui/slots.tsx";
import type { CopiedFrom } from "../types";
import { CopyIcon } from "./icons";

/** "Copied from Creatures of the deep by Ada" — the credit a copy carries for
 * the list it was taken from (R-LIST-21), wherever a copy is shown.
 *
 * The original is named and credited to its author whatever became of it,
 * except when its author deleted it: then the copy says only that it was
 * copied, because naming it would keep what that author asked to take away.
 * The name links only while the original is in the catalogue — a link to a
 * list that is not would open a page that refuses it.
 *
 * The sentences are passed in rather than read here, so each screen keeps its
 * own copy in its own group of the catalogue. */
export function CopiedFromCredit({
  credit,
  className,
  sentence,
  deletedSentence,
}: {
  credit: CopiedFrom;
  className: string;
  /** A template with `{list}` and `{owner}` slots. */
  sentence: string;
  deletedSentence: string;
}) {
  if (credit.status === "deleted" || credit.name === null) {
    return <p className={className}><CopyIcon size={14} /><span>{deletedSentence}</span></p>;
  }
  const list = credit.status === "published" && credit.listId
    ? <Link to={`/community-lists/${encodeURIComponent(credit.listId)}`}>{credit.name}</Link>
    : <strong>{credit.name}</strong>;
  return <p className={className}>
    <CopyIcon size={14} />
    <span>{fill(sentence, { list, owner: <strong>{credit.ownerDisplayName}</strong> })}</span>
  </p>;
}
