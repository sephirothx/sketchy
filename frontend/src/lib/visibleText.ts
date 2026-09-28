/** Text as a player can see it. */

/**
 * Code points that draw nothing: format characters (`\p{Cf}` - the zero-width
 * space and joiners, the soft hyphen, the byte-order mark, the direction
 * overrides) and the rest of Unicode's default-ignorable set. Pasted text
 * carries them - a soft hyphen from a web page, a zero-width space from a chat
 * app - and the server refuses them in a prompt or an alias (#1245). Nobody
 * can see them, so taking them out changes nothing a player sees.
 */
const INVISIBLE = /[\p{Cf}\p{Default_Ignorable_Code_Point}]/gu;

export function withoutInvisibleCharacters(text: string): string {
  return text.replace(INVISIBLE, "");
}
