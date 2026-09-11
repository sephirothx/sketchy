import type { RulesDocument } from "./types.ts";

/** The rules, in German.

A translation of [`en.ts`](./en.ts), which stays the reference: when the
English changes, this is stale until it follows.

Machine-drafted and **not yet read by a native speaker**. The rules are the
one text where a bad translation has consequences - somebody reads them after
being told they broke one, and a mistranslated prohibition is a decision they
cannot check - so this wants a human pass before launch (R-I18N-07).

The ids are not translated and never will be: they are anchors, and a notice
linking to `#spam` has to survive the page being read in German
(R-RULES-03). */
export const RULES_DE: RulesDocument = {
  locale: "de",
  title: "Regeln",
  introHeading: "Einleitung",
  intro: [
    "Sketchy ist ein Spiel, das du mit Fremden spielst, und fast alles daran funktioniert, weil die meisten Leute anständig sind, ohne dass man sie darum bitten muss. Diese Regeln sind für die Momente, in denen das nicht gilt — und dafür, dass es keine Überraschung ist, wenn doch einmal ein Moderator einschreitet.",
    "Das meiste, was hier schiefgeht, ist keine Bosheit. Einen schlechten Tag kann jeder haben, ein Witz kann danebengehen, und du weißt nie wirklich, womit jemand auf der anderen Seite einer Zeichnung gerade zu tun hat. Geh erst davon aus, und das meiste ist gar keine Meldung mehr wert.",
    "Nichts davon steht hier als Knüppel. Es steht hier, damit die Räume ein Ort bleiben, an dem Leute auftauchen, etwas Absurdes zeichnen und sich entspannen können. Wenn wir doch etwas entscheiden müssen, richten wir uns danach, was passiert ist, und nicht danach, wer du bist: ein Moderator liest, was tatsächlich gesagt oder gezeichnet wurde, in der Reihenfolge, in der es passiert ist, und entscheidet von da aus.",
  ],
  sections: [
    {
      id: "conduct",
      heading: "Wie du mit anderen umgehst",
      blurb: "Du spielst mit Leuten, die nicht einfach weggehen können, ohne das Spiel zu verlassen. Diese beiden Regeln drehen sich darum.",
      rules: [
        {
          id: "harassment",
          heading: "Belästigung",
          body: [
            "Geh andere Spieler nicht an. Keine Beleidigungen, keine Drohungen, kein Heruntermachen — dazu gehören auch Schmähungen und Hass jeder Art, sexuelle Belästigung und jemandem von Raum zu Raum zu folgen, um weiterzumachen.",
            "Frotzeleien sind die halbe Freude und daran ist nichts falsch — solange alle wirklich mitmachen und es nicht zu weit geht. Die Grenze liegt da, wo es aufhört, geteilt zu sein: wenn es jemandem reicht, oder wenn es auf eine Person zielt, die nicht lacht. Wenn du es nicht einschätzen kannst, lass es. Es kostet dich nichts.",
            "Und eine Runde übel zu verlieren ist kein Grund, es an der Gewinnerin oder dem Gewinner auszulassen — genauso wenig, wie es einer ist, wenn jemand etwas zeichnet, das dir nicht gefällt.",
          ],
          examples: [
            "Auf jemandes Zeichnung herumhacken, bis es eigentlich um die Person geht",
            "Jemanden wegen Herkunft, Religion, Geschlecht, Behinderung oder Nationalität angehen",
            "Jemandem in einen Raum folgen, um einen Streit fortzusetzen",
          ],
        },
        {
          id: "spam",
          heading: "Spam",
          body: [
            "Flute den Chat nicht, wiederhole dich nicht, um alle anderen zu übertönen, und nutze das Spiel nicht als Werbefläche.",
            "Raten ist kein Spam, egal wie wild die Vermutungen werden — schnell zu raten ist genau der Sinn der Sache.",
          ],
          examples: [
            "Eine Nachricht so lange wiederholen, dass niemand der Runde folgen kann",
            "Links oder Einladungen zu etwas anderem posten",
            "Dieselbe Textwand in einen Raum nach dem anderen einfügen",
          ],
        },
      ],
    },
    {
      id: "content",
      heading: "Was alle anderen ansehen müssen",
      blurb: "Deine Zeichnung, dein Name und dein Bild landen vor Leuten, die sie sich nicht ausgesucht haben. Von der Leinwand kann niemand wegsehen und trotzdem weiterspielen.",
      rules: [
        {
          id: "offensive_drawing",
          heading: "Anstößige Zeichnungen",
          body: [
            "Zeichne den Begriff. Die Leinwand ist nicht der Ort für sexuelle Inhalte, Gewaltdarstellungen, Hasssymbole oder Seitenhiebe auf jemanden im Raum.",
            "Schlecht zeichnen zu können verstößt gegen keine Regel — über deine Kreise urteilt niemand. Es geht darum, absichtlich etwas anderes zu zeichnen.",
          ],
          examples: [
            "Sexuelle oder blutige Zeichnungen",
            "Hasssymbole, wie grob auch immer gezeichnet",
            "Statt des Begriffs eine Beleidigung über jemanden zeichnen",
          ],
        },
        {
          id: "inappropriate_name",
          heading: "Unpassende Namen",
          body: [
            "Alle, mit denen du spielst, sehen deinen Namen: lass also Schmähungen, sexuelle Ausdrücke und Namen weg, die jemanden ärgern sollen.",
            "Und gib dich nicht als anderer Spieler oder als Moderator aus.",
          ],
          examples: [
            "Ein Name mit einer Schmähung oder einem sexuellen Ausdruck darin",
            "Ein Name, der wie der von jemand anderem aussehen soll",
            "Ein Name, der auf eine bestimmte Person zielt",
          ],
        },
        {
          id: "inappropriate_avatar",
          heading: "Unpassende Bilder",
          body: [
            "Dasselbe gilt für dein Kontobild — es steht in deinem Profil und neben deinem Namen, wo immer du spielst.",
            "Ein Moderator kann ein Bild entfernen, ohne dass mit deinem Konto sonst etwas passiert, und beim ersten Mal kannst du sofort ein neues hochladen.",
          ],
          examples: [
            "Sexuelle oder drastische Bilder",
            "Hasssymbole oder extremistische Bildsprache",
            "Ein Foto von jemandem, der nicht zugestimmt hat, dort zu stehen",
          ],
        },
      ],
    },
    {
      id: "fair-play",
      heading: "Fair spielen",
      blurb: "Das Spiel funktioniert nur, wenn das Raten echt ist.",
      rules: [
        {
          id: "cheating",
          heading: "Schummeln",
          body: [
            "Gib den Begriff niemandem, der ihn erraten soll — nicht im Chat, nicht in der Zeichnung, nicht irgendwo außerhalb des Spiels. Und lass kein Programm für dich spielen.",
            "Das Wort auf die Leinwand zu schreiben zählt, als hättest du es gesagt.",
          ],
          examples: [
            "Den Begriff beim Zeichnen hinschreiben oder buchstabieren",
            "Einem Freund den Begriff per Anruf oder über eine andere App verraten",
            "Ein zweites Konto benutzen, um dir selbst Antworten zuzuspielen",
          ],
        },
      ],
    },
  ],
  enforcement: {
    heading: "Was passiert, wenn du gegen eine Regel verstößt",
    body: [
      "Meldungen gehen an einen Moderator, der sieht, was tatsächlich gesagt oder gezeichnet wurde. Die meisten enden damit, dass nichts passiert — Leute melden Dinge, die sich als in Ordnung herausstellen, und genau dafür ist Melden da.",
      "War etwas nicht in Ordnung, kann ein Moderator dich verwarnen, ein Bild entfernen oder das Konto sperren. Eine Verwarnung schränkt nichts ein, aber eine weitere Meldung danach kann zu einer Sperre führen. Eine Sperre kann einen Tag, eine Woche, einen Monat oder unbefristet dauern, und dir wird gesagt, welche es ist.",
      "Was auch geschieht, dir wird gesagt, worum es ging, und du bekommst deine eigenen Worte oder deine eigene Zeichnung dazu gezeigt. Niemand versucht, dich zu überführen.",
    ],
  },
};
