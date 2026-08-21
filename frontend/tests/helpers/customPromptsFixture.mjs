export function createMaximumCustomPromptsFixture() {
  const prompts = Array.from({ length: 10_000 }, (_, index) => {
    const token = index.toString(36).padStart(3, "0");
    if (index % 3 === 0) return `s${token}`;
    if (index % 3 === 1) return `medium${token}`;
    if (index === 2) return "skeleton in a closet";
    return `long-custom-${"W".repeat(17)}${token}`;
  });
  return { prompts, raw: prompts.join("\n") };
}
