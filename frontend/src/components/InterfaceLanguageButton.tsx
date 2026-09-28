import { LanguagePicker } from "./LanguagePicker";
import { useInterfaceLocale } from "../hooks/useInterfaceLocale";
import { LOCALES, type Locale } from "../lib/interfaceLocale.ts";
import { ui } from "../content/ui/index.ts";

/** The language you read in, as a flag in the header of every page outside a
room (#1280).

The same control the room setup uses for its prompt language, a size smaller
to sit among the header's buttons. A flag rather than a word because the
person who needs it most cannot read the word yet. */
export function InterfaceLanguageButton() {
  const [locale, chooseLocale] = useInterfaceLocale();
  return (
    <LanguagePicker
      label={ui.settingsOverlay.interfaceLanguage}
      value={locale}
      options={LOCALES}
      onChange={(next) => chooseLocale(next as Locale)}
      flagOnly
      small
    />
  );
}
