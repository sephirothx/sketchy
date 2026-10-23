import { formattersFor } from "../ui/format.ts";
import type { SeoCopy } from "./types.ts";

/** The descriptions, in polski: machine-drafted from [`en.ts`](./en.ts) like the
rest of the interface, awaiting a native reader (#784). */
const { counted } = formattersFor("pl");

export const SEO_PL: SeoCopy = {
  locale: "pl",
  home: "Darmowa gra online w rysowanie i zgadywanie, jak kalambury. Graj ze znajomymi w przeglądarce: bez konta i bez pobierania.",
  rules: "Zasady, dzięki którym Sketchy jest przyjemne: traktowanie innych, to, co rysujesz i piszesz, uczciwa gra i co się dzieje po złamaniu zasady.",
  terms: "Warunki gry w Sketchy: kto może grać, konta, to, co rysujesz i piszesz, moderacja i odejście.",
  privacy: "Co Sketchy przechowuje o tobie, dlaczego, jak długo i co możesz z tym zrobić. Bez reklam i nic o tobie nie jest sprzedawane.",
  solo: "Zgaduj w pojedynkę rysunki z prawdziwych gier: codziennie nowe Wyzwanie dnia i swobodne serie, kiedy tylko chcesz.",
  promptList: (p) =>
    `${counted(p.count, { one: "hasło", few: "hasła", many: "haseł", other: "hasła" })} z listy ${p.name} do gier w rysowanie i zgadywanie, takich jak kalambury, z informacją, jak często gracze naprawdę je zgadują.`,
};
