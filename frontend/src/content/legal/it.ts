import type { LegalDocuments } from "./types.ts";

/** Informativa sulla privacy e termini d'uso, in italiano (#1417).
A translation of `en.ts`, machine-drafted and awaiting a native reader. */
export const LEGAL_IT: LegalDocuments = {
  locale: "it",
  privacy: {
    title: "Informativa sulla privacy",
    intro: [
      "Questa informativa spiega che cosa Sketchy conserva su di te, perché, per " +
        "quanto tempo e che cosa puoi fare al riguardo. Sketchy è gratuito: non " +
        "mostra pubblicità, e nulla su di te viene venduto o usato per venderti " +
        "qualcosa.",
    ],
    sections: [
      {
        id: "operator",
        heading: "Chi è responsabile",
        body: [
          "Sketchy è offerto dal suo gestore, con sede in Svizzera, che decide " +
            "che cosa viene conservato e perché. Puoi scrivere al gestore a " +
            "{contact}.",
          "A tutto ciò che è descritto qui si applica la legge svizzera sulla " +
            "protezione dei dati e, quando giochi dall'Unione europea, anche il " +
            "Regolamento generale sulla protezione dei dati dell'UE.",
        ],
      },
      {
        id: "data",
        heading: "Che cosa viene conservato",
        body: ["Solo ciò che serve al gioco per funzionare, essere equo e restare sicuro:"],
        items: [
          "Il nome con cui giochi, e il nome utente di un account.",
          "Se crei un account: il tuo indirizzo email, la tua password – " +
            "conservata solo come hash unidirezionale, da cui non si può " +
            "risalire a essa – e le passkey o l'autenticazione a due fattori che " +
            "configuri.",
          "Le tue impostazioni e il tuo profilo: le tue lingue e preferenze, " +
            "un'immagine del profilo se ne carichi una, i tuoi amici, i " +
            "giocatori che blocchi, le impostazioni di stanza salvate e le liste " +
            "a cui metti la stella.",
          "Le tue partite: le stanze in cui hai giocato, le tue risposte, punti " +
            "e risultati, le tue reazioni e i disegni che hai fatto.",
          "La chat, nelle stanze e nella lobby.",
          "Le liste di parole che scrivi, e se le hai pubblicate.",
          "Le segnalazioni che invii e quelle che ti riguardano, con i messaggi " +
            "e i disegni a cui si riferiscono, e ogni ammonimento o sospensione " +
            "del tuo account.",
          "Un registro di sicurezza e moderazione delle azioni delicate – per " +
            "esempio i cambi di password e di email, il blocco di qualcuno, il " +
            "cambio della tua immagine e le decisioni di moderazione.",
          "I tuoi accessi: una descrizione approssimativa di ogni dispositivo " +
            "(ad esempio «Firefox su Windows»), quando è stato usato l'ultima " +
            "volta e un hash con chiave segreta dell'indirizzo di rete da cui " +
            "proveniva. Lo stesso tipo di hash è conservato nel registro qui " +
            "sopra e limita quante volte si può fare qualcosa da uno stesso " +
            "indirizzo. Sketchy non conserva mai l'indirizzo stesso, anche se i " +
            "fornitori che trasportano il suo traffico lo vedono.",
          "Quando entri e esci dalle stanze, per poter rintracciare i problemi.",
          "Le segnalazioni di bug che invii, con uno screenshot se ne alleghi " +
            "uno.",
          "Informazioni tecniche sulla tua connessione e sugli errori del tuo " +
            "browser, per trovare e risolvere i problemi. Non contengono nessuno " +
            "dei tuoi messaggi né dei tuoi disegni.",
        ],
      },
      {
        id: "purposes",
        heading: "Perché viene conservato",
        body: [
          "Per far funzionare il gioco a cui vuoi giocare: stanze, turni, " +
            "punti, la tua cronologia e il tuo account. È l'accordo tra te e il " +
            "gestore, come descritto nei termini d'uso. Il tuo indirizzo email " +
            "serve solo al tuo account: per confermarlo, per reimpostare la " +
            "password e per avvisarti di modifiche e decisioni che lo " +
            "riguardano.",
          "Per mantenere il gioco equo e sicuro: moderare le segnalazioni, " +
            "fermare imbrogli, spam e abusi, e proteggere gli account. È " +
            "l'interesse legittimo del gestore e di tutti quelli che giocano.",
          "Per trovare e risolvere i problemi, per lo stesso motivo.",
          "Per rispondere alle autorità quando la legge obbliga il gestore a " +
            "farlo.",
          "Nulla su di te viene usato per la pubblicità, venduto o usato per " +
            "costruire un tuo profilo, e nessuna decisione con effetti giuridici " +
            "o altrettanto significativi per te viene presa solo da una " +
            "macchina.",
        ],
      },
      {
        id: "visibility",
        heading: "Che cosa vedono gli altri giocatori",
        body: [
          "Chi è in una stanza con te vede il tuo nome, i tuoi messaggi, i tuoi " +
            "disegni e il tuo punteggio.",
          "I disegni fatti in una stanza pubblica compaiono nella Galleria, dove " +
            "chiunque può vederli, con il nome con cui sono stati disegnati: " +
            "giocare in una stanza pubblica è giocare in pubblico, secondo i " +
            "termini d'uso. I disegni di una stanza privata li vede solo chi " +
            "c'era. Eliminare il tuo account cancella tutti i tuoi disegni, " +
            "tranne una copia allegata a una segnalazione, che resta con essa; " +
            "per farne rimuovere uno solo, scrivi a {contact}.",
          "Una lista di parole che pubblichi può essere letta da tutti, con il " +
            "tuo nome come autore. Il tuo profilo mostra ciò che scegli di " +
            "mostrare.",
        ],
      },
      {
        id: "recipients",
        heading: "Chi altro li tratta",
        body: [
          "Nessuno riceve i tuoi dati per usarli per scopi propri. Il gestore " +
            "si affida ad alcuni fornitori per far funzionare Sketchy – hosting, " +
            "distribuzione in rete ed email – che li trattano solo secondo le " +
            "istruzioni del gestore. Quando uno di loro lo fa fuori dalla " +
            "Svizzera e dall'UE, è con garanzie riconosciute dalla legge, come le " +
            "clausole contrattuali tipo della Commissione europea; scrivi a " +
            "{contact} per sapere quali paesi e quali garanzie.",
          "I moderatori e gli amministratori nominati dal gestore vedono le " +
            "segnalazioni su cui decidono e ciò a cui si riferiscono. Gli " +
            "amministratori leggono anche le segnalazioni di bug e possono " +
            "consultare un account e la sua attività recente quando qualcosa va " +
            "storto.",
          "I dati vengono forniti alle autorità solo quando la legge lo " +
            "richiede.",
        ],
      },
      {
        id: "retention",
        heading: "Per quanto tempo viene conservato",
        body: [],
        items: [
          "Chat: 30 giorni, tranne le righe citate in una segnalazione, che " +
            "restano con essa.",
          "Le segnalazioni e ciò che citano, gli ammonimenti, le sospensioni, il " +
            "registro di sicurezza e moderazione e le segnalazioni di bug: " +
            "conservati come traccia duratura della moderazione e della " +
            "sicurezza del servizio, anche dopo che hai eliminato il tuo " +
            "account. Le voci del registro da quel momento non ti nominano più.",
          "Screenshot delle segnalazioni di bug: finché la segnalazione non " +
            "viene gestita, e mai più di 90 giorni.",
          "Ospiti: eliminati dopo 30 giorni senza una partita conclusa, oppure " +
            "dopo 365 giorni senza giocare una volta che ne hanno una.",
          "Account: finché non li elimini. Amicizie, blocchi, liste di parole, " +
            "impostazioni di stanza salvate e stelle: finché non li rimuovi o " +
            "elimini il tuo account.",
          "Accessi: finché non scadono, e 30 giorni dopo.",
          "Entrate e uscite dalle stanze: 30 giorni.",
          "Email inviate a te: 30 giorni.",
          "Esportazioni di dati che richiedi: 7 giorni.",
          "Le partite concluse – punti, disegni, reazioni – fanno parte della " +
            "cronologia di tutti quelli che hanno giocato, quindi vengono " +
            "conservate. Se elimini il tuo account, i tuoi disegni vengono " +
            "cancellati e il tuo posto in quelle partite viene reso anonimo, così " +
            "la cronologia degli altri resta intatta senza di te.",
        ],
      },
      {
        id: "rights",
        heading: "I tuoi diritti",
        body: [
          "Nelle Impostazioni puoi scaricare una copia dei tuoi dati, correggere " +
            "il tuo nome, la tua email e il tuo profilo, ed eliminare il tuo " +
            "account o la tua identità di ospite, quando vuoi.",
          "Hai anche il diritto di ottenere tutto ciò che viene conservato su di " +
            "te e come viene usato – compreso ciò che il download non contiene, " +
            "come le segnalazioni che ti riguardano –, di farlo correggere o " +
            "cancellare, di riceverlo in un formato che puoi portare altrove, di " +
            "opporti al suo uso per gli interessi legittimi del gestore e di " +
            "farne limitare l'uso. Scrivi a {contact} per tutto ciò che le " +
            "Impostazioni non permettono.",
          "Se ritieni che i tuoi dati siano trattati male, puoi presentare " +
            "reclamo a un'autorità di protezione dei dati: in Svizzera " +
            "l'Incaricato federale della protezione dei dati e della trasparenza " +
            "(IFPDT), e nell'UE l'autorità del paese in cui vivi.",
        ],
      },
      {
        id: "cookies",
        heading: "Cookie e memoria",
        body: [
          "Sketchy usa un solo cookie, che ti mantiene connesso. È necessario " +
            "per far funzionare il gioco, quindi non ti viene chiesto di " +
            "accettarlo. Le tue impostazioni vengono anche ricordate nella " +
            "memoria del tuo browser.",
          "Non ci sono cookie pubblicitari o di analisi, né script di terzi.",
        ],
      },
      {
        id: "age",
        heading: "Età",
        body: [
          "Sketchy è per persone dai {age} anni in su. Se sei un genitore e " +
            "pensi che tuo figlio o tua figlia di meno di {age} anni stia " +
            "giocando, scrivi a {contact} e i suoi dati verranno cancellati.",
        ],
      },
      {
        id: "changes",
        heading: "Modifiche a questa informativa",
        body: [
          "Se questa informativa cambia, la nuova versione viene pubblicata " +
            "qui. Una modifica che incide su come vengono usati i tuoi dati non " +
            "si applicherà a ciò che è stato conservato in precedenza senza " +
            "avvisarti prima.",
        ],
      },
    ],
  },
  terms: {
    title: "Termini d'uso",
    intro: [
      "Questi termini sono l'accordo tra te e il gestore di Sketchy. Giocando " +
        "li accetti; se non li accetti, non usare Sketchy.",
    ],
    sections: [
      {
        id: "agreement",
        heading: "Sketchy è in beta",
        body: [
          "Sketchy è gratuito ed è ancora in costruzione: le funzioni cambiano, " +
            "qualcosa si rompe e, in rari casi, qualcosa può andare perso. " +
            "Grazie di giocarci comunque.",
        ],
      },
      {
        id: "age",
        heading: "Chi può giocare",
        body: ["Devi avere almeno {age} anni. Giocando confermi di averli."],
      },
      {
        id: "accounts",
        heading: "Il tuo nome e il tuo account",
        body: [
          "Scegli un nome che non finga di essere qualcun altro e che non violi " +
            "le regole. Tieni per te la password e l'accesso: sei responsabile " +
            "di ciò che viene fatto con il tuo account.",
          "Un ospite vive in un browser. Cancellare i dati di quel browser fa " +
            "perdere l'ospite, a meno che tu non l'abbia trasformato in un " +
            "account.",
        ],
      },
      {
        id: "fair-play",
        heading: "Giocare lealmente",
        body: [
          "Segui le regole. Non imbrogliare – nessuna risposta automatica, " +
            "nessun suggerimento della risposta agli altri, nessuna partita " +
            "giocata come più persone per avere un vantaggio –, non cercare di " +
            "rompere o sovraccaricare Sketchy e non usarlo per nulla di " +
            "illecito.",
        ],
      },
      {
        id: "content",
        heading: "Ciò che disegni e scrivi",
        body: [
          "Ciò che disegni, scrivi e pubblichi resta tuo. Perché il gioco " +
            "funzioni, consenti al gestore di conservarlo, mostrarlo e copiarlo " +
            "all'interno di Sketchy – nella tua stanza, nella Galleria per le " +
            "stanze pubbliche, nelle liste di parole che pubblichi e nelle copie " +
            "che altri ne fanno – gratuitamente, in tutto il mondo e finché " +
            "Sketchy lo conserva.",
          "Disegna e scrivi solo ciò che hai il diritto di condividere, e nulla " +
            "che le regole vietano.",
        ],
      },
      {
        id: "moderation",
        heading: "Moderazione",
        body: [
          "I moderatori possono nascondere contenuti, ammonire giocatori e " +
            "sospendere gli account che violano questi termini o le regole. " +
            "Quando un moderatore registra a quale regola si riferisce una " +
            "decisione, ti viene detto. I dati di un account sospeso possono " +
            "ancora essere scaricati o eliminati, da un dispositivo che aveva " +
            "effettuato l'accesso quando è iniziata la sospensione oppure " +
            "scrivendo a {contact}.",
        ],
      },
      {
        id: "availability",
        heading: "Nessuna garanzia",
        body: [
          "Sketchy è fornito così com'è, senza alcuna garanzia che sia sempre " +
            "disponibile, che funzioni senza errori o che conservi per sempre " +
            "ciò che hai fatto. Il gestore può modificarlo, sospenderlo o " +
            "chiuderlo.",
        ],
      },
      {
        id: "liability",
        heading: "Responsabilità",
        body: [
          "Nei limiti consentiti dalla legge, il gestore non risponde di danni " +
            "indiretti né della perdita di contenuti o dati. Nulla qui limita una " +
            "responsabilità che la legge non consente di limitare, come in caso " +
            "di dolo o colpa grave.",
        ],
      },
      {
        id: "leaving",
        heading: "Andarsene",
        body: [
          "Puoi smettere in qualsiasi momento ed eliminare il tuo account nelle " +
            "Impostazioni. Il gestore può revocarti l'accesso se violi questi " +
            "termini o le regole, oppure chiudere del tutto Sketchy.",
        ],
      },
      {
        id: "law",
        heading: "Quale legge si applica",
        body: [
          "Questi termini sono regolati dal diritto svizzero, che non ti toglie " +
            "la tutela che, in quanto consumatore, ti riconosce la legge " +
            "imperativa del paese in cui vivi. Le controversie spettano ai " +
            "tribunali della sede del gestore in Svizzera, a meno che quella " +
            "legge non ti dia il diritto di agire in giudizio nel tuo paese.",
        ],
      },
      {
        id: "changes",
        heading: "Modifiche a questi termini",
        body: [
          "Se questi termini cambiano su un punto importante, ti verrà detto " +
            "prima che la modifica si applichi, e continuare a giocare dopo " +
            "significa accettarla. Le domande vanno a {contact}.",
        ],
      },
    ],
  },
};
