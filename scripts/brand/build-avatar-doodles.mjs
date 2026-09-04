#!/usr/bin/env node
// Draws the avatar doodle sprite with the brand's own pen (R-AVA-06).
//
// Source of truth: scripts/brand/avatar-doodles.mjs — each doodle authored as
// centrelines on a 24x24 grid, which is the drawing. This file is the pen: it
// walks each centreline and sweeps a brush along it, so what ships is a filled
// outline with a tapering, breathing width, the way the logo and the 404
// drawing are (both Inkscape calligraphy exported as filled outlines).
//
// Doing it here rather than by hand is what makes the hand consistent. The
// wobble, the pressure and the overshoot come from the brush, so a doodle only
// has to be the right SHAPE — and a shape simple enough to survive the 19px
// disc, which is the smallest one a player list draws.
//
// Every value the brush jitters comes from a seeded PRNG keyed on the doodle
// id and the stroke's position in it, so the sprite is byte-stable: rerunning
// this with the same source rewrites the same file, which is what lets
// check-doodles-regenerated.sh tell a hand edit from a redraw.
//
// Strokes are ribbons, never annuli: a closed shape is a centreline that goes
// round and past its own start. That keeps every subpath a single simple loop
// filled with the default nonzero rule (self-overlap paints, it does not
// punch), and it is also why a hole - the palette's thumb - costs nothing but
// another stroke.
//
// Run:  node scripts/brand/build-avatar-doodles.mjs
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { DOODLES } from "./avatar-doodles.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const repo = join(here, "..", "..");
const OUT = join(repo, "frontend", "public", "avatars", "doodles.svg");

// How finely a centreline is walked. 0.3 of a grid unit is well under a pixel
// at every size a disc is drawn, so the sampling never shows.
const STEP = 0.3;
// Roughly how long one undulation of the wobble is, in grid units. Six is
// about a fifth of the disc: visible as a hand at 52px, invisible at 19px.
const WOBBLE_WAVELENGTH = 6;
// How far off the line the brush may stray, as a fraction of its own width.
const WOBBLE = 0.11;
// How much the width breathes along a stroke.
const PRESSURE = 0.14;
// Simplification of the emitted outline, in grid units: 0.02 is a fifth of a
// pixel at the largest disc anybody sees, and it halves the file.
const TOLERANCE = 0.05;

/* -------------------------------------------------------------- randomness */

function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** A string to a 32-bit seed, so a doodle's jitter is keyed on its name. */
function hashSeed(text) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/**
 * A smooth, bounded, periodic wiggle over arc length.
 *
 * Periodic because a closed stroke comes back to where it started: a wobble
 * that did not close would leave a step in the line exactly where the pen
 * laps its own beginning. Built from whole-numbered harmonics of the stroke's
 * own length, which is what makes the period the stroke.
 */
function makeWave(rand, length, wavelength, harmonics = 3) {
  const base = Math.max(1, Math.round(length / wavelength));
  const terms = [];
  let norm = 0;
  for (let i = 0; i < harmonics; i++) {
    const k = base + i;
    const amplitude = (1 / (i + 1)) * (0.7 + 0.6 * rand());
    terms.push({ k, amplitude, phase: rand() * Math.PI * 2 });
    norm += amplitude;
  }
  return (u) => {
    let sum = 0;
    for (const term of terms) sum += term.amplitude * Math.sin(2 * Math.PI * term.k * u + term.phase);
    return sum / norm;
  };
}

/* ------------------------------------------------------------------ curves */

function point(x, y) {
  return { x, y };
}

/**
 * Catmull-Rom through the authored points, so a doodle is written as the few
 * places the line goes and not as bezier handles.
 */
