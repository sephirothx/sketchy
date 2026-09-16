import { doodleNameOf } from "../../lib/avatarDoodles";

/**
 * What fills a disc that is not showing an initial: an uploaded picture, or
 * one of our doodles (#579). The one renderer the roster disc, the header
 * chip, the profile header and the moderation queue share, so a doodle is
 * drawn the same way wherever an account appears.
 *
 * A doodle goes through `<use>` into the sprite rather than through `<img>`:
 * an image is opaque to the page's colours, and a symbol drawn in
 * `currentColor` takes the disc's ink - the colour its initial would have been
 * - which is what keeps the player's name color meaning something.
 *
 * Decorative by default, because every disc sits beside the name it belongs
 * to. `label` is for the one place a picture is the subject rather than an
 * illustration: a moderator judging it.
 */
export function AvatarPicture({ url, label }: { url: string; label?: string }) {
  const doodle = doodleNameOf(url);
  const naming = label
    ? { role: "img" as const, "aria-label": label }
    : { "aria-hidden": true as const };
  if (doodle) {
    return (
      <svg className="avatar-doodle" focusable="false" data-doodle={doodle} {...naming}>
        <use href={url} width="100%" height="100%" />
      </svg>
    );
  }
  return <img src={url} alt={label ?? ""} />;
}
