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
            "lässt – und Passkeys oder eine Zwei-Schritt-Anmeldung, falls du sie " +
            "einrichtest.",
          "Deine Einstellungen und dein Profil: deine Sprachen und Vorlieben, " +
            "ein Profilbild, falls du eins hochlädst, deine Freunde und die " +
            "Spieler, die du blockierst.",
          "Deine Spiele: die Räume, in denen du gespielt hast, deine Rateversuche, " +
            "Punkte und Ergebnisse, deine Reaktionen und deine Zeichnungen.",
          "Der Chat, in Räumen und in der Lobby.",
          "Die Begriffslisten, die du schreibst, und ob du sie veröffentlicht hast.",
          "Meldungen, die du abschickst, und Meldungen über dich, mit den " +
            "Nachrichten und Zeichnungen, auf die sie sich beziehen.",
          "Deine Anmeldungen: eine grobe Beschreibung jedes Geräts (etwa " +
            "„Firefox unter Windows“), wann es zuletzt benutzt wurde, und ein " +
            "mit einem geheimen Schlüssel gebildeter Hash der Netzwerkadresse, von der es kam – nie die " +
            "Adresse selbst. Dieselbe Art Hash begrenzt, wie oft etwas von einer " +
            "Adresse aus getan werden kann.",
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
            "steht.",
          "Um das Spiel fair und sicher zu halten: Meldungen moderieren, " +
            "Schummeln, Spam und Missbrauch verhindern und Konten schützen. Das " +
            "ist das berechtigte Interesse des Betreibers und aller, die spielen.",
          "Um Probleme zu finden und zu beheben, aus demselben Grund.",
          "Nichts über dich wird für Werbung genutzt, verkauft oder zu einem " +
            "Profil über dich zusammengeführt, und keine Entscheidung über dich " +
            "trifft allein eine Maschine.",
        ],
      },
      {
        id: "visibility",
        heading: "Was andere Spieler sehen",
        body: [
          "Wer mit dir in einem Raum ist, sieht deinen Namen, deine Nachrichten, " +
            "deine Zeichnungen und deine Punkte.",
          "Zeichnungen aus einem öffentlichen Raum erscheinen in der Galerie, wo " +
            "jeder sie sehen kann, mit dem Namen, unter dem sie gezeichnet " +
            "wurden. Zeichnungen aus einem privaten Raum sehen nur die, die darin " +
            "waren. Wenn du dein Konto löschst, wird jede deiner Zeichnungen " +
            "gelöscht; soll nur eine einzelne entfernt werden, schreib an " +
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
            "Standardvertragsklauseln der Europäischen Kommission.",
          "Vom Betreiber ernannte Moderatoren sehen die Meldungen, über die sie " +
            "entscheiden, und die Nachrichten und Zeichnungen, auf die sie sich " +
            "beziehen.",
          "An Behörden werden Daten nur herausgegeben, wo das Gesetz es verlangt.",
        ],
      },
      {
        id: "retention",
        heading: "Wie lange es gespeichert wird",
        body: [],
        items: [
          "Chat: 30 Tage. Zeilen, die in einer Meldung zitiert werden, bleiben " +
            "bei der Meldung, solange die Moderation sie braucht.",
          "Gäste: gelöscht nach 30 Tagen ohne abgeschlossenes Spiel, oder nach " +
            "365 Tagen ohne zu spielen, sobald sie eins haben.",
          "Konten: bis du sie löschst.",
          "Anmeldungen: bis sie ablaufen, und 30 Tage danach.",
          "E-Mails an dich: 30 Tage.",
          "Screenshots in Fehlerberichten: bis der Bericht bearbeitet ist, und " +
            "nie länger als 90 Tage.",
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
          "In den Einstellungen kannst du jederzeit alles herunterladen, was " +
            "Sketchy über dich speichert, deinen Namen, deine E-Mail-Adresse und " +
            "dein Profil berichtigen und dein Konto oder deine Gastidentität " +
            "löschen.",
          "Du hast außerdem das Recht zu erfahren, was über dich gespeichert ist " +
            "und wie es genutzt wird, es berichtigen oder löschen zu lassen, der " +
            "Nutzung für die berechtigten Interessen des Betreibers zu " +
            "widersprechen und die Nutzung einschränken zu lassen. Schreib an " +
            "{contact} für alles, was die Einstellungen nicht können.",
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
          "Sketchy setzt ein Cookie, das dich angemeldet hält. Ohne es " +
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
          "Halte dich an die Regeln. Schummle nicht – kein automatisches Raten, " +
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
            "der Galerie bei öffentlichen Räumen, in Begriffslisten, die du " +
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
            "sperren oder ausschließen, die gegen diese Bedingungen oder die " +
            "Regeln verstoßen. Du erfährst, um welche Regel es bei einer " +
            "Entscheidung geht, und ein gesperrtes Konto kann seine Daten " +
            "weiterhin herunterladen und löschen.",
        ],
      },
      {
        id: "availability",
        heading: "Keine Garantien",
        body: [
          "Sketchy wird so bereitgestellt, wie es ist, ohne Versprechen, dass es " +
            "immer verfügbar ist, fehlerfrei funktioniert oder das, was du " +
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
          "Für diese Bedingungen gilt Schweizer Recht. Für Streitigkeiten sind " +
            "die Gerichte am Geschäftssitz des Betreibers in der Schweiz " +
            "zuständig, es sei denn, das Recht des Landes, in dem du lebst, gibt " +
            "dir als Verbraucher das Recht, zu Hause vor Gericht zu gehen.",
        ],
      },
      {
        id: "changes",
        heading: "Änderungen dieser Bedingungen",
        body: [
          "Ändern sich diese Bedingungen, wird die neue Fassung hier " +
            "veröffentlicht. Wer nach einer Änderung weiterspielt, akzeptiert " +
            "sie. Fragen gehen an {contact}.",
        ],
      },
    ],
  },
};
