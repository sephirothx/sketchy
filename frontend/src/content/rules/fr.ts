import type { RulesDocument } from "./types.ts";

/** The rules, in French.

A translation of [`en.ts`](./en.ts), which stays the reference: when the
English changes, this is stale until it follows.

Machine-drafted and **not yet read by a native speaker**. The rules are the
one text where a bad translation has consequences - somebody reads them after
being told they broke one, and a mistranslated prohibition is a decision they
cannot check - so this wants a human pass before launch (R-I18N-07).

The ids are not translated and never will be: they are anchors, and a notice
linking to `#spam` has to survive the page being read in French
(R-RULES-03). */
export const RULES_FR: RulesDocument = {
  locale: "fr",
  title: "Règles",
  introHeading: "Introduction",
  intro: [
    "Sketchy est un jeu auquel tu joues avec des inconnus, et presque tout y fonctionne parce que la plupart des gens sont corrects sans qu’on le leur demande. Ces règles sont pour les fois où ce n’est pas le cas — et pour que, si un modérateur intervient un jour, ce ne soit pas une surprise.",
    "L’essentiel de ce qui dérape ici n’est pas de la méchanceté. Tout le monde peut avoir une mauvaise journée, une blague peut mal tomber, et tu ne sais jamais vraiment ce que traverse la personne de l’autre côté d’un dessin. Pars de là d’abord, et l’essentiel ne vaut même plus un signalement.",
    "Rien de tout cela n’est ici comme un bâton. C’est ici pour que les salons restent un endroit où l’on débarque, où l’on dessine quelque chose de ridicule et où l’on se détend. Quand il faut vraiment trancher, on se fonde sur ce qui s’est passé et non sur qui tu es : un modérateur lit ce qui a réellement été dit ou dessiné, dans l’ordre où c’est arrivé, et décide à partir de là.",
  ],
  sections: [
    {
      id: "conduct",
      heading: "Comment tu traites les autres",
      blurb: "Tu joues avec des gens qui ne peuvent pas simplement s’en aller sans quitter la partie. Ces deux règles parlent de ça.",
      rules: [
        {
          id: "harassment",
          heading: "Harcèlement",
          body: [
            "Ne t’en prends pas aux autres joueurs. Pas d’insultes, pas de menaces, pas de rabaissement — et cela inclut les injures et la haine sous toutes leurs formes, le harcèlement sexuel, et le fait de suivre quelqu’un de salon en salon pour continuer.",
            "Les piques font la moitié du plaisir et il n’y a rien de mal à ça — tant que tout le monde est vraiment de la partie et que ça ne va pas trop loin. La limite, c’est le moment où ce n’est plus partagé : quand quelqu’un en a assez, ou quand ça vise une personne qui ne rit pas. Si tu ne sais pas, lève le pied. Ça ne te coûte rien.",
            "Et perdre lourdement une manche n’est pas une raison de s’en prendre à celui qui a gagné, pas plus que de voir quelqu’un dessiner quelque chose qui ne te plaît pas.",
          ],
          examples: [
            "S’acharner sur le dessin de quelqu’un jusqu’à ce que ça vise la personne",
            "S’en prendre à l’origine, la religion, le sexe, le genre, le handicap ou la nationalité de quelqu’un",
            "Suivre quelqu’un dans un salon pour poursuivre une dispute",
          ],
        },
        {
          id: "spam",
          heading: "Spam",
          body: [
            "N’inonde pas le chat, ne te répète pas pour couvrir tout le monde, et ne te sers pas du jeu pour faire de la publicité.",
            "Deviner n’est pas du spam, aussi farfelues que soient les propositions — deviner vite, c’est tout l’intérêt.",
          ],
          examples: [
            "Répéter un message jusqu’à ce que plus personne ne puisse suivre la manche",
            "Publier des liens ou des invitations vers ailleurs",
            "Coller le même pavé de texte dans un salon après l’autre",
          ],
        },
      ],
    },
    {
      id: "content",
      heading: "Ce que tout le monde doit regarder",
      blurb: "Ton dessin, ton nom et ton image atterrissent devant des gens qui ne les ont pas choisis. Personne ne peut détourner les yeux du tableau et continuer à jouer.",
      rules: [
        {
          id: "offensive_drawing",
          heading: "Dessins offensants",
          body: [
            "Dessine le mot. Le tableau n’est pas l’endroit pour du contenu sexuel, du gore, des symboles haineux ou pour s’en prendre à quelqu’un dans le salon.",
            "Mal dessiner n’est pas contraire aux règles — personne ne juge tes cercles. Il s’agit de dessiner autre chose exprès.",
          ],
          examples: [
            "Dessins sexuels ou sanglants",
            "Symboles haineux, même grossièrement dessinés",
            "Dessiner une insulte à propos de quelqu’un au lieu du mot",
          ],
        },
        {
          id: "inappropriate_name",
          heading: "Noms inappropriés",
          body: [
            "Tous ceux avec qui tu joues voient ton nom : garde donc les injures, les termes sexuels et les noms faits pour agacer quelqu’un en dehors de ça.",
            "Et ne te fais pas passer pour un autre joueur ni pour un modérateur.",
          ],
          examples: [
            "Un nom contenant une injure ou un terme sexuel",
            "Un nom fait pour ressembler à celui de quelqu’un d’autre",
            "Un nom qui vise une personne en particulier",
          ],
        },
        {
          id: "inappropriate_avatar",
          heading: "Images inappropriées",
          body: [
            "Même chose pour l’image de ton compte — elle apparaît sur ton profil et à côté de ton nom partout où tu joues.",
            "Un modérateur peut retirer une image sans que rien d’autre n’arrive à ton compte, et la première fois tu peux en remettre une aussitôt.",
          ],
          examples: [
            "Images sexuelles ou explicites",
            "Symboles haineux ou imagerie extrémiste",
            "Une photo de quelqu’un qui n’a pas accepté d’y figurer",
          ],
        },
      ],
    },
    {
      id: "fair-play",
      heading: "Jouer franc jeu",
      blurb: "Le jeu ne fonctionne que si les propositions sont sincères.",
      rules: [
        {
          id: "cheating",
          heading: "Triche",
          body: [
            "Ne donne le mot à personne qui est censé le deviner — ni dans le chat, ni dans le dessin, ni ailleurs en dehors du jeu. Et ne fais pas jouer un programme à ta place.",
            "Écrire le mot sur le tableau revient à le dire.",
          ],
          examples: [
            "Écrire ou épeler le mot pendant que tu le dessines",
            "Donner le mot à un ami par appel ou par une autre application",
            "Utiliser un second compte pour te souffler les réponses",
          ],
        },
      ],
    },
  ],
  enforcement: {
    heading: "Ce qui se passe si tu en enfreins une",
    body: [
      "Les signalements vont à un modérateur, qui voit ce qui a réellement été dit ou dessiné. La plupart se terminent sans rien : les gens signalent des choses qui s’avèrent correctes, et c’est exactement à cela que sert le signalement.",
      "Si quelque chose n’allait pas, un modérateur peut t’adresser un avertissement, retirer une image ou suspendre le compte. Un avertissement ne restreint rien, mais un nouveau signalement après un avertissement peut mener à une suspension. Une suspension peut durer un jour, une semaine, un mois, ou n’avoir aucune fin, et on te dira laquelle.",
      "Quoi qu’il arrive, on te dira de quoi il s’agissait et on te montrera tes propres mots, ou ton propre dessin, derrière. Personne ne cherche à te piéger.",
    ],
  },
};
