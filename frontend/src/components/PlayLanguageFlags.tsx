import { Flag } from "./icons";
import { PROMPT_LANGUAGE_LABELS, promptLanguageLabel } from "../lib/promptLanguages";
import { interfaceLocale, ui } from "../content/ui/index.ts";

/**
 * The languages a player plays in, as flags (#1212): the default larger, then
 * the others in the order the player ranked them - the order the lobby ranks
 * those rooms in (#1211).
 *
 * 24 and 18 wide are 17 and 13 tall: whole pixels, and both odd, so the
 * smaller ones centre on the larger without a half-pixel edge (see `Flag`).
 *
 * One picture with one name, not a row of images: a screen reader hears
 * "Plays in Italian; also English and Spanish" once, in the reader's own
 * language, where eight flags would be eight announcements of nothing. The
 * same sentence is the tooltip, for a flag nobody recognises.
 */
export function PlayLanguageFlags({ languages }: { languages: readonly string[] }) {
  // Only languages this build can draw and name: one from a newer server
  // would be a gap in the row and a code in the sentence.
  const known = languages.filter((language) => language in PROMPT_LANGUAGE_LABELS);
  if (known.length === 0) return null;
  const [language, ...others] = known;
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
          <Flag language={other} width={18} />
        </span>
      ))}
    </span>
  );
}
