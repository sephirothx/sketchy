import type { RulesDocument } from "./types.ts";

/** The rules, in Portuguese.

A translation of [`en.ts`](./en.ts), which stays the reference: when the
English changes, this is stale until it follows.

Machine-drafted and **not yet read by a native speaker**. The rules are the
one text where a bad translation has consequences - somebody reads them after
being told they broke one, and a mistranslated prohibition is a decision they
cannot check - so this wants a human pass before launch (R-I18N-07).

The ids are not translated and never will be: they are anchors, and a notice
linking to `#spam` has to survive the page being read in Portuguese
(R-RULES-03). */
export const RULES_PT: RulesDocument = {
  locale: "pt",
  title: "Regras",
  introHeading: "Introdução",
  intro: [
    "O Sketchy é um jogo que se joga com desconhecidos, e quase tudo funciona porque a maioria das pessoas é decente sem que seja preciso pedir. Estas regras são para as vezes em que isso não acontece — e para que, se algum dia um moderador intervier, não seja uma surpresa.",
    "Quase tudo o que corre mal aqui não é maldade. Um dia mau acontece a qualquer um, uma piada pode cair mal, e nunca sabes mesmo com o que está a lidar quem está do outro lado de um desenho. Parte daí primeiro e a maior parte deixa de valer uma denúncia.",
    "Nada disto está aqui como um pau. Está aqui para que as salas continuem a ser um sítio onde as pessoas aparecem, desenham algo ridículo e descontraem. Quando temos mesmo de decidir alguma coisa, guiamo-nos pelo que aconteceu e não por quem tu és: um moderador lê o que foi mesmo dito ou desenhado, pela ordem em que aconteceu, e decide a partir daí.",
  ],
  sections: [
    {
      id: "conduct",
      heading: "Como tratas os outros",
      blurb: "Estás a jogar com pessoas que não se podem ir embora sem deixar a partida. Estas duas regras são sobre isso.",
      rules: [
        {
          id: "harassment",
          heading: "Assédio",
          body: [
            "Não vás atrás de outros jogadores. Nada de insultos, ameaças ou humilhações — e isso inclui ofensas e ódio de qualquer tipo, assédio sexual, e seguir alguém de sala em sala para continuar.",
            "As picardias são metade da graça e não têm nada de mal — desde que toda a gente esteja mesmo dentro e não se passe da conta. O limite é onde deixa de ser partilhado: quando alguém já teve que chegue, ou quando é apontado a uma pessoa que não se está a rir. Se não consegues perceber, alivia. Não te custa nada.",
            "E perder feio uma ronda não é motivo para descarregares em quem ganhou, tal como não o é alguém desenhar algo de que não gostas.",
          ],
          examples: [
            "Insistir no desenho de alguém até aquilo ser mesmo sobre a pessoa",
            "Atacar a origem, a religião, o sexo, o género, a deficiência ou a nacionalidade de alguém",
            "Seguir alguém para uma sala para continuar uma discussão",
          ],
        },
        {
          id: "spam",
          heading: "Spam",
          body: [
            "Não inundes a conversa, não te repitas para abafar os outros e não uses o jogo para anunciar seja o que for.",
            "Tentar adivinhar não é spam, por mais loucos que sejam os palpites — adivinhar depressa é o objetivo.",
          ],
          examples: [
            "Repetir uma mensagem até ninguém conseguir acompanhar a ronda",
            "Publicar ligações ou convites para outro sítio",
            "Colar a mesma parede de texto numa sala atrás da outra",
          ],
        },
      ],
    },
    {
      id: "content",
      heading: "O que todos os outros têm de ver",
      blurb: "O teu desenho, o teu nome e a tua imagem aparecem à frente de pessoas que não os escolheram. Ninguém pode desviar o olhar da tela e continuar a jogar.",
      rules: [
        {
          id: "offensive_drawing",
          heading: "Desenhos ofensivos",
          body: [
            "Desenha a palavra. A tela não é sítio para conteúdo sexual, sangue, símbolos de ódio ou para te meteres com alguém da sala.",
            "Desenhar mal não é contra as regras — ninguém está a julgar os teus círculos. Isto é sobre desenhar outra coisa de propósito.",
          ],
          examples: [
            "Desenhos sexuais ou sangrentos",
            "Símbolos de ódio, por mais tosco que seja o desenho",
            "Desenhar um insulto sobre alguém em vez da palavra",
          ],
        },
        {
          id: "inappropriate_name",
          heading: "Nomes impróprios",
          body: [
            "Toda a gente com quem jogas vê o teu nome, por isso deixa de fora ofensas, termos sexuais e nomes feitos para picar alguém.",
            "E não te faças passar por outro jogador nem por um moderador.",
          ],
          examples: [
            "Um nome com uma ofensa ou um termo sexual lá dentro",
            "Um nome feito para parecer o de outra pessoa",
            "Um nome que é uma alfinetada a uma pessoa em concreto",
          ],
        },
        {
          id: "inappropriate_avatar",
          heading: "Imagens impróprias",
          body: [
            "O mesmo vale para a imagem da tua conta — está no teu perfil e ao lado do teu nome onde quer que jogues.",
            "Um moderador pode retirar uma imagem sem que aconteça mais nada à tua conta, e da primeira vez podes pôr outra logo a seguir.",
          ],
          examples: [
            "Imagens sexuais ou explícitas",
            "Símbolos de ódio ou imagens extremistas",
            "Uma fotografia de alguém que não concordou em lá estar",
          ],
        },
      ],
    },
    {
      id: "fair-play",
      heading: "Jogar limpo",
      blurb: "O jogo só funciona se os palpites forem a sério.",
      rules: [
        {
          id: "cheating",
          heading: "Batota",
          body: [
            "Não passes a palavra a ninguém que a tenha de adivinhar — nem na conversa, nem no desenho, nem fora do jogo. E não ponhas um programa a jogar por ti.",
            "Escrever a palavra na tela conta como dizê-la.",
          ],
          examples: [
            "Escrever ou soletrar a palavra enquanto a desenhas",
            "Dizer a palavra a um amigo por chamada ou por outra aplicação",
            "Usar uma segunda conta para te passares respostas a ti próprio",
          ],
        },
      ],
    },
  ],
  enforcement: {
    heading: "O que acontece se quebrares uma",
    body: [
      "As denúncias vão para um moderador, que vê o que foi mesmo dito ou desenhado. A maior parte acaba sem acontecer nada — as pessoas denunciam coisas que se revelam bem, e é exatamente para isso que serve denunciar.",
      "Se algo esteve mal, um moderador pode dar-te um aviso, retirar uma imagem ou suspender a conta. Um aviso não restringe nada, mas outra denúncia a seguir pode levar a uma suspensão. Uma suspensão pode durar um dia, uma semana, um mês, ou não ter fim à vista, e ser-te-á dito qual.",
      "Aconteça o que acontecer, ser-te-á dito do que se tratava e mostradas as tuas próprias palavras, ou o teu próprio desenho, por trás disso. Ninguém está a tentar apanhar-te.",
    ],
  },
};
