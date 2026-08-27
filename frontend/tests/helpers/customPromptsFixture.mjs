import { MAX_CUSTOM_PROMPTS } from "../../src/lib/customPrompts.ts";

// Derived, not repeated: the point of the fixture is to be exactly as large as
// the limit allows, which stops being true the moment the limit moves.
export function createMaximumCustomPromptsFixture() {
  const prompts = Array.from({ length: MAX_CUSTOM_PROMPTS }, (_, index) => {
    const token = index.toString(36).padStart(3, "0");
    if (index % 3 === 0) return `s${token}`;
    if (index % 3 === 1) return `medium${token}`;
    if (index === 2) return "skeleton in a closet";
    return `long-custom-${"W".repeat(17)}${token}`;
  });
  return { prompts, raw: prompts.join("\n") };
}
