import type { RulesDocument } from "./types.ts";

/** The rules, in Polish.

A translation of [`en.ts`](./en.ts), which stays the reference: when the
English changes, this is stale until it follows.

Machine-drafted and **not yet read by a native speaker**. The rules are the
one text where a bad translation has consequences - somebody reads them after
being told they broke one, and a mistranslated prohibition is a decision they
cannot check - so this wants a human pass before launch (R-I18N-07).

The ids are not translated and never will be: they are anchors, and a notice
linking to `#spam` has to survive the page being read in Polish
(R-RULES-03). */
export const RULES_PL: RulesDocument = {
  locale: "pl",
  title: "Zasady",
  introHeading: "Wprowadzenie",
  intro: [
    "Sketchy to gra z nieznajomymi i prawie wszystko w niej działa dlatego, że większość ludzi zachowuje się przyzwoicie, nawet jeśli nikt ich o to nie prosi. Te zasady są na chwile, kiedy tak nie jest — i po to, żeby interwencja moderatora, jeśli kiedyś do niej dojdzie, nie była dla ciebie zaskoczeniem.",
    "Większość tego, co tu idzie nie tak, nie wynika ze złej woli. Każdy może mieć gorszy dzień, żart może nie wyjść, a nigdy tak naprawdę nie wiesz, z czym mierzy się osoba po drugiej stronie rysunku. Zacznij od tego założenia, a większość takich sytuacji w ogóle przestanie być warta zgłoszenia.",
    "Nic z tego nie jest tu po to, żeby kogoś karać. Jest po to, żeby pokoje pozostały miejscem, do którego można wpaść, narysować coś absurdalnego i odpocząć. Kiedy już musimy coś rozstrzygnąć, kierujemy się tym, co się wydarzyło, a nie tym, kim jesteś: moderator czyta to, co naprawdę zostało napisane lub narysowane, w kolejności, w jakiej to się działo, i na tej podstawie podejmuje decyzję.",
  ],
  sections: [
    {
      id: "conduct",
      heading: "Jak traktujesz innych",
      blurb: "Grasz z ludźmi, którzy nie mogą po prostu odejść, nie opuszczając przy tym gry. Te dwie zasady dotyczą właśnie tego.",
      rules: [
        {
          id: "harassment",
          heading: "Nękanie",
          body: [
            "Nie atakuj innych graczy. Żadnych wyzwisk, gróźb ani poniżania — dotyczy to także obraźliwych określeń i nienawiści w jakiejkolwiek formie, molestowania seksualnego oraz chodzenia za kimś z pokoju do pokoju, żeby dalej go nękać.",
            "Przekomarzanie się to połowa zabawy i nie ma w nim nic złego — pod warunkiem, że naprawdę bawią się wszyscy i nikt nie posuwa się za daleko. Granica leży tam, gdzie przestaje to być wspólna zabawa: kiedy ktoś ma już dość albo kiedy docinki są wymierzone w jedną osobę, której wcale nie jest do śmiechu. Jeśli nie masz pewności, odpuść. Nic cię to nie kosztuje.",
            "A przegrana runda, nawet sromotna, nie jest powodem, żeby odgrywać się na zwycięzcy — tak samo jak nie jest nim to, że ktoś narysował coś, co ci się nie podoba.",
          ],
          examples: [
            "Czepianie się czyjegoś rysunku tak długo, aż tak naprawdę chodzi już o samą osobę",
            "Atakowanie kogoś ze względu na rasę, religię, płeć, tożsamość płciową, niepełnosprawność lub narodowość",
            "Pójście za kimś do innego pokoju, żeby ciągnąć kłótnię",
          ],
        },
        {
          id: "spam",
          heading: "Spam",
          body: [
            "Nie zalewaj czatu wiadomościami, nie powtarzaj się, żeby zagłuszyć innych, i nie używaj gry do reklamowania czegokolwiek.",
            "Zgadywanie to nie spam, nawet jeśli odpowiedzi robią się zupełnie szalone — szybkie zgadywanie to przecież cała istota gry.",
          ],
          examples: [
            "Powtarzanie wiadomości tak długo, aż nikt nie może nadążyć za grą",
            "Wrzucanie linków albo zaproszeń do innych miejsc",
            "Wklejanie tej samej ściany tekstu w kolejnych pokojach",
          ],
        },
      ],
    },
    {
      id: "content",
      heading: "Co muszą oglądać wszyscy inni",
      blurb: "Twój rysunek, twoja nazwa i twoje zdjęcie trafiają przed oczy ludzi, którzy ich nie wybierali. Nikt nie może odwrócić wzroku od płótna i dalej grać.",
      rules: [
        {
          id: "offensive_drawing",
          heading: "Obraźliwe rysunki",
          body: [
            "Rysuj hasło. Płótno to nie miejsce na treści seksualne, krwawą przemoc, symbole nienawiści ani na atakowanie kogoś z pokoju.",
            "Słabe rysowanie nie jest wbrew zasadom — nikt nie ocenia Twoich kółek. Chodzi o celowe rysowanie czegoś innego niż hasło.",
          ],
          examples: [
            "Rysunki o treści seksualnej lub pełne krwi i przemocy",
            "Symbole nienawiści, nawet jeśli narysowane byle jak",
            "Rysowanie obelgi pod adresem kogoś zamiast hasła",
          ],
        },
        {
          id: "inappropriate_name",
          heading: "Niestosowne nazwy",
          body: [
            "Twoją nazwę widzą wszyscy, z którymi grasz, więc nie umieszczaj w niej obraźliwych określeń ani słów o charakterze seksualnym i nie wybieraj nazwy wymyślonej po to, żeby komuś dogryźć.",
            "Nie podszywaj się też pod innego gracza ani pod moderatora.",
          ],
          examples: [
            "Nazwa zawierająca obraźliwe określenie lub słowo o charakterze seksualnym",
            "Nazwa wymyślona tak, żeby wyglądała jak czyjaś",
            "Nazwa, która jest przytykiem do jednej konkretnej osoby",
          ],
        },
        {
          id: "inappropriate_avatar",
          heading: "Niestosowne zdjęcia",
          body: [
            "To samo dotyczy zdjęcia na Twoim koncie — widać je na Twoim profilu i obok twojej nazwy, gdziekolwiek grasz.",
            "Moderator może usunąć zdjęcie bez żadnych innych konsekwencji dla twojego konta, a jeśli zdarzy się to pierwszy raz, możesz od razu wstawić nowe.",
          ],
          examples: [
            "Obrazy o charakterze seksualnym lub drastyczne",
            "Symbole nienawiści lub symbolika ekstremistyczna",
            "Zdjęcie osoby, która nie zgodziła się na jego umieszczenie",
          ],
        },
      ],
    },
    {
      id: "fair-play",
      heading: "Uczciwa gra",
      blurb: "Gra działa tylko wtedy, gdy zgadywanie jest naprawdę zgadywaniem.",
      rules: [
        {
          id: "cheating",
          heading: "Oszukiwanie",
          body: [
            "Nie zdradzaj hasła nikomu, kto ma je zgadnąć — ani na czacie, ani na rysunku, ani nigdzie poza grą. I nie używaj programu, który gra za ciebie.",
            "Napisanie hasła na płótnie traktujemy tak samo jak podanie go wprost.",
          ],
          examples: [
            "Pisanie albo literowanie hasła w trakcie rysowania",
            "Zdradzenie hasła znajomemu przez rozmowę głosową lub inną aplikację",
            "Używanie drugiego konta, żeby podsuwać sobie hasło",
          ],
        },
      ],
    },
  ],
  enforcement: {
    heading: "Co się dzieje, gdy złamiesz zasadę",
    body: [
      "Zgłoszenia trafiają do moderatora, który widzi, co naprawdę zostało napisane lub narysowane. Większość z nich kończy się niczym — ludzie zgłaszają rzeczy, które okazują się w porządku, i właśnie po to jest możliwość zgłaszania.",
      "Jeśli coś było nie tak, moderator może udzielić ci ostrzeżenia, usunąć zdjęcie albo zawiesić konto. Ostrzeżenie niczego nie ogranicza, ale kolejne zgłoszenie po nim może skończyć się zawieszeniem. Zawieszenie może trwać dzień, tydzień, miesiąc albo nie mieć daty końcowej — i dowiesz się, który z tych wariantów cię dotyczy.",
      "Cokolwiek się stanie, dowiesz się, czego to dotyczyło, i zobaczysz własne słowa albo własny rysunek, który za tym stał. Nikt nie próbuje cię na niczym przyłapać.",
    ],
  },
};
