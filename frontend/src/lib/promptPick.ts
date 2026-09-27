/** What the drawer's pick sends: the offer's position, and the turn the
offers were made for.

By position rather than by text (#1181): the text is how the drawer's
language spells the offer. A position is valid in every turn's offers,
though, so the turn `your_prompt_choices` named goes back with it and a click
that lands after the turn moved on is refused rather than taken as a pick
among offers the drawer never saw. */
export function promptPickPayload(
  index: number,
  turnId: string | null,
): { index: number; turnId?: string } {
  return turnId ? { index, turnId } : { index };
}
