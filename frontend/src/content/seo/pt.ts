import { formattersFor } from "../ui/format.ts";
import type { SeoCopy } from "./types.ts";

/** The descriptions, in português: machine-drafted from [`en.ts`](./en.ts) like the
rest of the interface, awaiting a native reader (#784). */
const { counted } = formattersFor("pt");

export const SEO_PT: SeoCopy = {
  locale: "pt",
  home: "Um jogo gratuito de desenhar e adivinhar online, como o Pictionary. Joga com os teus amigos no navegador: sem conta e sem transferências.",
  rules: "As regras que tornam o Sketchy divertido: como tratas os outros, o que desenhas e escreves, o jogo limpo e o que acontece quando uma regra é quebrada.",
  terms: "Os termos para jogar Sketchy: quem pode jogar, as contas, o que desenhas e escreves, a moderação e como sair.",
  privacy: "O que o Sketchy guarda sobre ti, porquê, durante quanto tempo e o que podes fazer. Sem publicidade, e nada sobre ti é vendido.",
  solo: "Adivinha sozinho desenhos de jogos reais: um novo Desafio do dia todos os dias e partidas livres sempre que quiseres.",
  promptList: (p) =>
    `${counted(p.count, { one: "palavra", other: "palavras" })} de ${p.name} para jogos de desenhar e adivinhar como o Pictionary, com a frequência com que os jogadores adivinham cada uma.`,
};
