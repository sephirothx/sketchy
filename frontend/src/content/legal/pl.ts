import type { LegalDocuments } from "./types.ts";

/** Polityka prywatności i warunki korzystania, po polsku (#1417).
A translation of `en.ts`, machine-drafted and awaiting a native reader.
Gender-neutral forms and lower-case "ty", as the interface writes them;
"hasło do konta" for a password, since a bare "hasło" is a game prompt. */
export const LEGAL_PL: LegalDocuments = {
  locale: "pl",
  privacy: {
    title: "Polityka prywatności",
    intro: [
      "Ta polityka wyjaśnia, co Sketchy przechowuje na twój temat, dlaczego, " +
        "jak długo i co możesz z tym zrobić. Sketchy jest darmowe: nie " +
        "wyświetla reklam, a nic o tobie nie jest sprzedawane ani używane do " +
        "sprzedawania ci czegokolwiek.",
    ],
    sections: [
      {
        id: "operator",
        heading: "Kto odpowiada",
        body: [
          "Sketchy prowadzi jego operator z siedzibą w Szwajcarii, który " +
            "decyduje, co jest przechowywane i dlaczego. Do operatora można " +
            "napisać na adres {contact}.",
          "Do wszystkiego, co tu opisano, stosuje się szwajcarskie prawo o " +
            "ochronie danych, a przy grze z Unii Europejskiej także unijne " +
            "ogólne rozporządzenie o ochronie danych (RODO).",
        ],
      },
      {
        id: "data",
        heading: "Co jest przechowywane",
        body: ["Tylko to, czego gra potrzebuje, żeby działać, być uczciwa i bezpieczna:"],
        items: [
          "Nazwa, pod którą grasz, i nazwa użytkownika konta.",
          "Przy zakładaniu konta: twój adres e-mail, twoje hasło do konta – " +
            "przechowywane wyłącznie jako jednokierunkowy skrót, z którego nie da " +
            "się go odtworzyć – oraz klucze dostępu lub weryfikacja dwuetapowa, " +
            "jeśli zostaną skonfigurowane.",
          "Twoje ustawienia i profil: twoje języki i preferencje, zdjęcie " +
            "profilowe, jeśli zostanie wgrane, twoi znajomi, zablokowani gracze, " +
            "zapisane ustawienia pokoi oraz listy oznaczone gwiazdką.",
          "Twoje gry: pokoje, w których toczyła się gra, twoje odpowiedzi, " +
            "punkty i wyniki, twoje reakcje, twoje rysunki oraz rysunki " +
            "udostępnione przez ciebie w Galerii.",
          "Czat, w pokojach i w lobby.",
          "Wiadomości w twojej skrzynce, dotyczące twojego konta, twoich " +
            "rysunków i znajomych.",
          "Twoje listy haseł oraz informacja, czy zostały opublikowane.",
          "Zgłoszenia wysłane przez ciebie i zgłoszenia dotyczące ciebie, wraz " +
            "z wiadomościami i rysunkami, których dotyczą, a także każde " +
            "ostrzeżenie lub zawieszenie twojego konta.",
          "Dziennik bezpieczeństwa i moderacji obejmujący ważne działania – " +
            "np. zmiany hasła do konta i adresu e-mail, blokowanie kogoś, zmianę " +
            "obrazka oraz decyzje moderacji.",
          "Twoje logowania: ogólny opis każdego urządzenia (np. „Firefox w " +
            "systemie Windows”), kiedy było ostatnio używane, oraz skrót z " +
            "tajnym kluczem adresu sieciowego, z którego się łączyło. Ten sam " +
            "rodzaj skrótu trafia do powyższego dziennika i ogranicza, jak " +
            "często można coś zrobić z jednego adresu. Sketchy nigdy nie " +
            "przechowuje samego adresu, choć widzą go dostawcy, którzy przesyłają " +
            "jego ruch.",
          "Momenty wejścia do pokoju i wyjścia z niego, żeby dało się wyśledzić " +
            "problemy.",
          "Wysłane zgłoszenia błędów, ze zrzutem ekranu, jeśli zostanie " +
            "dołączony.",
          "Informacje techniczne o połączeniu i błędach w przeglądarce, żeby " +
            "można było znaleźć i naprawić problemy. Nie zawierają żadnych " +
            "twoich wiadomości ani rysunków.",
        ],
      },
      {
        id: "purposes",
        heading: "Dlaczego jest przechowywane",
        body: [
          "Żeby prowadzić grę, w którą chcesz grać: pokoje, tury, punkty, twoją " +
            "historię i twoje konto. To umowa między tobą a operatorem, opisana " +
            "w warunkach korzystania. Twój adres e-mail służy wyłącznie twojemu " +
            "kontu: do jego potwierdzenia, resetowania hasła do konta oraz " +
            "powiadomień o zmianach i decyzjach, które go dotyczą.",
          "Żeby gra była uczciwa i bezpieczna: moderowanie zgłoszeń, " +
            "powstrzymywanie oszustw, spamu i nadużyć oraz ochrona kont. To " +
            "prawnie uzasadniony interes operatora i wszystkich, którzy grają.",
          "Żeby znajdować i naprawiać problemy, z tego samego powodu.",
          "Żeby odpowiadać władzom, gdy prawo zobowiązuje do tego operatora.",
          "Nic o tobie nie jest używane do reklam, sprzedawane ani używane do " +
            "tworzenia twojego profilu, a żadnej decyzji wywołującej wobec " +
            "ciebie skutki prawne lub podobnie istotne nie podejmuje sama " +
            "maszyna.",
        ],
      },
      {
        id: "visibility",
        heading: "Co widzą inni gracze",
        body: [
          "Osoby w pokoju widzą twoją nazwę, twoje wiadomości, twoje rysunki i " +
            "twój wynik.",
          "Rysunek trafia do Galerii, gdzie każdy może go zobaczyć, dopiero gdy " +
            "ktoś go udostępni, z nazwą, pod którą powstał, i nazwą osoby, która " +
            "udostępniła go jako pierwsza. Swoje rysunki możesz udostępniać z " +
            "każdego pokoju. W pokoju publicznym inne grające w nim osoby też " +
            "mogą udostępniać twoje, bez wcześniejszego pytania: gra w pokoju " +
            "publicznym to gra publiczna, zgodnie z warunkami korzystania. Każdy " +
            "swój rysunek możesz zdjąć z Galerii i wtedy nikt nie może go " +
            "ponownie udostępnić, chyba że zrobisz to ty. Rysunki z pokoju " +
            "prywatnego widzą tylko osoby, które w nim były, chyba że udostępnisz " +
            "swoje.",
          "Usunięcie konta kasuje wszystkie twoje rysunki, oprócz kopii " +
            "dołączonej do zgłoszenia, która zostaje przy nim; żeby skasować " +
            "tylko jeden, napisz na adres {contact}.",
          "Opublikowaną przez ciebie listę haseł może przeczytać każdy, z twoją " +
            "nazwą jako autorem. Twój profil pokazuje to, co zdecydujesz się " +
            "pokazać.",
        ],
      },
      {
        id: "recipients",
        heading: "Kto jeszcze ma z nimi do czynienia",
        body: [
          "Nikt nie otrzymuje twoich danych, żeby używać ich do własnych celów. " +
            "Operator korzysta z kilku dostawców, żeby Sketchy działało – " +
            "hostingu, dostarczania przez sieć i poczty e-mail – którzy " +
            "przetwarzają je wyłącznie na polecenie operatora. Jeśli któryś z " +
            "nich robi to poza Szwajcarią i UE, odbywa się to z zabezpieczeniami " +
            "uznawanymi przez prawo, takimi jak standardowe klauzule umowne " +
            "Komisji Europejskiej; napisz na adres {contact}, żeby zapytać, o " +
            "jakie kraje i zabezpieczenia chodzi.",
          "Każde połączenie ze Sketchy jest szyfrowane, hasła do kont są " +
            "przechowywane wyłącznie jako jednokierunkowe skróty, zespół " +
            "moderacji i administracji widzi tylko to, czego wymaga dana rola, a " +
            "stare dane są usuwane zgodnie z terminami podanymi niżej.",
          "Moderatorzy i administratorzy wyznaczeni przez operatora widzą " +
            "zgłoszenia, o których decydują, i to, czego dotyczą. Administratorzy " +
            "czytają też zgłoszenia błędów i mogą sprawdzić konto oraz jego " +
            "ostatnią aktywność, gdy coś pójdzie nie tak.",
          "Dane są przekazywane władzom tylko wtedy, gdy wymaga tego prawo.",
        ],
      },
      {
        id: "retention",
        heading: "Jak długo jest przechowywane",
        body: [],
        items: [
          "Czat: 30 dni, oprócz wierszy przytoczonych w zgłoszeniu, które " +
            "zostają przy nim.",
          "Zgłoszenia i to, czego dotyczą, zawieszenia, dziennik " +
            "bezpieczeństwa i moderacji oraz zgłoszenia błędów: przechowywane " +
            "trwale jako zapis moderacji i bezpieczeństwa usługi, także po " +
            "usunięciu konta. Wpisy dziennika przestają wtedy wskazywać ciebie.",
          "Ostrzeżenia: 12 miesięcy; usuwane razem z kontem.",
          "Wiadomości w twojej skrzynce: 90 dni, przeczytane czy nie; usuwane " +
            "razem z kontem.",
          "Zrzuty ekranu ze zgłoszeń błędów: do rozpatrzenia zgłoszenia i nigdy " +
            "dłużej niż 90 dni.",
          "Goście: usuwani po 30 dniach bez ukończonej gry albo po 365 dniach " +
            "bez gry, jeśli mają już jakąś ukończoną.",
          "Konta: do ich usunięcia. Znajomości, blokady, listy haseł, zapisane " +
            "ustawienia pokoi i gwiazdki: do ich usunięcia albo usunięcia konta.",
          "Logowania: do wygaśnięcia, a potem jeszcze 30 dni – z wyjątkiem logowań zawieszonego konta, przechowywanych przez cały czas zawieszenia, bo to jedyna droga do pobrania lub usunięcia jego danych.",
          "Wejścia do pokoi i wyjścia z nich: 30 dni.",
          "Wysłane do ciebie e-maile: 30 dni.",
          "Zamówione eksporty danych: 7 dni.",
          "Ukończone gry – punkty, rysunki, reakcje – są częścią historii " +
            "wszystkich, którzy grali, więc są przechowywane. Po usunięciu konta " +
            "twoje rysunki zostają skasowane, a twoje miejsce w tych grach " +
            "zanonimizowane, dzięki czemu historia innych zostaje nienaruszona – " +
            "bez ciebie.",
        ],
      },
      {
        id: "rights",
        heading: "Twoje prawa",
        body: [
          "W Ustawieniach możesz w każdej chwili pobrać kopię swoich danych, " +
            "poprawić swoją nazwę, e-mail i profil oraz usunąć konto lub " +
            "tożsamość gościa.",
          "Masz też prawo uzyskać wszystko, co jest o tobie przechowywane, i " +
            "dowiedzieć się, jak jest używane – także to, czego nie zawiera " +
            "pobrana kopia, np. zgłoszenia dotyczące ciebie – żądać sprostowania " +
            "lub usunięcia, otrzymać dane w formacie, który można przenieść " +
            "gdzie indziej, sprzeciwić się ich wykorzystywaniu dla prawnie " +
            "uzasadnionych interesów operatora oraz żądać ograniczenia " +
            "przetwarzania. Napisz na adres {contact} w każdej sprawie, której " +
            "nie da się załatwić w Ustawieniach.",
          "Jeśli uważasz, że twoje dane są przetwarzane niewłaściwie, możesz " +
            "złożyć skargę do organu ochrony danych: w Szwajcarii do federalnego " +
            "pełnomocnika ds. ochrony danych (FDPIC/EDÖB), a w UE do organu " +
            "kraju, w którym mieszkasz.",
        ],
      },
      {
        id: "cookies",
        heading: "Pliki cookie i pamięć",
        body: [
          "Sketchy ustawia jeden jedyny plik cookie, który utrzymuje " +
            "zalogowanie. Jest niezbędny do działania gry, więc nie prosimy o " +
            "zgodę. Twoje ustawienia są też zapamiętywane w pamięci twojej " +
            "własnej przeglądarki.",
          "Nie ma plików cookie reklamowych ani analitycznych, ani skryptów " +
            "innych podmiotów.",
        ],
      },
      {
        id: "age",
        heading: "Wiek",
        body: [
          "Sketchy jest dla osób w wieku co najmniej {age} lat. Rodzic, który " +
            "uważa, że jego dziecko poniżej {age} lat gra, może napisać na adres " +
            "{contact}, a dane dziecka zostaną usunięte.",
        ],
      },
      {
        id: "changes",
        heading: "Zmiany tej polityki",
        body: [
          "Jeśli ta polityka się zmieni, nowa wersja zostanie opublikowana tutaj. " +
            "Zmiana, która ma znaczenie dla sposobu wykorzystania twoich danych, " +
            "nie obejmie tego, co zapisano wcześniej, bez uprzedniej informacji.",
        ],
      },
    ],
  },
  terms: {
    title: "Warunki korzystania",
    intro: [
      "Te warunki to umowa między tobą a operatorem Sketchy. Grając, " +
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
            "Nie udostępniaj hasła do konta ani logowania: odpowiadasz za to, co " +
            "dzieje się na twoim koncie.",
          "Gość istnieje w jednej przeglądarce. Wyczyszczenie jej danych oznacza " +
            "utratę gościa, chyba że został zamieniony w konto.",
        ],
      },
      {
        id: "fair-play",
        heading: "Uczciwa gra",
        body: [
          "Przestrzegaj zasad. Nie oszukuj – żadnych automatycznych odpowiedzi, " +
            "podpowiadania odpowiedzi innym ani grania jako kilka osób dla " +
            "przewagi – nie próbuj psuć ani przeciążać Sketchy i nie używaj go do " +
            "niczego niezgodnego z prawem.",
        ],
      },
      {
        id: "content",
        heading: "To, co rysujesz i piszesz",
        body: [
          "To, co rysujesz, piszesz i publikujesz, pozostaje twoje. Żeby gra " +
            "mogła działać, pozwalasz operatorowi przechowywać, pokazywać i " +
            "kopiować to w ramach Sketchy – w twoim pokoju, w Galerii, gdy " +
            "rysunek zostanie udostępniony, " +
            "w listach haseł, które publikujesz, i w kopiach, " +
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
          "Moderacją zajmują się osoby dorosłe wyznaczone przez operatora. " +
            "Mogą ukrywać treści, udzielać upomnień oraz zawieszać konta, które " +
            "łamią te warunki lub zasady. Jeśli moderator zapisze, " +
            "której zasady dotyczy decyzja, otrzymasz tę informację. Dane " +
            "zawieszonego konta nadal można pobrać lub usunąć – z urządzenia, " +
            "które było zalogowane w chwili zawieszenia, albo pisząc na adres " +
            "{contact}.",
        ],
      },
      {
        id: "availability",
        heading: "Bez gwarancji",
        body: [
          "Sketchy jest udostępniane w obecnej postaci, bez żadnej gwarancji, że " +
            "zawsze będzie dostępne, będzie działać bez błędów albo zachowa na " +
            "zawsze to, co powstało. Operator może je zmienić, wstrzymać lub " +
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
            "Operator może zakończyć twój dostęp, jeśli łamiesz te warunki lub " +
            "zasady, albo całkowicie zamknąć Sketchy.",
        ],
      },
      {
        id: "law",
        heading: "Jakie prawo obowiązuje",
        body: [
          "Te warunki podlegają prawu szwajcarskiemu, które nie odbiera ci " +
            "ochrony, jaką jako konsumentowi daje ci bezwzględnie obowiązujące " +
            "prawo kraju, w którym mieszkasz. Spory rozstrzygają sądy właściwe " +
            "dla siedziby operatora w Szwajcarii, chyba że to prawo daje ci " +
            "prawo do dochodzenia roszczeń w swoim kraju.",
        ],
      },
      {
        id: "changes",
        heading: "Zmiany tych warunków",
        body: [
          "Jeśli te warunki zmienią się w istotnym punkcie, dowiesz się o tym, " +
            "zanim zmiana zacznie obowiązywać, a dalsza gra potem oznacza jej " +
            "akceptację. Pytania kieruj na adres {contact}.",
        ],
      },
    ],
  },
};
