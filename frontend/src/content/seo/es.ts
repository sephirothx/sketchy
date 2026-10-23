import { formattersFor } from "../ui/format.ts";
import type { SeoCopy } from "./types.ts";

/** The descriptions, in español: machine-drafted from [`en.ts`](./en.ts) like the
rest of the interface, awaiting a native reader (#784). */
const { counted } = formattersFor("es");

export const SEO_ES: SeoCopy = {
  locale: "es",
  home: "Un juego gratis de dibujar y adivinar en línea, como Pictionary. Juega con tus amigos en el navegador: sin cuenta y sin descargas.",
  rules: "Las reglas que hacen divertido Sketchy: cómo tratas a los demás, qué dibujas y escribes, el juego limpio y qué pasa si alguien rompe una regla.",
  terms: "Las condiciones para jugar a Sketchy: quién puede jugar, las cuentas, lo que dibujas y escribes, la moderación y cómo irte.",
  privacy: "Qué guarda Sketchy sobre ti, por qué, durante cuánto tiempo y qué puedes hacer al respecto. Sin publicidad, y nada sobre ti se vende.",
  solo: "Adivina dibujos de partidas reales tú solo: un nuevo Reto diario cada día y partidas libres cuando quieras.",
  promptList: (p) =>
    `${counted(p.count, { one: "palabra", other: "palabras" })} de ${p.name} para juegos de dibujar y adivinar como Pictionary, con la frecuencia con que los jugadores adivinan cada una.`,
};
