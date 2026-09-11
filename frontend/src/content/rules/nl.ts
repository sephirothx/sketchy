import type { RulesDocument } from "./types.ts";

/** The rules, in Dutch.

A translation of [`en.ts`](./en.ts), which stays the reference: when the
English changes, this is stale until it follows.

Machine-drafted and **not yet read by a native speaker**. The rules are the
one text where a bad translation has consequences - somebody reads them after
being told they broke one, and a mistranslated prohibition is a decision they
cannot check - so this wants a human pass before launch (R-I18N-07).

The ids are not translated and never will be: they are anchors, and a notice
linking to `#spam` has to survive the page being read in Dutch
(R-RULES-03). */
export const RULES_NL: RulesDocument = {
  locale: "nl",
  title: "Regels",
  introHeading: "Inleiding",
  intro: [
    "Sketchy is een spel dat je met vreemden speelt, en bijna alles werkt omdat de meeste mensen fatsoenlijk zijn zonder dat je het hoeft te vragen. Deze regels zijn voor de keren dat dat niet opgaat — en zodat het geen verrassing is als er ooit een moderator ingrijpt.",
    "Het meeste dat hier misgaat is geen kwade wil. Iedereen kan een rotdag hebben, een grap kan verkeerd vallen, en je weet nooit echt waar iemand aan de andere kant van een tekening mee bezig is. Ga daar eerst van uit, en het meeste is geen melding meer waard.",
    "Niets hiervan staat hier als stok. Het staat hier zodat de kamers een plek blijven waar mensen binnenlopen, iets belachelijks tekenen en ontspannen. Als we toch iets moeten beslissen, gaan we af op wat er gebeurd is en niet op wie je bent: een moderator leest wat er echt gezegd of getekend is, in de volgorde waarin het gebeurde, en beslist van daaruit.",
  ],
  sections: [
    {
      id: "conduct",
      heading: "Hoe je met anderen omgaat",
      blurb: "Je speelt met mensen die niet zomaar weg kunnen lopen zonder het spel te verlaten. Deze twee regels gaan daarover.",
      rules: [
        {
          id: "harassment",
          heading: "Pesten en intimidatie",
          body: [
            "Ga niet achter andere spelers aan. Geen scheldpartijen, dreigementen of vernederingen — en dat geldt ook voor beledigingen en haat van welke soort dan ook, seksuele intimidatie, en iemand van kamer naar kamer volgen om ermee door te gaan.",
            "Plagen is het halve plezier en daar is niets mis mee — zolang iedereen er echt in meegaat en het niet te ver gaat. De grens ligt waar het niet meer gedeeld is: als iemand er genoeg van heeft, of als het op één persoon gericht is die niet lacht. Als je het niet kunt inschatten, laat het dan. Het kost je niets.",
            "En een ronde zwaar verliezen is geen reden om het op de winnaar af te reageren, net zomin als iemand die iets tekent wat jij niet mooi vindt.",
          ],
          examples: [
            "Blijven doorgaan over iemands tekening tot het eigenlijk over die persoon gaat",
            "Iemand aanvallen op afkomst, geloof, sekse, gender, handicap of nationaliteit",
            "Iemand een kamer in volgen om een ruzie voort te zetten",
          ],
        },
        {
          id: "spam",
          heading: "Spam",
          body: [
            "Overspoel de chat niet, herhaal jezelf niet om iedereen te overstemmen, en gebruik het spel niet om iets te adverteren.",
            "Gokken is geen spam, hoe wild de gokken ook worden — snel gokken is juist de bedoeling.",
          ],
          examples: [
            "Een bericht herhalen tot niemand de ronde meer kan volgen",
            "Links of uitnodigingen naar ergens anders plaatsen",
            "Dezelfde muur tekst in kamer na kamer plakken",
          ],
        },
      ],
    },
    {
      id: "content",
      heading: "Waar iedereen naar moet kijken",
      blurb: "Je tekening, je naam en je afbeelding komen terecht voor mensen die ze niet gekozen hebben. Van het canvas kan niemand wegkijken en toch doorspelen.",
      rules: [
        {
          id: "offensive_drawing",
          heading: "Aanstootgevende tekeningen",
          body: [
            "Teken het woord. Het canvas is niet de plek voor seksuele inhoud, bloed, haatsymbolen of een uithaal naar iemand in de kamer.",
            "Slecht kunnen tekenen is niet tegen de regels — niemand beoordeelt je cirkels. Dit gaat over expres iets anders tekenen.",
          ],
          examples: [
            "Seksuele of bloederige tekeningen",
            "Haatsymbolen, hoe grof getekend ook",
            "In plaats van het woord een belediging over iemand tekenen",
          ],
        },
        {
          id: "inappropriate_name",
          heading: "Ongepaste namen",
          body: [
            "Iedereen met wie je speelt ziet je naam, dus laat beledigingen, seksuele termen en namen die bedoeld zijn om iemand te jennen achterwege.",
            "En doe je ook niet voor als een andere speler of als moderator.",
          ],
          examples: [
            "Een naam met een belediging of een seksuele term erin",
            "Een naam die op die van iemand anders moet lijken",
            "Een naam die een steek onder water is naar één bepaalde persoon",
          ],
        },
        {
          id: "inappropriate_avatar",
          heading: "Ongepaste afbeeldingen",
          body: [
            "Hetzelfde geldt voor je accountafbeelding — die staat op je profiel en naast je naam overal waar je speelt.",
            "Een moderator kan een afbeelding weghalen zonder dat er verder iets met je account gebeurt, en de eerste keer kun je meteen een nieuwe plaatsen.",
          ],
          examples: [
            "Seksuele of grafische afbeeldingen",
            "Haatsymbolen of extremistische beelden",
            "Een foto van iemand die er niet mee ingestemd heeft dat die er staat",
          ],
        },
      ],
    },
    {
      id: "fair-play",
      heading: "Eerlijk spelen",
      blurb: "Het spel werkt alleen als er echt geraden wordt.",
      rules: [
        {
          id: "cheating",
          heading: "Valsspelen",
          body: [
            "Geef het woord aan niemand die het moet raden — niet in de chat, niet in de tekening, en niet ergens buiten het spel. En laat geen programma voor je spelen.",
            "Het woord op het canvas schrijven telt als het zeggen.",
          ],
          examples: [
            "Het woord opschrijven of spellen terwijl je het tekent",
            "Een vriend het woord doorgeven via een gesprek of een andere app",
            "Een tweede account gebruiken om jezelf antwoorden door te spelen",
          ],
        },
      ],
    },
  ],
  enforcement: {
    heading: "Wat er gebeurt als je er een overtreedt",
    body: [
      "Meldingen gaan naar een moderator, die ziet wat er echt gezegd of getekend is. De meeste eindigen zonder dat er iets gebeurt — mensen melden dingen die in orde blijken te zijn, en daar is melden precies voor.",
      "Als er iets mis was, kan een moderator je een waarschuwing geven, een afbeelding weghalen of het account schorsen. Een waarschuwing beperkt niets, maar nog een melding daarna kan tot een schorsing leiden. Een schorsing kan een dag, een week, een maand of geen einddatum hebben, en je hoort welke het is.",
      "Wat er ook gebeurt, je hoort waar het over ging en je krijgt je eigen woorden, of je eigen tekening, erbij te zien. Niemand probeert je te betrappen.",
    ],
  },
};
