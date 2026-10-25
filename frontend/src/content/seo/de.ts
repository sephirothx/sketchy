import { formattersFor } from "../ui/format.ts";
import type { SeoCopy } from "./types.ts";

/** The descriptions, in Deutsch: machine-drafted from [`en.ts`](./en.ts) like the
rest of the interface, awaiting a native reader (#784). */
const { counted } = formattersFor("de");

export const SEO_DE: SeoCopy = {
  locale: "de",
  home: "Ein kostenloses Online-Zeichen- und Ratespiel, wie Montagsmaler. Spiel mit Freunden im Browser: kein Konto, kein Download.",
  rules: "Die Regeln, die Sketchy unterhaltsam halten: Umgang mit anderen, was du zeichnest und schreibst, Fairness, und was bei einem Regelverstoß passiert.",
  terms: "Die Bedingungen für Sketchy: wer spielen darf, Konten, was du zeichnest und schreibst, Moderation und wie du aufhörst.",
  privacy: "Was Sketchy über dich speichert, warum, wie lange und was du dagegen tun kannst. Keine Werbung, und nichts über dich wird verkauft.",
  solo: "Errate allein Zeichnungen aus echten Spielen: jeden Tag ein neues Tagesrätsel und freie Runden, wann immer du willst.",
  promptList: (p) =>
    `${counted(p.count, { one: "Begriff", other: "Begriffe" })} aus ${p.name} für Zeichen- und Ratespiele wie Montagsmaler, mit der Angabe, wie oft jeder tatsächlich erraten wird.`,
};
