/** The dialog card's layout, which the stylesheet cannot hold on its own.

A ModalShell's head, body and foot are the card's direct children, and only the
body scrolls: the card is a flex column capped at 90dvh, the head and foot do
not shrink, and the body takes the rest with `min-height: 0` and its own
overflow (R-A11Y-04, #1115). Take the column away and nothing fails loudly -
the body's flex rules simply stop applying, and a tall dialog runs off a
landscape phone with its submit button out of reach. A squash merge dropped
those three lines once without a conflict to show for it, so this holds them. */
import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("../src/styles/dialogs.css", import.meta.url), "utf8")
  .replace(/\/\*[\s\S]*?\*\//g, "");

function declarations(selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const blocks = [...css.matchAll(new RegExp(`(?:^|})\\s*${escaped}\\s*\\{([^}]*)\\}`, "g"))];
  assert.ok(blocks.length > 0, `${selector} is not declared in dialogs.css`);
  const found = new Map();
  for (const [, body] of blocks) {
    for (const line of body.split(";")) {
      const [property, ...value] = line.split(":");
      if (property.trim()) found.set(property.trim(), value.join(":").trim());
    }
  }
  return found;
}

test("the dialog card is a capped flex column", () => {
  const card = declarations(".modal-card");
  assert.equal(card.get("display"), "flex");
  assert.equal(card.get("flex-direction"), "column");
  assert.equal(card.get("max-height"), "90dvh");
});

test("only the body scrolls: it takes the rest, the head and foot keep their height", () => {
  const body = declarations(".modal-content");
  assert.equal(body.get("min-height"), "0");
  assert.equal(body.get("overflow-y"), "auto");
  for (const edge of [".modal-head", ".modal-foot"]) {
    assert.equal(declarations(edge).get("flex"), "0 0 auto", `${edge} must not shrink`);
  }
});
