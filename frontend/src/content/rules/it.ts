import type { RulesDocument } from "./types.ts";

/** The rules, in Italian.

A translation of [`en.ts`](./en.ts), which stays the reference: when the
English changes, this is stale until it follows.

Machine-drafted and **not yet read by a native speaker**. The rules are the
one text where a bad translation has consequences - somebody reads them after
being told they broke one, and a mistranslated prohibition is a decision they
cannot check - so this wants a human pass before launch (R-I18N-07).

The ids are not translated and never will be: they are anchors, and a notice
linking to `#spam` has to survive the page being read in Italian
(R-RULES-03). */
export const RULES_IT: RulesDocument = {
  locale: "it",
  title: "Regole",
  introHeading: "Introduzione",
  intro: [
    "Sketchy è un gioco che si fa con sconosciuti, e quasi tutto funziona perché la maggior parte delle persone si comporta bene senza che glielo si chieda. Queste regole sono per le volte in cui non è così — e perché, se un moderatore interviene, non sia una sorpresa.",
    "Quasi tutto ciò che va storto qui non è cattiveria. Una brutta giornata capita a chiunque, una battuta può cadere male, e non sai mai davvero con cosa abbia a che fare chi sta dall’altra parte di un disegno. Parti da lì, e la maggior parte delle cose smette di meritare una segnalazione.",
    "Niente di tutto questo sta qui come un bastone. Sta qui perché le stanze restino un posto dove ci si presenta, si disegna qualcosa di ridicolo e ci si rilassa. Quando invece dobbiamo decidere qualcosa, guardiamo a cosa è successo e non a chi sei: un moderatore legge quello che è stato davvero detto o disegnato, nell’ordine in cui è successo, e decide da lì.",
  ],
  sections: [
    {
      id: "conduct",
      heading: "Come tratti gli altri",
      blurb: "Stai giocando con persone che non possono semplicemente andarsene senza lasciare la partita. Queste due regole riguardano questo.",
      rules: [
        {
          id: "harassment",
          heading: "Molestie",
          body: [
            "Non prendertela con gli altri giocatori. Niente insulti, minacce o umiliazioni — e questo comprende offese e odio di qualsiasi tipo, molestie sessuali e seguire qualcuno di stanza in stanza per continuare.",
            "Le battute sono metà del divertimento e non c’è niente di male — finché ci stanno davvero tutti e non si esagera. Il limite è dove smette di essere condiviso: quando qualcuno ne ha abbastanza, o quando è puntato su una persona che non sta ridendo. Se non riesci a capirlo, lascia stare. Non ti costa niente.",
            "E perdere male un round non è un motivo per prendersela con chi ha vinto, così come non lo è che qualcuno disegni qualcosa che non ti piace.",
          ],
          examples: [
            "Accanirsi sul disegno di qualcuno finché in realtà si parla della persona",
            "Prendersela con l’origine, la religione, il sesso, il genere, la disabilità o la nazionalità di qualcuno",
            "Seguire qualcuno in una stanza per continuare un litigio",
          ],
        },
        {
          id: "spam",
          heading: "Spam",
          body: [
            "Non inondare la chat, non ripeterti per coprire tutti gli altri e non usare il gioco per fare pubblicità.",
            "Provare a indovinare non è spam, per quanto assurdi diventino i tentativi — indovinare in fretta è tutto il senso della cosa.",
          ],
          examples: [
            "Ripetere un messaggio finché nessuno riesce a seguire il round",
            "Pubblicare link o inviti verso altrove",
            "Incollare lo stesso muro di testo in una stanza dopo l’altra",
          ],
        },
      ],
    },
    {
      id: "content",
      heading: "Quello che tutti gli altri devono guardare",
      blurb: "Il tuo disegno, il tuo nome e la tua immagine finiscono davanti a persone che non li hanno scelti. Dalla tela nessuno può distogliere lo sguardo e continuare a giocare.",
      rules: [
        {
          id: "offensive_drawing",
          heading: "Disegni offensivi",
          body: [
            "Disegna la parola. La tela non è il posto per contenuti sessuali, sangue, simboli d’odio o per prendersela con qualcuno nella stanza.",
            "Disegnare male non è contro le regole — nessuno sta giudicando i tuoi cerchi. Qui si parla di disegnare apposta altro.",
          ],
          examples: [
            "Disegni sessuali o cruenti",
            "Simboli d’odio, per quanto grossolano sia il disegno",
            "Disegnare un insulto su qualcuno invece della parola",
          ],
        },
        {
          id: "inappropriate_name",
          heading: "Nomi inappropriati",
          body: [
            "Tutti quelli con cui giochi vedono il tuo nome, quindi tieni fuori offese, termini sessuali e nomi costruiti per punzecchiare qualcuno.",
            "E non spacciarti per un altro giocatore o per un moderatore.",
          ],
          examples: [
            "Un nome con dentro un’offesa o un termine sessuale",
            "Un nome fatto per somigliare a quello di qualcun altro",
            "Un nome che è una frecciata a una persona precisa",
          ],
        },
        {
          id: "inappropriate_avatar",
          heading: "Immagini inappropriate",
          body: [
            "Lo stesso vale per l’immagine del tuo account: sta sul tuo profilo e accanto al tuo nome ovunque tu giochi.",
            "Un moderatore può togliere un’immagine senza che al tuo account succeda altro, e la prima volta puoi caricarne subito una nuova.",
          ],
          examples: [
            "Immagini sessuali o esplicite",
            "Simboli d’odio o immagini estremiste",
            "La foto di qualcuno che non ha acconsentito a starci",
          ],
        },
      ],
    },
    {
      id: "fair-play",
      heading: "Giocare lealmente",
      blurb: "Il gioco funziona solo se i tentativi sono veri.",
      rules: [
        {
          id: "cheating",
          heading: "Imbrogli",
          body: [
            "Non passare la parola a chi deve indovinarla — né in chat, né nel disegno, né fuori dal gioco. E non far giocare un programma al posto tuo.",
            "Scrivere la parola sulla tela vale come dirla.",
          ],
          examples: [
            "Scrivere o sillabare la parola mentre la disegni",
            "Dire la parola a un amico per telefono o con un’altra app",
            "Usare un secondo account per passarti le risposte",
          ],
        },
      ],
    },
  ],
  enforcement: {
    heading: "Cosa succede se ne infrangi una",
    body: [
      "Le segnalazioni vanno a un moderatore, che vede quello che è stato davvero detto o disegnato. La maggior parte finisce senza che succeda niente: la gente segnala cose che si rivelano a posto, ed è esattamente a questo che serve segnalare.",
      "Se qualcosa non andava, un moderatore può darti un avvertimento, togliere un’immagine o sospendere l’account. Un avvertimento non limita niente, ma un’altra segnalazione dopo può portare a una sospensione. Una sospensione può durare un giorno, una settimana, un mese, o non avere una fine, e ti verrà detto quale.",
      "Qualunque cosa succeda, ti verrà detto di cosa si trattava e ti verranno mostrate le tue parole, o il tuo disegno, dietro la decisione. Nessuno sta cercando di incastrarti.",
    ],
  },
};
