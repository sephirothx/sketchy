import { formattersFor } from "../ui/format.ts";
import type { SeoCopy } from "./types.ts";

/** The descriptions, in Nederlands: machine-drafted from [`en.ts`](./en.ts) like the
rest of the interface, awaiting a native reader (#784). */
const { counted } = formattersFor("nl");

export const SEO_NL: SeoCopy = {
  locale: "nl",
  home: "Een gratis online teken- en raadspel, zoals Pictionary. Speel met vrienden in je browser: geen account, geen download.",
  rules: "De regels die Sketchy leuk houden: hoe je met anderen omgaat, wat je tekent en schrijft, eerlijk spel, en wat er gebeurt als iemand een regel breekt.",
  terms: "De voorwaarden om Sketchy te spelen: wie mag spelen, accounts, wat je tekent en schrijft, moderatie en stoppen.",
  privacy: "Wat Sketchy over je bewaart, waarom, hoe lang, en wat je eraan kunt doen. Geen reclame, en niets over jou wordt verkocht.",
  solo: "Raad in je eentje tekeningen uit echte spellen: elke dag een nieuwe Dagpuzzel en vrije rondes wanneer je wilt.",
  promptList: (p) =>
    `${counted(p.count, { one: "woord", other: "woorden" })} uit ${p.name} voor teken- en raadspellen zoals Pictionary, met hoe vaak spelers elk woord echt raden.`,
};