function spline(points, closed, samplesPerSegment = 14) {
  // A point marked a corner is fed in twice: the segment between the copies
  // has no length, which pins the tangent and gives an ear its tip.
  const pts = points.flatMap(([x, y, corner]) => (corner ? [point(x, y), point(x, y)] : [point(x, y)]));
  const n = pts.length;
  const at = (i) => (closed ? pts[((i % n) + n) % n] : pts[Math.max(0, Math.min(n - 1, i))]);
  const out = [];
  const segments = closed ? n : n - 1;
  for (let i = 0; i < segments; i++) {
    const p0 = at(i - 1);
    const p1 = at(i);
    const p2 = at(i + 1);
    const p3 = at(i + 2);
    for (let j = 0; j < samplesPerSegment; j++) {
      const t = j / samplesPerSegment;
      const t2 = t * t;
      const t3 = t2 * t;
      out.push(
        point(
          0.5 * (2 * p1.x + (-p0.x + p2.x) * t + (2 * p0.x - 5 * p1.x + 4 * p2.x - p3.x) * t2 + (-p0.x + 3 * p1.x - 3 * p2.x + p3.x) * t3),
          0.5 * (2 * p1.y + (-p0.y + p2.y) * t + (2 * p0.y - 5 * p1.y + 4 * p2.y - p3.y) * t2 + (-p0.y + 3 * p1.y - 3 * p2.y + p3.y) * t3),
        ),
      );
    }
  }
  out.push(closed ? point(pts[0].x, pts[0].y) : point(at(n - 1).x, at(n - 1).y));
  return out;
}

function distance(a, b) {
  return Math.hypot(b.x - a.x, b.y - a.y);
}

function totalLength(pts) {
  let sum = 0;
  for (let i = 1; i < pts.length; i++) sum += distance(pts[i - 1], pts[i]);
  return sum;
}

/** Even spacing, so the wobble's wavelength means the same everywhere. */
function resample(pts, step) {
  const out = [pts[0]];
  let carry = 0;
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1];
    const b = pts[i];
    let span = distance(a, b);
    if (span < 1e-9) continue;
    let travelled = -carry;
    while (travelled + step <= span) {
      travelled += step;
      const t = travelled / span;
      out.push(point(a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t));
    }
    carry = span - travelled;
  }
  const last = pts[pts.length - 1];
  if (distance(out[out.length - 1], last) > step * 0.4) out.push(last);
  return out;
}

/** Unit tangents by central difference; the ends borrow their neighbour's. */
function tangents(pts) {
  return pts.map((_, i) => {
    const a = pts[Math.max(0, i - 1)];
    const b = pts[Math.min(pts.length - 1, i + 1)];
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const len = Math.hypot(dx, dy) || 1;
    return { x: dx / len, y: dy / len };
  });
}

function smoothstep(t) {
  const c = Math.max(0, Math.min(1, t));
  return c * c * (3 - 2 * c);
}

/** Ramer-Douglas-Peucker: the outline keeps its shape and loses its samples. */
function simplify(pts, tolerance) {
  if (pts.length < 3) return pts.slice();
  const keep = new Array(pts.length).fill(false);
  keep[0] = true;
  keep[pts.length - 1] = true;
  const stack = [[0, pts.length - 1]];
  while (stack.length) {
    const [from, to] = stack.pop();
    const a = pts[from];
    const b = pts[to];
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const span = Math.hypot(dx, dy) || 1;
    let worst = -1;
    let worstIndex = -1;
    for (let i = from + 1; i < to; i++) {
      const d = Math.abs((pts[i].x - a.x) * dy - (pts[i].y - a.y) * dx) / span;
      if (d > worst) {
        worst = d;
        worstIndex = i;
      }
    }
    if (worst > tolerance) {
      keep[worstIndex] = true;
      stack.push([from, worstIndex], [worstIndex, to]);
    }
  }
  return pts.filter((_, i) => keep[i]);
}

/* ------------------------------------------------------------------- brush */

