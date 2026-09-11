import type { ReactNode } from "react";

/** A sentence with something rendered inside it - a link, a coloured name.

The problem this solves is word order. *"Recorded as **spam**"* has to keep
the link on the category, and a language that puts the category first must be
able to say so - which it cannot if the sentence is stored as two halves with
a component between them. Half a sentence is not translatable, and a
catalogue full of halves is the failure this whole epic is avoiding.

So the catalogue keeps the **whole** sentence with a named slot in it -
`"Recorded as {category}"` - and the component says what goes in the slot. A
translator moves the token wherever their language wants it.

Used only where a node really has to sit inside the text; a sentence that
merely mentions a value takes the value as a parameter instead. */
export function fill(template: string, slots: Record<string, ReactNode>): ReactNode[] {
  const parts: ReactNode[] = [];
  const pattern = /\{(\w+)\}/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let key = 0;
  while ((match = pattern.exec(template)) !== null) {
    if (match.index > last) parts.push(template.slice(last, match.index));
    const name = match[1];
    // An unknown slot renders as its own token rather than disappearing: a
    // translation that mistypes one is then visibly wrong instead of quietly
    // dropping a name.
    parts.push(
      name in slots ? <span key={`slot-${key++}`}>{slots[name]}</span> : match[0],
    );
    last = match.index + match[0].length;
  }
  if (last < template.length) parts.push(template.slice(last));
  return parts;
}
