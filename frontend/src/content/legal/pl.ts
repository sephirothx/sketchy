import type { LegalDocuments } from "./types.ts";

/** Polityka prywatności i warunki korzystania, po polsku (#1417).
A translation of `en.ts`, machine-drafted and awaiting a native reader. */
export const LEGAL_PL: LegalDocuments = {
  locale: "pl",
  privacy: {
    title: "Polityka prywatności",
    intro: [
      "Ta polityka wyjaśnia, co Sketchy przechowuje na Twój temat, dlaczego, " +
        "jak długo i co możesz z tym zrobić. Sketchy jest darmowe: nie " +
        "wyświetla reklam, a nic o Tobie nie jest sprzedawane ani używane do " +
        "sprzedawania Ci czegokolwiek.",
    ],
    sections: [
      {
        id: "operator",
        heading: "Kto odpowiada",
        body: [
          "Sketchy prowadzi jego operator z siedzibą w Szwajcarii, który decyduje, " +
            "co jest przechowywane i dlaczego. Możesz napisać do operatora na " +
            "adres {contact}.",
          "Do wszystkiego, co tu opisano, stosuje się szwajcarskie prawo o " +
            "ochronie danych, a gdy grasz z Unii Europejskiej, także unijne " +
            "ogólne rozporządzenie o ochronie danych (RODO).",
        ],
      },
      {
        id: "data",
        heading: "Co jest przechowywane",
        body: ["Tylko to, czego gra potrzebuje, żeby działać, być uczciwa i bezpieczna:"],
        items: [
          "Nazwa, pod którą grasz, i nazwa użytkownika konta.",
          "Jeśli zakładasz konto: Twój adres e-mail, Twoje hasło – przechowywane " +
            "wyłącznie jako jednokierunkowy skrót, z którego nie da się go " +
            "odtworzyć – oraz klucze dostępu lub logowanie dwuetapowe, jeśli je " +
            "skonfigurujesz.",
          "Twoje ustawienia i profil: Twoje języki i preferencje, zdjęcie " +
            "profilowe, jeśli je wgrasz, Twoi znajomi i gracze, których " +
            "blokujesz.",
          "Twoje gry: pokoje, w których grałeś, Twoje próby, punkty i wyniki, " +
            "Twoje reakcje oraz Twoje rysunki.",
          "Czat, w pokojach i w lobby.",
          "Listy haseł, które piszesz, i to, czy je opublikowałeś.",
          "Zgłoszenia, które wysyłasz, i zgłoszenia dotyczące Ciebie, wraz z " +
            "wiadomościami i rysunkami, których dotyczą.",
          "Twoje logowania: ogólny opis każdego urządzenia (np. „Firefox w " +
            "systemie Windows”), kiedy było ostatnio używane, oraz skrót z " +
            "tajnym kluczem adresu sieciowego, z którego się łączyło – nigdy sam " +
            "adres. Ten sam rodzaj skrótu ogranicza, jak często można coś zrobić " +
            "z jednego adresu.",
          "Zgłoszenia błędów, które wysyłasz, ze zrzutem ekranu, jeśli go " +
            "dołączysz.",
          "Informacje techniczne o Twoim połączeniu i błędach w przeglądarce, " +
            "żeby można było znaleźć i naprawić problemy. Nie zawierają żadnych " +
            "Twoich wiadomości ani rysunków.",
        ],
      },
      {
        id: "purposes",
        heading: "Dlaczego jest przechowywane",
        body: [
          "Żeby prowadzić grę, w którą chcesz grać: pokoje, tury, punkty, Twoją " +
            "historię i Twoje konto. To umowa między Tobą a operatorem, opisana " +
            "w warunkach korzystania.",
          "Żeby gra była uczciwa i bezpieczna: moderowanie zgłoszeń, " +
            "powstrzymywanie oszustw, spamu i nadużyć oraz ochrona kont. To " +
            "prawnie uzasadniony interes operatora i wszystkich, którzy grają.",
          "Żeby znajdować i naprawiać problemy, z tego samego powodu.",
          "Nic o Tobie nie jest używane do reklam, sprzedawane ani używane do " +
            "tworzenia Twojego profilu, a żadnej decyzji dotyczącej Ciebie nie " +
            "podejmuje sama maszyna.",
        ],
      },
      {
        id: "visibility",
        heading: "Co widzą inni gracze",
        body: [
          "Osoby w pokoju widzą Twoją nazwę, Twoje wiadomości, Twoje rysunki i " +
            "Twój wynik.",
          "Rysunki z pokoju publicznego trafiają do Galerii, gdzie każdy może je " +
            "zobaczyć, z nazwą, pod którą powstały. Rysunki z pokoju prywatnego " +
            "widzą tylko osoby, które w nim były. Usunięcie konta kasuje " +
            "wszystkie Twoje rysunki; żeby usunąć tylko jeden, napisz na adres " +
            "{contact}.",
          "Opublikowaną przez Ciebie listę haseł może przeczytać każdy, z Twoją " +
            "nazwą jako autorem. Twój profil pokazuje to, co zdecydujesz się " +
            "pokazać.",
        ],
      },
      {
        id: "recipients",
        heading: "Kto jeszcze ma z nimi do czynienia",
        body: [
          "Nikt nie otrzymuje Twoich danych, żeby używać ich do własnych celów. " +
            "Operator korzysta z kilku dostawców, żeby Sketchy działało – " +
            "hostingu, dostarczania przez sieć i poczty e-mail – którzy " +
            "przetwarzają je wyłącznie na jego polecenie. Jeśli któryś z nich " +
            "robi to poza Szwajcarią i UE, odbywa się to z zabezpieczeniami " +
            "uznawanymi przez prawo, takimi jak standardowe klauzule umowne " +
            "Komisji Europejskiej.",
          "Moderatorzy wyznaczeni przez operatora widzą zgłoszenia, o których " +
            "decydują, oraz wiadomości i rysunki, których dotyczą.",
          "Dane są przekazywane władzom tylko wtedy, gdy wymaga tego prawo.",
        ],
      },
      {
        id: "retention",
        heading: "Jak długo jest przechowywane",
        body: [],
        items: [
          "Czat: 30 dni. Wiersze przytoczone w zgłoszeniu są przechowywane " +
            "razem z nim tak długo, jak potrzebuje ich moderacja.",
          "Goście: usuwani po 30 dniach bez ukończonej gry albo po 365 dniach " +
            "bez gry, jeśli mają już jakąś ukończoną.",
          "Konta: dopóki ich nie usuniesz.",
          "Logowania: do wygaśnięcia, a potem jeszcze 30 dni.",
          "Wysłane do Ciebie e-maile: 30 dni.",
          "Zrzuty ekranu ze zgłoszeń błędów: do rozpatrzenia zgłoszenia i nigdy " +
            "dłużej niż 90 dni.",
          "Eksporty danych, o które prosisz: 7 dni.",
          "Ukończone gry – punkty, rysunki, reakcje – są częścią historii " +
            "wszystkich, którzy grali, więc są przechowywane. Gdy usuniesz konto, " +
            "Twoje rysunki zostaną skasowane, a Twoje miejsce w tych grach " +
            "zanonimizowane, dzięki czemu historia innych zostaje nienaruszona – " +
            "bez Ciebie.",
        ],
      },
      {
        id: "rights",
        heading: "Twoje prawa",
        body: [
          "W Ustawieniach możesz w każdej chwili pobrać wszystko, co Sketchy " +
            "przechowuje na Twój temat, poprawić swoją nazwę, e-mail i profil " +
            "oraz usunąć konto lub tożsamość gościa.",
          "Masz też prawo wiedzieć, co jest o Tobie przechowywane i jak jest " +
            "używane, żądać sprostowania lub usunięcia, sprzeciwić się " +
            "wykorzystywaniu dla prawnie uzasadnionych interesów operatora oraz " +
            "żądać ograniczenia przetwarzania. Napisz na adres {contact} w " +
            "każdej sprawie, której nie załatwisz w Ustawieniach.",
          "Jeśli uważasz, że Twoje dane są przetwarzane niewłaściwie, możesz " +
            "złożyć skargę do organu ochrony danych: w Szwajcarii do Federalnego " +
            "Pełnomocnika ds. Ochrony Danych i Informacji (FDPIC), a w UE do " +
            "organu kraju, w którym mieszkasz.",
        ],
      },
      {
        id: "cookies",
        heading: "Pliki cookie i pamięć",
        body: [
          "Sketchy ustawia jeden plik cookie, który utrzymuje Cię zalogowanym. " +
            "Jest niezbędny do działania gry, więc nie prosimy o zgodę. Twoje " +
            "ustawienia są też zapamiętywane w pamięci Twojej własnej " +
            "przeglądarki.",
          "Nie ma plików cookie reklamowych ani analitycznych, ani skryptów " +
            "innych podmiotów.",
        ],
      },
      {
        id: "age",
        heading: "Wiek",
        body: [
          "Sketchy jest dla osób w wieku co najmniej {age} lat. Jeśli jesteś " +
            "rodzicem i uważasz, że Twoje dziecko poniżej {age} lat gra, napisz " +
            "na adres {contact}, a jego dane zostaną usunięte.",
        ],
      },
      {
        id: "changes",
        heading: "Zmiany tej polityki",
        body: [
          "Jeśli ta polityka się zmieni, nowa wersja zostanie opublikowana tutaj. " +
            "Zmiana, która ma znaczenie dla sposobu wykorzystania Twoich danych, " +
            "nie obejmie tego, co zapisano wcześniej, bez uprzedniego " +
            "poinformowania Cię.",
        ],
      },
    ],
  },
  terms: {
    title: "Warunki korzystania",
    intro: [
      "Te warunki to umowa między Tobą a operatorem Sketchy. Grając, " +
        "akceptujesz je; jeśli się na nie nie zgadzasz, nie korzystaj ze " +
        "Sketchy.",
    ],
    sections: [
      {
        id: "agreement",
        heading: "Sketchy jest w becie",
        body: [
          "Sketchy jest darmowe i wciąż powstaje: funkcje się zmieniają, coś " +
            "się psuje, a w rzadkich przypadkach coś może przepaść. Dziękujemy, " +
            "że mimo to grasz.",
        ],
      },
      {
        id: "age",
        heading: "Kto może grać",
        body: ["Musisz mieć co najmniej {age} lat. Grając, potwierdzasz, że tak jest."],
      },
      {
        id: "accounts",
        heading: "Twoja nazwa i konto",
        body: [
          "Wybierz nazwę, która nie podszywa się pod nikogo i nie łamie zasad. " +
            "Nie udostępniaj hasła ani logowania: odpowiadasz za to, co dzieje " +
            "się na Twoim koncie.",
          "Gość istnieje w jednej przeglądarce. Wyczyszczenie jej danych oznacza " +
            "utratę gościa, chyba że zamieniłeś go w konto.",
        ],
      },
      {
        id: "fair-play",
        heading: "Uczciwa gra",
        body: [
          "Przestrzegaj zasad. Nie oszukuj – żadnego automatycznego zgadywania, " +
            "podpowiadania odpowiedzi innym ani grania jako kilka osób dla " +
            "przewagi – nie próbuj psuć ani przeciążać Sketchy i nie używaj go do " +
            "niczego niezgodnego z prawem.",
        ],
      },
      {
        id: "content",
        heading: "To, co rysujesz i piszesz",
        body: [
          "To, co rysujesz, piszesz i publikujesz, pozostaje Twoje. Żeby gra " +
            "mogła działać, pozwalasz operatorowi przechowywać, pokazywać i " +
            "kopiować to w ramach Sketchy – w Twoim pokoju, w Galerii w przypadku " +
            "pokoi publicznych, w listach haseł, które publikujesz, i w kopiach, " +
            "które robią z nich inni – bezpłatnie, na całym świecie i tak długo, " +
            "jak Sketchy to przechowuje.",
          "Rysuj i pisz tylko to, czym masz prawo się dzielić, i nic, czego " +
            "zakazują zasady.",
        ],
      },
      {
        id: "moderation",
        heading: "Moderacja",
        body: [
          "Moderatorzy mogą ukrywać treści, upominać graczy oraz zawieszać lub " +
            "blokować konta, które łamią te warunki lub zasady. Dowiesz się, " +
            "której zasady dotyczy decyzja, a zawieszone konto nadal może pobrać " +
            "i usunąć swoje dane.",
        ],
      },
      {
        id: "availability",
        heading: "Bez gwarancji",
        body: [
          "Sketchy jest udostępniane w obecnej postaci, bez obietnicy, że " +
            "zawsze będzie dostępne, będzie działać bez błędów albo zachowa na " +
            "zawsze to, co stworzyłeś. Operator może je zmienić, wstrzymać lub " +
            "zamknąć.",
        ],
      },
      {
        id: "liability",
        heading: "Odpowiedzialność",
        body: [
          "W zakresie dozwolonym przez prawo operator nie odpowiada za szkody " +
            "pośrednie ani za utratę treści lub danych. Nic tutaj nie ogranicza " +
            "odpowiedzialności, której prawo nie pozwala ograniczyć, na przykład " +
            "za winę umyślną lub rażące niedbalstwo.",
        ],
      },
      {
        id: "leaving",
        heading: "Odejście",
        body: [
          "Możesz w każdej chwili przestać i usunąć konto w Ustawieniach. " +
            "Operator może zakończyć Twój dostęp, jeśli łamiesz te warunki lub " +
            "zasady, albo całkowicie zamknąć Sketchy.",
        ],
      },
      {
        id: "law",
        heading: "Jakie prawo obowiązuje",
        body: [
          "Te warunki podlegają prawu szwajcarskiemu. Spory rozstrzygają sądy " +
            "właściwe dla siedziby operatora w Szwajcarii, chyba że prawo kraju, " +
            "w którym mieszkasz, daje Ci jako konsumentowi prawo do dochodzenia " +
            "roszczeń w swoim kraju.",
        ],
      },
      {
        id: "changes",
        heading: "Zmiany tych warunków",
        body: [
          "Jeśli te warunki się zmienią, nowa wersja zostanie opublikowana " +
            "tutaj. Dalsza gra po zmianie oznacza jej akceptację. Pytania kieruj " +
            "na adres {contact}.",
        ],
      },
    ],
  },
};
