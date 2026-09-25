import assert from "node:assert/strict";
import test from "node:test";

import { SITE_NAV_SLACK, siteLinkCurrent, siteNavMode } from "../src/lib/siteNav.ts";

test("a site link is the current page only on its own path", () => {
  assert.equal(siteLinkCurrent("/", "/"), "page");
  assert.equal(siteLinkCurrent("/gallery", "/gallery"), "page");
  assert.equal(siteLinkCurrent("/rules", "/rules/"), "page");
  assert.equal(siteLinkCurrent("/gallery", "/rules"), undefined);
});

test("a page nested under a link marks the section, not the page", () => {
  assert.equal(siteLinkCurrent("/gallery", "/gallery/42"), "true");
  assert.equal(siteLinkCurrent("/prompt-lists", "/prompt-lists/en-standard"), "true");
  assert.equal(siteLinkCurrent("/community-lists", "/community-lists/7"), "true");
});

test("the lobby is never current off the lobby, and prefixes are whole segments", () => {
  assert.equal(siteLinkCurrent("/", "/gallery"), undefined);
  assert.equal(siteLinkCurrent("/", "/profile/3"), undefined);
  // My prompt lists is not under Prompt stats, and a lookalike path is not under the Gallery.
  assert.equal(siteLinkCurrent("/prompt-lists", "/my-prompt-lists"), undefined);
  assert.equal(siteLinkCurrent("/gallery", "/gallery-old"), undefined);
});

test("the nav is the fullest mode that fits: labels, else icons, else nothing", () => {
  const widths = { labels: 600, icons: 220 };
  assert.equal(siteNavMode({ ...widths, room: 700, current: "labels" }), "labels");
  assert.equal(siteNavMode({ ...widths, room: 599, current: "labels" }), "icons");
  assert.equal(siteNavMode({ ...widths, room: 219, current: "icons" }), "hidden");
  assert.equal(siteNavMode({ ...widths, room: 0, current: "hidden" }), "hidden");
});

test("it shrinks the moment a mode stops fitting, and grows only with room to spare", () => {
  const widths = { labels: 600, icons: 220 };
  // Exactly enough keeps the mode on screen...
  assert.equal(siteNavMode({ ...widths, room: 600, current: "labels" }), "labels");
  assert.equal(siteNavMode({ ...widths, room: 220, current: "icons" }), "icons");
  // ...but is not enough to grow into it.
  assert.equal(siteNavMode({ ...widths, room: 600, current: "icons" }), "icons");
  assert.equal(siteNavMode({ ...widths, room: 220, current: "hidden" }), "hidden");
  assert.equal(siteNavMode({ ...widths, room: 600 + SITE_NAV_SLACK, current: "icons" }), "labels");
  assert.equal(siteNavMode({ ...widths, room: 220 + SITE_NAV_SLACK, current: "hidden" }), "icons");
  // From nothing straight to the labels when there is room for them.
  assert.equal(siteNavMode({ ...widths, room: 900, current: "hidden" }), "labels");
});