/**
 * Sweep the brush along one centreline and return the outline that traces it.
 *
 * The ribbon is the left offset out and the right offset back, joined by a
 * half-turn at each end - a round cap drawn rather than declared, because a
 * filled outline has no stroke-linecap to ask for. The tip never tapers to
 * nothing: the smallest disc is 19 pixels across, where the whole doodle is
 * about 14, and a stroke that ends in a point ends in nothing at all there.
 */
function sweep(stroke, seed) {
  const {
    p,
    closed = false,
    w = 2,
    lap = 2.4,
    over = 0,
    head = closed ? 0.72 : 0.6,
    tail = closed ? 0.42 : 0.5,
    wobble = WOBBLE,
  } = stroke;

  let line = spline(p, closed);
  if (closed) {
    // Round and past the start: the lap is what a pen does, and it keeps this
    // one simple loop instead of an outer ring and an inner one.
    const lead = spline(p, closed).slice(1);
    let walked = 0;
    for (let i = 0; i < lead.length && walked < lap; i++) {
      walked += distance(line[line.length - 1], lead[i]);
      line.push(lead[i]);
    }
  }
  line = resample(line, STEP);

  if (over > 0 && !closed) {
    const start = tangents(line)[0];
    const end = tangents(line)[line.length - 1];
    line.unshift(point(line[0].x - start.x * over, line[0].y - start.y * over));
    line.push(point(line[line.length - 1].x + end.x * over, line[line.length - 1].y + end.y * over));
    line = resample(line, STEP);
  }

  const rand = mulberry32(seed);
  const length = totalLength(line);
  const stray = makeWave(rand, length, WOBBLE_WAVELENGTH);
  const press = makeWave(rand, length, WOBBLE_WAVELENGTH * 2.5, 2);

  // Off the line first, then measure again: the offsets have to follow the
  // wobbled centreline, not the one that was authored.
  const straight = tangents(line);
  const amplitude = wobble * w;
  const wobbled = line.map((q, i) => {
    const u = i / (line.length - 1);
    const n = { x: -straight[i].y, y: straight[i].x };
    const d = amplitude * stray(u);
    return point(q.x + n.x * d, q.y + n.y * d);
  });

  const t = tangents(wobbled);
  const ramp = Math.min(closed ? lap : 1.8, length * 0.22);
  const left = [];
  const right = [];
  const half = [];
  let walked = 0;
  for (let i = 0; i < wobbled.length; i++) {
    if (i > 0) walked += distance(wobbled[i - 1], wobbled[i]);
    const u = walked / (length || 1);
    const lift =
      Math.min(
        head + (1 - head) * smoothstep(walked / ramp),
        tail + (1 - tail) * smoothstep((length - walked) / ramp),
      ) * (1 + PRESSURE * press(u));
    const h = (w / 2) * lift;
    half.push(h);
    const n = { x: -t[i].y, y: t[i].x };
    left.push(point(wobbled[i].x + n.x * h, wobbled[i].y + n.y * h));
    right.push(point(wobbled[i].x - n.x * h, wobbled[i].y - n.y * h));
  }

  // The half-turn at each tip, drawn as points so the outline stays one
  // polygon and its bounding box is exactly the points it is made of.
  const cap = (centre, tangent, h, sign) => {
    const out = [];
    const start = Math.atan2(-tangent.x * sign, tangent.y * sign);
    for (let i = 1; i < 8; i++) {
      const angle = start + (sign * Math.PI * i) / 8;
      out.push(point(centre.x + Math.cos(angle) * h, centre.y + Math.sin(angle) * h));
    }
    return out;
  };

  const last = wobbled.length - 1;
  return [
    ...simplify(left, TOLERANCE),
    ...cap(wobbled[last], t[last], half[last], -1),
    ...simplify(right, TOLERANCE).reverse(),
    ...cap(wobbled[0], t[0], half[0], 1),
  ];
}

