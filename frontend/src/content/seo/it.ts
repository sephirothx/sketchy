import { formattersFor } from "../ui/format.ts";
import type { SeoCopy } from "./types.ts";

/** The descriptions, in italiano: machine-drafted from [`en.ts`](./en.ts) like the
rest of the interface, awaiting a native reader (#784). */
const { counted } = formattersFor("it");

export const SEO_IT: SeoCopy = {
  locale: "it",
  home: "Un gioco gratuito online per disegnare e indovinare, come Pictionary. Gioca con gli amici nel browser: niente account, niente download.",
  rules: "Le regole che rendono Sketchy divertente: come tratti gli altri, cosa disegni e scrivi, il gioco corretto e cosa succede se una regola viene infranta.",
  terms: "Le condizioni per giocare a Sketchy: chi può giocare, gli account, cosa disegni e scrivi, la moderazione e come andartene.",
  privacy: "Cosa conserva Sketchy su di te, perché, per quanto tempo e cosa puoi fare. Niente pubblicità, e nulla su di te viene venduto.",
  solo: "Indovina da solo i disegni di partite vere: una nuova Sfida del giorno ogni giorno e partite libere quando vuoi.",
  promptList: (p) =>
    `${counted(p.count, { one: "parola", other: "parole" })} da ${p.name} per giochi di disegno e indovinelli come Pictionary, con quanto spesso i giocatori indovinano davvero ciascuna.`,
};
