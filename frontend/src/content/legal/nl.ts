import type { LegalDocuments } from "./types.ts";

/** Privacyverklaring en gebruiksvoorwaarden, in het Nederlands (#1417).
A translation of `en.ts`, machine-drafted and awaiting a native reader.
"Exploitant" for the operator: "beheerder" is the interface's administrator. */
export const LEGAL_NL: LegalDocuments = {
  locale: "nl",
  privacy: {
    title: "Privacyverklaring",
    intro: [
      "Deze verklaring legt uit wat Sketchy over je bewaart, waarom, hoe lang, " +
        "en wat je eraan kunt doen. Sketchy is gratis: het toont geen reclame, " +
        "en niets over jou wordt verkocht of gebruikt om je iets te verkopen.",
    ],
    sections: [
      {
        id: "operator",
        heading: "Wie verantwoordelijk is",
        body: [
          "Sketchy wordt gerund door de exploitant, gevestigd in Zwitserland, " +
            "die beslist wat er wordt bewaard en waarom. Je kunt de exploitant " +
            "schrijven op {contact}.",
          "Op alles wat hier staat is de Zwitserse wet op de " +
            "gegevensbescherming van toepassing, en wanneer je vanuit de " +
            "Europese Unie speelt ook de Algemene Verordening " +
            "Gegevensbescherming van de EU.",
        ],
      },
      {
        id: "data",
        heading: "Wat er wordt bewaard",
        body: ["Alleen wat het spel nodig heeft om te werken, eerlijk te zijn en veilig te blijven:"],
        items: [
          "De naam waaronder je speelt, en de gebruikersnaam van een account.",
          "Als je een account maakt: je e-mailadres, je wachtwoord – alleen " +
            "bewaard als eenrichtingshash waaruit het niet terug te halen is – " +
            "en de passkeys of tweestapsverificatie die je instelt.",
          "Je instellingen en profiel: je talen en voorkeuren, een " +
            "profielfoto als je er een uploadt, je vrienden, de spelers die je " +
            "blokkeert, je opgeslagen kamerinstellingen en de lijsten die je " +
            "een ster geeft.",
          "Je spellen: de kamers waarin je speelde, je gokken, punten en " +
            "uitslagen, je reacties, de tekeningen die je maakte en de " +
            "tekeningen die je in de Galerij deelde.",
          "De chat, in kamers en in de lobby.",
          "De berichten in je inbox, over je account, je tekeningen en je " +
            "vriendschappen.",
          "De woordenlijsten die je schrijft, en of je ze hebt gepubliceerd.",
          "Meldingen die je verstuurt en meldingen over jou, met de berichten " +
            "en tekeningen waarnaar ze verwijzen, en elke waarschuwing of " +
            "schorsing van je account.",
          "Een beveiligings- en moderatielogboek van gevoelige handelingen – " +
            "zoals wijzigingen van wachtwoord en e-mailadres, iemand blokkeren, " +
            "je afbeelding wijzigen en beslissingen van de moderatie.",
          "Je aanmeldingen: een globale omschrijving van elk apparaat " +
            "(bijvoorbeeld 'Firefox op Windows'), wanneer het voor het laatst " +
            "werd gebruikt, en een hash met geheime sleutel van het netwerkadres " +
            "waar het vandaan kwam. Hetzelfde soort hash wordt bij het logboek " +
            "hierboven bewaard en beperkt hoe vaak iets vanaf één adres kan " +
            "worden gedaan. Sketchy bewaart nooit het adres zelf, al zien de " +
            "leveranciers die het verkeer bezorgen het wel.",
          "Wanneer je kamers binnenkomt en verlaat, zodat problemen te " +
            "herleiden zijn.",
          "Bugmeldingen die je stuurt, met een screenshot als je er een " +
            "toevoegt.",
          "Technische gegevens over je verbinding en fouten in je browser, zodat " +
            "problemen gevonden en opgelost kunnen worden. Ze bevatten geen van " +
            "je berichten of tekeningen.",
        ],
      },
      {
        id: "purposes",
        heading: "Waarom het wordt bewaard",
        body: [
          "Om het spel te laten draaien dat je wilt spelen: kamers, beurten, " +
            "punten, je geschiedenis en je account. Dat is de afspraak tussen " +
            "jou en de exploitant, zoals de gebruiksvoorwaarden die beschrijven. " +
            "Je e-mailadres wordt alleen voor je account gebruikt: om het te " +
            "bevestigen, om je wachtwoord te herstellen en om je te laten weten " +
            "wat er aan je account verandert en wat erover wordt besloten.",
          "Om het spel eerlijk en veilig te houden: meldingen modereren, " +
            "valsspelen, spam en misbruik tegengaan, en accounts beschermen. Dat " +
            "is het gerechtvaardigde belang van de exploitant en van iedereen " +
            "die speelt.",
          "Om problemen te vinden en op te lossen, om dezelfde reden.",
          "Om autoriteiten te antwoorden waar de wet de exploitant daartoe " +
            "verplicht.",
          "Niets over jou wordt gebruikt voor reclame, verkocht of gebruikt om " +
            "een profiel van je te maken, en geen beslissing met " +
            "rechtsgevolgen of vergelijkbare aanmerkelijke gevolgen voor jou " +
            "wordt alleen door een machine genomen.",
        ],
      },
      {
        id: "visibility",
        heading: "Wat andere spelers zien",
        body: [
          "Wie met je in een kamer zit, ziet je naam, je berichten, je " +
            "tekeningen en je score.",
          "Een tekening verschijnt pas in de Galerij, waar iedereen hem kan " +
            "zien, als iemand hem deelt, met de naam waaronder hij is getekend en " +
            "de naam van wie hem als eerste deelde. Je eigen tekeningen kun je " +
            "vanuit elke kamer delen. In een openbare kamer kunnen de anderen in " +
            "de kamer ook die van jou delen, zonder het eerst te vragen: wie in " +
            "een openbare kamer speelt, speelt in het openbaar, volgens de " +
            "gebruiksvoorwaarden. Je kunt elke tekening van jou uit de Galerij " +
            "halen, en dan kan niemand hem opnieuw delen, behalve jij. Tekeningen " +
            "uit een privékamer zien alleen de mensen die erin zaten, tenzij je " +
            "je eigen tekeningen deelt.",
          "Als je je account verwijdert, worden al je tekeningen gewist, " +
            "behalve een kopie die bij een melding hoort en daarbij blijft; wil " +
            "je er één laten wissen, schrijf dan naar {contact}.",
          "Een woordenlijst die je publiceert, kan iedereen lezen, met jouw naam " +
            "als auteur. Je profiel toont wat jij ervoor kiest te tonen.",
        ],
      },
      {
        id: "recipients",
        heading: "Wie er verder mee omgaat",
        body: [
          "Niemand krijgt je gegevens om ze voor eigen doeleinden te gebruiken. " +
            "De exploitant werkt met een paar leveranciers om Sketchy te laten " +
            "draaien – hosting, netwerklevering en e-mail – die ze alleen volgens " +
            "de instructies van de exploitant verwerken. Als een van hen dat " +
            "buiten Zwitserland en de EU doet, gebeurt dat met waarborgen die de " +
            "wet erkent, zoals de standaardcontractbepalingen van de Europese " +
            "Commissie; schrijf naar {contact} om te vragen welke landen en welke " +
            "waarborgen.",
          "Door de exploitant aangestelde moderators en beheerders zien de " +
            "meldingen waarover ze beslissen en waar die naar verwijzen. " +
            "Beheerders lezen ook bugmeldingen en kunnen een account en de " +
            "recente activiteit ervan opzoeken als er iets misgaat.",
          "Gegevens worden alleen aan autoriteiten gegeven als de wet dat " +
            "vereist.",
        ],
      },
      {
        id: "retention",
        heading: "Hoe lang het wordt bewaard",
        body: [],
        items: [
          "Chat: 30 dagen, behalve regels die in een melding worden " +
            "aangehaald; die blijven bij de melding.",
          "Meldingen en waar ze naar verwijzen, schorsingen, het beveiligings- " +
            "en moderatielogboek en bugmeldingen: blijvend bewaard als " +
            "vastlegging van de moderatie en de beveiliging van de dienst, ook " +
            "nadat je je account hebt verwijderd. Logboekregels noemen je daarna " +
            "niet meer.",
          "Waarschuwingen: 12 maanden, en verwijderd met je account.",
          "Berichten in je inbox: 90 dagen, gelezen of niet, en verwijderd met " +
            "je account.",
          "Screenshots bij bugmeldingen: tot de melding is afgehandeld, en " +
            "nooit langer dan 90 dagen.",
          "Gasten: verwijderd na 30 dagen zonder afgerond spel, of na 365 dagen " +
            "zonder te spelen zodra ze er een hebben.",
          "Accounts: tot je ze verwijdert. Vriendschappen, blokkeringen, " +
            "woordenlijsten, opgeslagen kamerinstellingen en sterren: tot je ze " +
            "weghaalt of je account verwijdert.",
          "Aanmeldingen: tot ze verlopen, en 30 dagen daarna – behalve die van een geschorst account, die blijven zolang de schorsing duurt, omdat ze de enige manier zijn om de gegevens te downloaden of te verwijderen.",
          "Binnenkomen en verlaten van kamers: 30 dagen.",
          "E-mails aan jou: 30 dagen.",
          "Gegevensexports die je aanvraagt: 7 dagen.",
          "Afgeronde spellen – punten, tekeningen, reacties – horen bij de " +
            "geschiedenis van iedereen die meespeelde, dus die blijven bewaard. " +
            "Als je je account verwijdert, worden je tekeningen gewist en wordt " +
            "je plaats in die spellen geanonimiseerd, zodat de geschiedenis van " +
            "de anderen intact blijft zonder jou.",
        ],
      },
      {
        id: "rights",
        heading: "Je rechten",
        body: [
          "In Instellingen kun je een kopie van je gegevens downloaden, je " +
            "naam, e-mailadres en profiel corrigeren, en je account of je " +
            "gastidentiteit verwijderen, wanneer je maar wilt.",
          "Je hebt ook het recht om alles op te vragen wat er over je wordt " +
            "bewaard en hoe het wordt gebruikt – ook wat de download niet bevat, " +
            "zoals meldingen over jou –, om het te laten corrigeren of wissen, " +
            "om het te krijgen in een formaat dat je elders kunt gebruiken, om " +
            "bezwaar te maken tegen het gebruik voor de gerechtvaardigde belangen " +
            "van de exploitant, en om het gebruik te laten beperken. Schrijf naar " +
            "{contact} voor alles wat Instellingen niet kan.",
          "Als je vindt dat er verkeerd met je gegevens wordt omgegaan, kun je " +
            "een klacht indienen bij een toezichthouder: in Zwitserland de " +
            "federale toezichthouder voor gegevensbescherming (FDPIC/EDÖB), en " +
            "in de EU de toezichthouder van het land waar je woont.",
        ],
      },
      {
        id: "cookies",
        heading: "Cookies en opslag",
        body: [
          "Sketchy plaatst één enkele cookie, die je ingelogd houdt. Die is " +
            "nodig om het spel te laten werken, dus word je niet gevraagd ermee " +
            "in te stemmen. Je instellingen worden ook onthouden in de opslag " +
            "van je eigen browser.",
          "Er zijn geen reclame- of analysecookies, en geen scripts van anderen.",
        ],
      },
      {
        id: "age",
        heading: "Leeftijd",
        body: [
          "Sketchy is voor mensen van {age} jaar en ouder. Ben je ouder of " +
            "verzorger en denk je dat je kind onder de {age} speelt, schrijf dan " +
            "naar {contact} en de gegevens worden verwijderd.",
        ],
      },
      {
        id: "changes",
        heading: "Wijzigingen in deze verklaring",
        body: [
          "Als deze verklaring verandert, wordt de nieuwe versie hier " +
            "gepubliceerd. Een wijziging die van belang is voor hoe je gegevens " +
            "worden gebruikt, geldt niet voor wat eerder is bewaard zonder dat je " +
            "het eerst te horen krijgt.",
        ],
      },
    ],
  },
  terms: {
    title: "Gebruiksvoorwaarden",
    intro: [
      "Deze voorwaarden zijn de afspraak tussen jou en de exploitant van " +
        "Sketchy. Door te spelen accepteer je ze; als je dat niet wilt, gebruik " +
        "Sketchy dan niet.",
    ],
    sections: [
      {
        id: "agreement",
        heading: "Sketchy is in bèta",
        body: [
          "Sketchy is gratis en wordt nog gebouwd: functies veranderen, dingen " +
            "gaan stuk, en in zeldzame gevallen kan er iets verloren gaan. " +
            "Bedankt dat je het toch speelt.",
        ],
      },
      {
        id: "age",
        heading: "Wie mag spelen",
        body: ["Je moet minstens {age} jaar oud zijn. Door te spelen bevestig je dat."],
      },
      {
        id: "accounts",
        heading: "Je naam en je account",
        body: [
          "Kies een naam die zich niet voordoet als iemand anders en de regels " +
            "niet breekt. Houd je wachtwoord en aanmelding voor jezelf: je bent " +
            "verantwoordelijk voor wat er met je account gebeurt.",
          "Een gast leeft in één browser. Wis je de gegevens van die browser, " +
            "dan ben je de gast kwijt, tenzij je er een account van hebt " +
            "gemaakt.",
        ],
      },
      {
        id: "fair-play",
        heading: "Eerlijk spelen",
        body: [
          "Volg de regels. Speel niet vals – geen automatische gokken, geen " +
            "antwoord voorzeggen, niet als meerdere personen spelen voor een " +
            "voordeel –, probeer Sketchy niet kapot te maken of te overbelasten, " +
            "en gebruik het niet voor iets wat onwettig is.",
        ],
      },
      {
        id: "content",
        heading: "Wat je tekent en schrijft",
        body: [
          "Wat je tekent, schrijft en publiceert, blijft van jou. Zodat het " +
            "spel kan werken, geef je de exploitant toestemming het binnen " +
            "Sketchy te bewaren, te tonen en te kopiëren – in je kamer, in de " +
            "Galerij zodra een tekening is gedeeld, in woordenlijsten die je " +
            "publiceert en " +
            "in kopieën die anderen ervan maken –, kosteloos, wereldwijd en " +
            "zolang Sketchy het bewaart.",
          "Teken en schrijf alleen wat je mag delen, en niets wat de regels " +
            "verbieden.",
        ],
      },
      {
        id: "moderation",
        heading: "Moderatie",
        body: [
          "Moderators kunnen inhoud verbergen, spelers waarschuwen en accounts " +
            "schorsen die deze voorwaarden of de regels overtreden. Als een " +
            "moderator vastlegt over welke regel een beslissing gaat, hoor je " +
            "dat. De gegevens van een geschorst account kunnen nog steeds worden " +
            "gedownload of verwijderd, vanaf een apparaat dat was aangemeld toen " +
            "de schorsing begon, of door te schrijven naar {contact}.",
        ],
      },
      {
        id: "availability",
        heading: "Geen garanties",
        body: [
          "Sketchy wordt geleverd zoals het is, zonder enige garantie dat het " +
            "altijd beschikbaar is, foutloos werkt of wat je maakte voor altijd " +
            "bewaart. De exploitant kan het wijzigen, pauzeren of sluiten.",
        ],
      },
      {
        id: "liability",
        heading: "Aansprakelijkheid",
        body: [
          "Voor zover de wet het toestaat, is de exploitant niet aansprakelijk " +
            "voor indirecte schade of voor het verlies van inhoud of gegevens. " +
            "Niets hier beperkt een aansprakelijkheid die de wet niet laat " +
            "beperken, zoals bij opzet of grove nalatigheid.",
        ],
      },
      {
        id: "leaving",
        heading: "Stoppen",
        body: [
          "Je kunt op elk moment stoppen en je account verwijderen in " +
            "Instellingen. De exploitant kan je toegang beëindigen als je deze " +
            "voorwaarden of de regels overtreedt, of Sketchy helemaal sluiten.",
        ],
      },
      {
        id: "law",
        heading: "Welk recht van toepassing is",
        body: [
          "Op deze voorwaarden is Zwitsers recht van toepassing, dat je niet de " +
            "bescherming afneemt die het dwingende recht van het land waar je " +
            "woont je als consument geeft. Geschillen gaan naar de rechter van " +
            "de vestigingsplaats van de exploitant in Zwitserland, tenzij dat " +
            "recht je het recht geeft om thuis naar de rechter te stappen.",
        ],
      },
      {
        id: "changes",
        heading: "Wijzigingen in deze voorwaarden",
        body: [
          "Als deze voorwaarden op een belangrijk punt veranderen, hoor je dat " +
            "voordat de wijziging ingaat, en blijf je daarna spelen, dan " +
            "accepteer je haar. Vragen gaan naar {contact}.",
        ],
      },
    ],
  },
};
