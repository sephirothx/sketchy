import { Flag } from "./icons";
import { promptLanguageLabel } from "../lib/promptLanguages";
import { interfaceLocale, ui } from "../content/ui/index.ts";

/**
 * The languages a player plays in, as flags (#1212): the default larger, then
 * the others in the order the player ranked them - the order the lobby ranks
 * those rooms in (#1211).
 *
 * One picture with one name, not a row of images: a screen reader hears
 * "Plays in Italian; also English and Spanish" once, in the reader's own
 * language, where seven flags would be seven announcements of nothing. The
 * same sentence is the tooltip, for a flag nobody recognises.
 */
export function PlayLanguageFlags({ languages }: { languages: readonly string[] }) {
  if (languages.length === 0) return null;
  const [language, ...others] = languages;
  const named = promptLanguageLabel(language);
  const label = others.length === 0
    ? ui.profilePage.playsIn({ language: named })
    : ui.profilePage.playsInAlso({
        language: named,
        others: new Intl.ListFormat(interfaceLocale(), { type: "conjunction" }).format(
          others.map(promptLanguageLabel),
        ),
      });
  return (
    <span className="play-language-flags" role="img" aria-label={label} title={label}>
      <span className="play-language-flag is-default" data-language={language}>
        <Flag language={language} width={24} />
      </span>
      {others.map((other) => (
        <span key={other} className="play-language-flag" data-language={other}>
          <Flag language={other} width={16} />
        </span>
      ))}
    </span>
  );
}
