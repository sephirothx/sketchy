import type { LegalDocuments } from "./types.ts";

/** Datenschutzerklärung und Nutzungsbedingungen, auf Deutsch (#1417).
A translation of `en.ts`, machine-drafted and awaiting a native reader. */
export const LEGAL_DE: LegalDocuments = {
  locale: "de",
  privacy: {
    title: "Datenschutzerklärung",
    intro: [
      "Diese Erklärung beschreibt, was Sketchy über dich speichert, warum, wie " +
        "lange und was du dagegen tun kannst. Sketchy ist kostenlos: Es zeigt " +
        "keine Werbung, und nichts über dich wird verkauft oder genutzt, um dir " +
        "etwas zu verkaufen.",
    ],
    sections: [
      {
        id: "operator",
        heading: "Wer verantwortlich ist",
        body: [
          "Sketchy wird von seinem Betreiber mit Sitz in der Schweiz betrieben, " +
            "der entscheidet, was gespeichert wird und warum. Du erreichst den " +
            "Betreiber unter {contact}.",
          "Für alles hier gilt das Schweizer Datenschutzrecht und, wenn du aus " +
            "der Europäischen Union spielst, auch die Datenschutz-Grundverordnung " +
            "der EU.",
        ],
      },
      {
        id: "data",
        heading: "Was gespeichert wird",
        body: ["Nur, was das Spiel braucht, um zu funktionieren, fair zu sein und sicher zu bleiben:"],
        items: [
          "Der Name, unter dem du spielst, und der Benutzername eines Kontos.",
          "Wenn du ein Konto anlegst: deine E-Mail-Adresse, dein Passwort – nur " +
            "als Einweg-Hash gespeichert, aus dem es sich nicht zurückgewinnen " +
            "lässt – und Passkeys oder eine Zwei-Faktor-Authentifizierung, falls " +
            "du sie einrichtest.",
          "Deine Einstellungen und dein Profil: deine Sprachen und Vorlieben, " +
            "ein Profilbild, falls du eins hochlädst, deine Freunde, die Spieler, " +
            "die du blockierst, deine gespeicherten Raumeinstellungen und die " +
            "Listen, die du mit einem Stern markierst.",
          "Deine Spiele: die Räume, in denen du gespielt hast, deine Tipps, " +
            "Punkte und Ergebnisse, deine Reaktionen, deine Zeichnungen und die " +
            "Zeichnungen, die du in die Galerie gestellt hast.",
          "Der Chat, in Räumen und in der Lobby.",
          "Die Nachrichten in deinem Posteingang, zu deinem Konto, deinen " +
            "Zeichnungen und deinen Freundschaften.",
          "Die Begriffslisten, die du schreibst, und ob du sie veröffentlicht hast.",
          "Meldungen, die du abschickst, und Meldungen über dich, mit den " +
            "Nachrichten und Zeichnungen, auf die sie sich beziehen; dazu jede " +
            "Verwarnung oder Sperre deines Kontos.",
          "Ein Sicherheits- und Moderationsprotokoll sensibler Aktionen – etwa " +
            "Änderungen von Passwort und E-Mail-Adresse, das Blockieren von " +
            "jemandem, das Ändern deines Bildes und Entscheidungen der " +
            "Moderation.",
          "Deine Anmeldungen: eine grobe Beschreibung jedes Geräts (etwa " +
            "„Firefox unter Windows“), wann es zuletzt benutzt wurde, und ein " +
            "mit einem geheimen Schlüssel gebildeter Hash der Netzwerkadresse, " +
            "von der es kam. Dieselbe Art Hash wird im obigen Protokoll " +
            "gespeichert und begrenzt, wie oft etwas von einer Adresse aus getan " +
            "werden kann. Sketchy speichert nie die Adresse selbst, auch wenn die " +
            "Dienstleister, die seinen Datenverkehr ausliefern, sie sehen.",
          "Wann du Räume betrittst und verlässt, damit sich Probleme " +
            "nachvollziehen lassen.",
          "Fehlerberichte, die du schickst, mit einem Screenshot, falls du einen " +
            "anhängst.",
          "Technische Angaben zu deiner Verbindung und zu Fehlern in deinem " +
            "Browser, damit Probleme gefunden und behoben werden können. Sie " +
            "enthalten keine deiner Nachrichten oder Zeichnungen.",
        ],
      },
      {
        id: "purposes",
        heading: "Warum es gespeichert wird",
        body: [
          "Um das Spiel zu betreiben, das du spielen willst: Räume, Runden, " +
            "Punkte, deinen Verlauf und dein Konto. Das ist die Vereinbarung " +
            "zwischen dir und dem Betreiber, wie sie in den Nutzungsbedingungen " +
            "steht. Deine E-Mail-Adresse wird nur für dein Konto verwendet: um es " +
            "zu bestätigen, um dein Passwort zurückzusetzen und um dich über " +
            "Änderungen daran und Entscheidungen dazu zu informieren.",
          "Um das Spiel fair und sicher zu halten: Meldungen moderieren, " +
            "Schummeln, Spam und Missbrauch verhindern und Konten schützen. Das " +
            "ist das berechtigte Interesse des Betreibers und aller, die spielen.",
          "Um Probleme zu finden und zu beheben, aus demselben Grund.",
          "Um Behörden zu antworten, wo das Gesetz den Betreiber dazu " +
            "verpflichtet.",
          "Nichts über dich wird für Werbung genutzt, verkauft oder zu einem " +
            "Profil über dich zusammengeführt, und keine Entscheidung mit " +
            "rechtlicher oder ähnlich erheblicher Wirkung für dich trifft allein " +
            "eine Maschine.",
        ],
      },
      {
        id: "visibility",
        heading: "Was andere Spieler sehen",
        body: [
          "Wer mit dir in einem Raum ist, sieht deinen Namen, deine Nachrichten, " +
            "deine Zeichnungen und deine Punkte.",
          "Eine Zeichnung erscheint erst dann in der Galerie, wo alle sie sehen " +
            "können, wenn jemand sie in die Galerie stellt – mit dem Namen, unter " +
            "dem sie gezeichnet wurde, und dem Namen der Person, die sie als " +
            "Erste hineingestellt hat. Deine eigenen Zeichnungen kannst du aus " +
            "jedem Raum in die Galerie stellen. In einem öffentlichen Raum können " +
            "auch die anderen im Raum deine hineinstellen, ohne vorher zu fragen: " +
            "Wer in einem öffentlichen Raum spielt, spielt öffentlich, nach den " +
            "Nutzungsbedingungen. Jede deiner Zeichnungen kannst du aus der " +
            "Galerie nehmen, und dann kann niemand sie erneut hineinstellen, außer " +
            "du selbst. Zeichnungen aus einem privaten Raum sehen nur die, die " +
            "darin waren, außer du stellst deine eigenen in die Galerie.",
          "Wenn du dein Konto löschst, wird jede deiner Zeichnungen gelöscht, " +
            "außer einer Kopie, die einer Meldung beigefügt ist und bei der " +
            "Meldung bleibt; soll nur eine einzelne gelöscht werden, schreib an " +
            "{contact}.",
          "Eine Begriffsliste, die du veröffentlichst, kann jeder lesen, mit " +
            "deinem Namen als Autor. Dein Profil zeigt, was du dort zeigen willst.",
        ],
      },
      {
        id: "recipients",
        heading: "Wer sonst damit umgeht",
        body: [
          "Niemand erhält deine Daten, um sie für eigene Zwecke zu nutzen. Der " +
            "Betreiber nutzt einige Dienstleister, um Sketchy zu betreiben – " +
            "Hosting, Netzwerkauslieferung und E-Mail –, die sie nur nach seinen " +
            "Anweisungen verarbeiten. Geschieht das außerhalb der Schweiz und der " +
            "EU, dann mit Garantien, die das Gesetz anerkennt, etwa den " +
            "Standardvertragsklauseln der Europäischen Kommission; welche Länder " +
            "und welche Garantien, erfährst du unter {contact}.",
          "Vom Betreiber ernannte Moderatoren und Administratoren sehen die " +
            "Meldungen, über die sie entscheiden, und das, worauf sie sich " +
            "beziehen. Administratoren lesen außerdem Fehlerberichte und können " +
            "ein Konto und seine jüngste Aktivität nachschlagen, wenn etwas " +
            "schiefgeht.",
          "An Behörden werden Daten nur herausgegeben, wo das Gesetz es verlangt.",
        ],
      },
      {
        id: "retention",
        heading: "Wie lange es gespeichert wird",
        body: [],
        items: [
          "Chat: 30 Tage, außer Zeilen, die in einer Meldung zitiert werden; " +
            "sie bleiben bei der Meldung.",
          "Meldungen und das, worauf sie sich beziehen, Sperren, das " +
            "Sicherheits- und Moderationsprotokoll und Fehlerberichte: dauerhaft " +
            "aufbewahrt als Nachweis der Moderation und der Sicherheit des " +
            "Dienstes, auch nachdem du dein Konto gelöscht hast. " +
            "Protokolleinträge nennen dich danach nicht mehr.",
          "Verwarnungen: 12 Monate, und mit deinem Konto gelöscht.",
          "Nachrichten in deinem Posteingang: 90 Tage, gelesen oder nicht, und " +
            "mit deinem Konto gelöscht.",
          "Screenshots in Fehlerberichten: bis der Bericht bearbeitet ist, und " +
            "nie länger als 90 Tage.",
          "Gäste: gelöscht nach 30 Tagen ohne abgeschlossenes Spiel, oder nach " +
            "365 Tagen ohne zu spielen, sobald sie eins haben.",
          "Konten: bis du sie löschst. Freundschaften, Blockierungen, " +
            "Begriffslisten, gespeicherte Raumeinstellungen und Sterne: bis du " +
            "sie entfernst oder dein Konto löschst.",
          "Anmeldungen: bis sie ablaufen, und 30 Tage danach – außer denen eines gesperrten Kontos, die für die Dauer der Sperre bleiben, weil sie sein einziger Weg sind, seine Daten herunterzuladen oder zu löschen.",
          "Betreten und Verlassen von Räumen: 30 Tage.",
          "E-Mails an dich: 30 Tage.",
          "Datenexporte, die du anforderst: 7 Tage.",
          "Abgeschlossene Spiele – Punkte, Zeichnungen, Reaktionen – gehören zum " +
            "Verlauf aller, die mitgespielt haben, und bleiben deshalb erhalten. " +
            "Löschst du dein Konto, werden deine Zeichnungen gelöscht und dein " +
            "Platz in diesen Spielen anonymisiert, sodass der Verlauf der anderen " +
            "erhalten bleibt, ohne dich.",
        ],
      },
      {
        id: "rights",
        heading: "Deine Rechte",
        body: [
          "In den Einstellungen kannst du jederzeit eine Kopie deiner Daten " +
            "herunterladen, deinen Namen, deine E-Mail-Adresse und dein Profil " +
            "berichtigen und dein Konto oder deine Gastidentität löschen.",
          "Du hast außerdem das Recht, alles zu erfahren, was über dich " +
            "gespeichert ist und wie es genutzt wird – auch das, was der Download " +
            "nicht enthält, etwa Meldungen über dich –, es berichtigen oder " +
            "löschen zu lassen, es in einem Format zu erhalten, das du anderswo " +
            "verwenden kannst, der Nutzung für die berechtigten Interessen des " +
            "Betreibers zu widersprechen und die Nutzung einschränken zu lassen. " +
            "Schreib an {contact} für alles, was die Einstellungen nicht können.",
          "Wenn du meinst, dass mit deinen Daten falsch umgegangen wird, kannst " +
            "du dich bei einer Datenschutzbehörde beschweren: in der Schweiz beim " +
            "Eidgenössischen Datenschutz- und Öffentlichkeitsbeauftragten (EDÖB), " +
            "in der EU bei der Behörde des Landes, in dem du lebst.",
        ],
      },
      {
        id: "cookies",
        heading: "Cookies und Speicher",
        body: [
          "Sketchy setzt ein einziges Cookie, das dich angemeldet hält. Ohne es " +
            "funktioniert das Spiel nicht, deshalb wirst du nicht um Zustimmung " +
            "gebeten. Deine Einstellungen werden außerdem im Speicher deines " +
            "eigenen Browsers gemerkt.",
          "Es gibt keine Werbe- oder Analyse-Cookies und keine Skripte von " +
            "anderen.",
        ],
      },
      {
        id: "age",
        heading: "Alter",
        body: [
          "Sketchy ist für Menschen ab {age} Jahren. Wenn du ein Elternteil bist " +
            "und glaubst, dass dein Kind unter {age} spielt, schreib an {contact}, " +
            "und seine Daten werden gelöscht.",
        ],
      },
      {
        id: "changes",
        heading: "Änderungen dieser Erklärung",
        body: [
          "Ändert sich diese Erklärung, wird die neue Fassung hier " +
            "veröffentlicht. Eine Änderung, die beeinflusst, wie deine Daten " +
            "genutzt werden, gilt nicht für zuvor Gespeichertes, ohne dass du " +
            "vorher davon erfährst.",
        ],
      },
    ],
  },
  terms: {
    title: "Nutzungsbedingungen",
    intro: [
      "Diese Bedingungen sind die Vereinbarung zwischen dir und dem Betreiber " +
        "von Sketchy. Wer spielt, akzeptiert sie; wenn du das nicht willst, " +
        "nutze Sketchy bitte nicht.",
    ],
    sections: [
      {
        id: "agreement",
        heading: "Sketchy ist in der Beta",
        body: [
          "Sketchy ist kostenlos und noch im Bau: Funktionen ändern sich, Dinge " +
            "gehen kaputt, und in seltenen Fällen kann etwas verloren gehen. " +
            "Danke, dass du es trotzdem spielst.",
        ],
      },
      {
        id: "age",
        heading: "Wer spielen darf",
        body: ["Du musst mindestens {age} Jahre alt sein. Wer spielt, bestätigt das."],
      },
      {
        id: "accounts",
        heading: "Dein Name und dein Konto",
        body: [
          "Wähle einen Namen, der nicht vorgibt, jemand anderes zu sein, und " +
            "nicht gegen die Regeln verstößt. Behalte dein Passwort und deine " +
            "Anmeldung für dich: Du bist verantwortlich für das, was mit deinem " +
            "Konto getan wird.",
          "Ein Gast lebt in einem Browser. Löschst du dessen Daten, ist der Gast " +
            "weg, außer du hast ein Konto daraus gemacht.",
        ],
      },
      {
        id: "fair-play",
        heading: "Fair spielen",
        body: [
          "Halte dich an die Regeln. Schummle nicht – keine automatischen Tipps, " +
            "kein Verraten der Antwort, kein Spielen als mehrere Personen, um " +
            "einen Vorteil zu haben –, versuche nicht, Sketchy kaputt zu machen " +
            "oder zu überlasten, und nutze es für nichts Rechtswidriges.",
        ],
      },
      {
        id: "content",
        heading: "Was du zeichnest und schreibst",
        body: [
          "Was du zeichnest, schreibst und veröffentlichst, bleibt deins. Damit " +
            "das Spiel funktioniert, erlaubst du dem Betreiber, es innerhalb von " +
            "Sketchy zu speichern, zu zeigen und zu kopieren – in deinem Raum, in " +
            "der Galerie, sobald eine Zeichnung hineingestellt ist, in " +
            "Begriffslisten, die du " +
            "veröffentlichst, und in Kopien, die andere davon machen –, " +
            "kostenlos, weltweit und so lange, wie Sketchy es aufbewahrt.",
          "Zeichne und schreibe nur, was du teilen darfst, und nichts, was die " +
            "Regeln verbieten.",
        ],
      },
      {
        id: "moderation",
        heading: "Moderation",
        body: [
          "Moderatoren können Inhalte ausblenden, Spieler verwarnen und Konten " +
            "sperren, die gegen diese Bedingungen oder die Regeln verstoßen. Wenn " +
            "die Moderation festhält, um welche Regel es bei einer Entscheidung " +
            "geht, erfährst du es. Die Daten eines gesperrten Kontos können " +
            "weiterhin heruntergeladen oder gelöscht werden – von einem Gerät, " +
            "das bei Beginn der Sperre angemeldet war, oder per Nachricht an " +
            "{contact}.",
        ],
      },
      {
        id: "availability",
        heading: "Keine Garantien",
        body: [
          "Sketchy wird so bereitgestellt, wie es ist, ohne jede Garantie, dass " +
            "es immer verfügbar ist, fehlerfrei funktioniert oder das, was du " +
            "gemacht hast, für immer behält. Der Betreiber kann es ändern, " +
            "pausieren oder einstellen.",
        ],
      },
      {
        id: "liability",
        heading: "Haftung",
        body: [
          "Soweit das Gesetz es erlaubt, haftet der Betreiber nicht für " +
            "indirekte Schäden oder für den Verlust von Inhalten oder Daten. " +
            "Nichts hier beschränkt eine Haftung, die das Gesetz nicht " +
            "beschränken lässt, etwa bei Vorsatz oder grober Fahrlässigkeit.",
        ],
      },
      {
        id: "leaving",
        heading: "Aufhören",
        body: [
          "Du kannst jederzeit aufhören und dein Konto in den Einstellungen " +
            "löschen. Der Betreiber kann deinen Zugang beenden, wenn du gegen " +
            "diese Bedingungen oder die Regeln verstößt, oder Sketchy ganz " +
            "einstellen.",
        ],
      },
      {
        id: "law",
        heading: "Welches Recht gilt",
        body: [
          "Für diese Bedingungen gilt Schweizer Recht; es nimmt dir nicht den " +
            "Schutz, den dir das zwingende Recht des Landes, in dem du lebst, als " +
            "Verbraucher gibt. Für Streitigkeiten sind die Gerichte am " +
            "Geschäftssitz des Betreibers in der Schweiz zuständig, es sei denn, " +
            "dieses Recht gibt dir das Recht, zu Hause vor Gericht zu gehen.",
        ],
      },
      {
        id: "changes",
        heading: "Änderungen dieser Bedingungen",
        body: [
          "Ändern sich diese Bedingungen in einem wichtigen Punkt, erfährst du " +
            "es, bevor die Änderung gilt; wer danach weiterspielt, akzeptiert " +
            "sie. Fragen gehen an {contact}.",
        ],
      },
    ],
  },
};
