import { formattersFor } from "../ui/format.ts";
import type { SeoCopy } from "./types.ts";

/** The descriptions, in français: machine-drafted from [`en.ts`](./en.ts) like the
rest of the interface, awaiting a native reader (#784). */
const { counted } = formattersFor("fr");

export const SEO_FR: SeoCopy = {
  locale: "fr",
  home: "Un jeu gratuit de dessin et de devinettes en ligne, comme Pictionary. Joue avec tes amis dans ton navigateur : sans compte, sans téléchargement.",
  rules: "Les règles qui gardent Sketchy agréable : comment traiter les autres, ce que tu dessines et écris, le fair-play, et ce qui arrive en cas d’infraction.",
  terms: "Les conditions pour jouer à Sketchy : qui peut jouer, les comptes, ce que tu dessines et écris, la modération et comment partir.",
  privacy: "Ce que Sketchy conserve sur toi, pourquoi, combien de temps, et ce que tu peux y faire. Pas de publicité, et rien sur toi n’est vendu.",
  solo: "Devine seul des dessins tirés de vraies parties : un nouveau Défi du jour chaque jour, et des parties libres quand tu veux.",
  promptList: (p) =>
    `${counted(p.count, { one: "mot", other: "mots" })} de ${p.name} pour les jeux de dessin et de devinettes comme Pictionary, avec la fréquence à laquelle chacun est vraiment deviné.`,
};
