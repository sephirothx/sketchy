import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

// The podium and the profile's place badges print a medal-coloured number on
// that medal's own tint. The number is ordinary text, so it owes WCAG AA's
// 4.5:1 — and gold, the lightest medal, is the one that can quietly lose it
// when a tint is made a shade stronger.

const THEME = readFileSync(new URL("../src/styles/theme.css", import.meta.url), "utf8");

function block(selector) {
  const start = THEME.indexOf(`${selector} {`);
  assert.notEqual(start, -1, `${selector} is missing from theme.css`);
  return THEME.slice(start, THEME.indexOf("\n}", start));
}

function tokens(selector) {
  const values = {};
  for (const [, name, value] of block(selector).matchAll(/--([a-z-]+):\s*([^;]+);/g)) {
    values[name] = value.trim();
  }
  return values;
}

function rgba(value) {
  const hex = value.match(/^#([0-9a-f]{6})$/i);
  if (hex) {
    const n = Number.parseInt(hex[1], 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255, 1];
  }
  const fn = value.match(/^rgba?\(([^)]+)\)$/);
  assert.ok(fn, `not a colour: ${value}`);
  const [r, g, b, a = 1] = fn[1].split(",").map(Number);
  return [r, g, b, a];
}

// An alpha wash is seen over the card the podium and the badges sit on.
function over(top, ground) {
  const [r, g, b, a] = top;
  return [0, 1, 2].map((i) => [r, g, b][i] * a + ground[i] * (1 - a));
}

function luminance(rgb) {
  const [r, g, b] = rgb.map((channel) => {
    const v = channel / 255;
    return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a, b) {
  const [high, low] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (high + 0.05) / (low + 0.05);
}

const light = tokens(":root");
const themes = {
  light,
  dark: { ...light, ...tokens('[data-theme="dark"]') },
};

for (const [theme, values] of Object.entries(themes)) {
  for (const medal of ["gold", "silver", "bronze"]) {
    test(`${theme}: ${medal} numbers read on the ${medal} tint`, () => {
      const card = rgba(values.card);
      const fill = over(rgba(values[`${medal}-soft`]), card);
      const ink = rgba(values[medal]);
      const ratio = contrast(ink.slice(0, 3), fill);
      assert.ok(ratio >= 4.5, `${medal} on ${medal}-soft is ${ratio.toFixed(2)}:1 in ${theme}`);
    });
  }
}