/** A dot is a blob, not a circle: the same hand, at the size of a pen press. */
function blob(cx, cy, r, seed) {
  const rand = mulberry32(seed);
  const wave = makeWave(rand, 8, 3.2, 2);
  const out = [];
  for (let i = 0; i < 20; i++) {
    const u = i / 20;
    const angle = u * Math.PI * 2;
    const radius = r * (1 + 0.09 * wave(u));
    out.push(point(cx + Math.cos(angle) * radius, cy + Math.sin(angle) * radius));
  }
  return out;
}

/* ------------------------------------------------------------------ output */

function round(value) {
  return Number(value.toFixed(2));
}

function subpath(points) {
  const head = `M${round(points[0].x)} ${round(points[0].y)}`;
  const rest = points
    .slice(1)
    .map((q) => `${round(q.x)} ${round(q.y)}`)
    .join(" ");
  return `${head}L${rest}Z`;
}

const symbols = [];
for (const doodle of DOODLES) {
  const loops = [];
  (doodle.strokes ?? []).forEach((stroke, index) => {
    loops.push(sweep(stroke, hashSeed(`${doodle.id}/stroke/${index}`)));
  });
  (doodle.dots ?? []).forEach(([cx, cy, r], index) => {
    loops.push(blob(cx, cy, r, hashSeed(`${doodle.id}/dot/${index}`)));
  });

  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const loop of loops) {
    for (const q of loop) {
      if (q.x < minX) minX = q.x;
      if (q.y < minY) minY = q.y;
      if (q.x > maxX) maxX = q.x;
      if (q.y > maxY) maxY = q.y;
    }
  }
  // A square on the CIRCLE that contains the drawing, not on its bounding
  // box. The doodle is drawn inside a disc, and a square box lets whatever
  // reaches its corners - the fox's ear tips, the star's points - sit at
  // 71% of the way out along a diagonal and poke straight through the rim.
  // Sizing on the enclosing circle instead makes every doodle fill the same
  // share of the disc it is actually drawn in, which is the thing that was
  // meant. Centred on the bounding box, which is within a few percent of the
  // smallest enclosing circle and needs none of its arithmetic.
  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;
  let radius = 0;
  for (const loop of loops) {
    for (const q of loop) radius = Math.max(radius, Math.hypot(q.x - cx, q.y - cy));
  }
  const side = radius * 2;
  const x = round(cx - radius);
  const y = round(cy - radius);
  const d = loops.map(subpath).join("");
  symbols.push(
    `  <symbol id="${doodle.id}" viewBox="${x} ${y} ${round(side)} ${round(side)}">` +
      `<path fill="currentColor" d="${d}"/></symbol>`,
  );
}

const header = `<!-- GENERATED by scripts/brand/build-avatar-doodles.mjs - do not edit by hand.
     Source drawing: scripts/brand/avatar-doodles.mjs

     The doodle set a registered player may wear instead of an initial
     (R-AVA-06). Each is a filled outline swept along an authored centreline,
     the way the logo and the 404 drawing are drawn, and painted with
     currentColor so the disc's ink paints it whatever the theme.

     The paint is a presentation attribute and not a stylesheet, because a
     stylesheet does not follow a symbol through an external <use>.

     Every viewBox is a square on that doodle's own drawn extent, so each one
     fills the same share of the disc. The smallest disc is 19 pixels across,
     which is why these are a handful of strokes each.

     The server's list of ids lives in backend/app/auth/avatar_doodles.py and
     the client's in frontend/src/lib/avatarDoodles.ts; tests hold the three
     together. -->`;

mkdirSync(dirname(OUT), { recursive: true });
writeFileSync(OUT, `<svg xmlns="http://www.w3.org/2000/svg">\n${header}\n${symbols.join("\n")}\n</svg>\n`, "utf8");

process.stdout.write(`doodles.svg: ${DOODLES.length} symbols, ${(Buffer.byteLength(
  `${symbols.join("\n")}`,
) / 1024).toFixed(1)} KiB of path data\n`);
