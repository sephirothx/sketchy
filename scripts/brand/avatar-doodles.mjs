// The doodle set a registered player may wear instead of an initial
// (R-AVA-06). This file is the drawing; scripts/brand/build-avatar-doodles.mjs
// is the pen that inks it into frontend/public/avatars/doodles.svg.
//
// A doodle is written as the few places its line goes, on the same 24x24 grid
// the UI icons use. Everything that makes it look drawn rather than plotted -
// the wobble, the pressure, the round tips, the lap where a closed line passes
// its own start - comes from the brush, so a doodle here only has to be the
// right SHAPE.
//
// Two things decide whether a shape works, and both are about size:
//
//   - The smallest disc a player list draws is 19 pixels across, and a doodle
//     fills 80% of it. That is fifteen pixels for the whole animal, so a
//     doodle is a handful of strokes and never a detailed one. Anything that
//     reads only at 52px - a nostril, a third shell line - is noise at 19.
//   - Silhouettes have to differ, not just details. Four round animal heads
//     with different ears are one doodle at 19 pixels, which is why the fox is
//     angular and pointed where the bear is circular, and why the owl, penguin
//     and turtle are whole bodies rather than more heads.
//
// The ids are the wire's, not just this file's: they are what `doodle:<name>`
// stores, and the server's list in backend/app/auth/avatar_doodles.py and the
// client's in frontend/src/lib/avatarDoodles.ts have to name the same set in
// the same order. A test holds the three together. Changing an id is changing
// what every account wearing it points at, so add rather than rename.
//
// What a doodle is CALLED to a player lives with the client's list, not here:
// a name a screen reader reads out belongs beside the rest of the UI copy,
// and one list of labels is one list to keep in step.

/** Marks an authored point as a corner: the line turns there instead of curving. */
export const SHARP = true;

const TAU = Math.PI * 2;

/** `n` points round an ellipse, optionally rotated, ready to be splined. */
export function oval(cx, cy, rx, ry, rotation = 0, n = 10) {
  const radians = (rotation * Math.PI) / 180;
  const cos = Math.cos(radians);
  const sin = Math.sin(radians);
  const out = [];
  for (let i = 0; i < n; i++) {
    const a = (i / n) * TAU;
    const x = Math.cos(a) * rx;
    const y = Math.sin(a) * ry;
    out.push([cx + x * cos - y * sin, cy + x * sin + y * cos]);
  }
  return out;
}

export function disc(cx, cy, r, n = 10) {
  return oval(cx, cy, r, r, 0, n);
}

/** A five-pointed star, every vertex a corner so the points stay points. */
export function star(cx, cy, outer, inner, points = 5) {
  const out = [];
  for (let i = 0; i < points * 2; i++) {
    const a = (i / (points * 2)) * TAU - Math.PI / 2;
    const r = i % 2 === 0 ? outer : inner;
    out.push([cx + Math.cos(a) * r, cy + Math.sin(a) * r, SHARP]);
  }
  return out;
}

/** An Archimedean spiral from `from` out to `to`, for the snail's shell. */
export function spiral(cx, cy, from, to, turns, n = 40) {
  const out = [];
  for (let i = 0; i <= n; i++) {
    const t = i / n;
    const a = t * turns * TAU - Math.PI / 2;
    const r = from + (to - from) * t;
    out.push([cx + Math.cos(a) * r, cy + Math.sin(a) * r]);
  }
  return out;
}

/**
 * Each doodle: `strokes` are centrelines the brush sweeps, `dots` are pen
 * presses (cx, cy, radius). A stroke's `w` is its width on the 24 grid;
 * `closed` takes the line round and past its own start; `over` runs an open
 * line past where it was going, the way a hand does not stop on the mark.
 */
export const DOODLES = [
  {
    id: "fox",
    // Angular and pointed everywhere the bear and the dog are round: big
    // upright ears, a narrow snout, a chin that comes to a point. The outline
    // turns at the temple before it climbs to each ear tip - without that
    // corner the ear and the cheek are one edge, and the whole head reads as
    // a shield.
    strokes: [
      {
        closed: true,
        w: 2,
        p: [
          [5.2, 11.8, SHARP],
          [3.6, 4.6, SHARP],
          [8.2, 8.8],
          [12, 7.6],
          [15.8, 8.8],
          [20.4, 4.6, SHARP],
          [18.8, 11.8, SHARP],
          [15.0, 16.8],
          [12.6, 20.2],
          [12, 21.2, SHARP],
          [11.4, 20.2],
          [9.0, 16.8],
        ],
      },
    ],
    dots: [
      [9.4, 12.8, 0.8],
      [14.6, 12.8, 0.8],
      [12, 18.4, 0.9],
    ],
  },
  {
    id: "cat",
    // Rounder than the fox, and the whiskers are what carry it at 19 pixels:
    // nothing else in the set has a line leaving the silhouette sideways.
    strokes: [
      {
        closed: true,
        w: 2,
        p: [
          [5.2, 4.2, SHARP],
          [8.4, 8.8],
          [12, 7.8],
          [15.6, 8.8],
          [18.8, 4.2, SHARP],
          [18.6, 12.6],
          [16.2, 18.6],
          [12, 20.2],
          [7.8, 18.6],
          [5.4, 12.6],
        ],
      },
      { w: 1.2, over: 0.2, p: [[8.4, 15.4], [5.6, 14.4], [4.2, 14.0]] },
      { w: 1.2, over: 0.2, p: [[8.4, 16.8], [5.6, 17.4], [4.4, 18.4]] },
      { w: 1.2, over: 0.2, p: [[15.6, 15.4], [18.4, 14.4], [19.8, 14.0]] },
      { w: 1.2, over: 0.2, p: [[15.6, 16.8], [18.4, 17.4], [19.6, 18.4]] },
    ],
    dots: [
      [9.5, 12.8, 0.85],
      [14.5, 12.8, 0.85],
      [12, 15.6, 0.6],
    ],
  },
  {
    id: "ghost",
    // The hem is the whole doodle: a dome with a straight bottom is a
    // tombstone, and the spikes survive being three pixels tall.
    strokes: [
      {
        closed: true,
        w: 2,
        p: [
          [5.0, 18.0],
          [5.0, 11.2],
          [6.8, 6.6],
          [12, 4.2],
          [17.2, 6.6],
          [19.0, 11.2],
          [19.0, 20.4, SHARP],
          [17.0, 17.8, SHARP],
          [15.0, 20.4, SHARP],
          [13.0, 17.8, SHARP],
          [11.0, 20.4, SHARP],
          [9.0, 17.8, SHARP],
          [7.0, 20.4, SHARP],
        ],
      },
      { closed: true, w: 1.2, lap: 1.4, p: disc(12, 14.4, 1.1, 8) },
    ],
    dots: [
      [9.6, 10.6, 1.1],
      [14.4, 10.6, 1.1],
    ],
  },
  {
    id: "dog",
    // The ears are lobes of the head outline, not two shapes laid over it:
    // separate ovals either float beside the head or crowd into it, and both
    // read as some other animal.
    strokes: [
      {
        closed: true,
        w: 2,
        p: [
          [8.0, 8.6],
          [12, 7.0],
          [16.0, 8.6],
          [17.6, 11.0],
          [19.8, 13.4],
          [19.2, 18.0, SHARP],
          [16.8, 16.4],
          [15.4, 18.6],
          [12, 19.9],
          [8.6, 18.6],
          [7.2, 16.4],
          [4.8, 18.0, SHARP],
          [4.2, 13.4],
          [6.4, 11.0],
        ],
      },
      { w: 1.3, p: [[10.2, 17.0], [12, 18.0], [13.8, 17.0]] },
    ],
    dots: [
      [9.8, 12.6, 0.85],
      [14.2, 12.6, 0.85],
      [12, 15.4, 1.0],
    ],
  },
  {
    id: "owl",
    // A whole bird, not another head: the two rings around the eyes are the
    // one thing in the set that reads as a face at any size.
    strokes: [
      {
        closed: true,
        w: 2,
        p: [
          [5.6, 4.4, SHARP],
          [8.6, 8.4],
          [15.4, 8.4],
          [18.4, 4.4, SHARP],
          [18.8, 13.4],
          [16.6, 19.4],
          [12, 21.0],
          [7.4, 19.4],
          [5.2, 13.4],
        ],
      },
      { closed: true, w: 1.4, lap: 1.6, p: disc(9.2, 12.4, 2.3) },
      { closed: true, w: 1.4, lap: 1.6, p: disc(14.8, 12.4, 2.3) },
      { w: 1.6, p: [[10.8, 15.4], [12, 17.2, SHARP], [13.2, 15.4]] },
    ],
    dots: [
      [9.2, 12.4, 0.9],
      [14.8, 12.4, 0.9],
    ],
  },
  {
    id: "bear",
    // Circles all the way down, which is exactly what makes it not the dog.
    strokes: [
      { closed: true, w: 2, p: disc(12, 13.6, 6.2) },
      { closed: true, w: 1.7, lap: 1.6, p: disc(6.6, 7.4, 2.2) },
      { closed: true, w: 1.7, lap: 1.6, p: disc(17.4, 7.4, 2.2) },
      { closed: true, w: 1.5, lap: 1.6, p: oval(12, 16.6, 2.9, 2.1) },
    ],
    dots: [
      [9.6, 12.2, 0.8],
      [14.4, 12.2, 0.8],
      [12, 15.5, 0.9],
    ],
  },
  {
    id: "frog",
    // Eyes on top of the head and a mouth wider than the face: the two things
    // no other animal here does.
    strokes: [
      {
        closed: true,
        w: 2,
        p: [
          [4.0, 13.0],
          [4.4, 10.0],
          [7.0, 8.6],
          [12, 8.2],
          [17.0, 8.6],
          [19.6, 10.0],
          [20.0, 13.0],
          [17.4, 17.6],
          [12, 19.2],
          [6.6, 17.6],
        ],
      },
      { closed: true, w: 1.5, lap: 1.6, p: disc(7.4, 7.4, 2.2) },
      { closed: true, w: 1.5, lap: 1.6, p: disc(16.6, 7.4, 2.2) },
      { w: 1.5, p: [[6.6, 13.2], [12, 15.8], [17.4, 13.2]] },
    ],
    dots: [
      [7.4, 7.4, 0.85],
      [16.6, 7.4, 0.85],
    ],
  },
  {
    id: "rabbit",
    strokes: [
      { closed: true, w: 2, p: oval(12, 15.4, 5.2, 4.7) },
      { closed: true, w: 1.7, p: oval(9.5, 6.6, 1.8, 4.8, -10) },
      { closed: true, w: 1.7, p: oval(14.5, 6.6, 1.8, 4.8, 10) },
      { w: 1.2, p: [[10.6, 19.0], [12, 18.0], [13.4, 19.0]] },
    ],
    dots: [
      [9.9, 14.6, 0.8],
      [14.1, 14.6, 0.8],
      [12, 17.0, 0.7],
    ],
  },
  {
    id: "penguin",
    // A head that is its own circle on top of the body. A single upright oval
    // with a face drawn on it is an egg however it is marked, and a bib big
    // enough to see at 19 pixels swallowed the face whole.
    strokes: [
      { closed: true, w: 2, p: oval(12, 15.6, 5.4, 6.2) },
      { closed: true, w: 2, p: disc(12, 7.6, 4.0) },
      { closed: true, w: 1.3, lap: 1.4, p: [[14.6, 7.4, SHARP], [17.8, 8.6, SHARP], [14.4, 9.6, SHARP]] },
      { w: 1.6, p: [[6.9, 13.6], [5.0, 16.6], [6.6, 19.4]] },
      { w: 1.6, p: [[17.1, 13.6], [19.0, 16.6], [17.4, 19.4]] },
      { w: 1.5, over: 0.2, p: [[10.4, 21.4], [8.8, 22.4]] },
      { w: 1.5, over: 0.2, p: [[13.6, 21.4], [15.2, 22.4]] },
    ],
    dots: [
      [10.6, 6.6, 0.75],
      [13.4, 6.6, 0.75],
    ],
  },
  {
    id: "whale",
    // Fat, and with the tail turned UP. Both are the difference from a fish:
    // a streamlined body and a tail standing on end is what a fish is, and
    // the set has no room for one of each. The spout is two lines splayed
    // wide, because three upright ones are a mohawk.
    strokes: [
      {
        closed: true,
        w: 2,
        p: [
          [2.6, 13.4],
          [3.6, 9.6],
          [7.6, 7.0],
          [12.6, 6.8],
          [16.6, 8.6],
          [18.6, 11.4],
          [20.2, 7.6],
          [22.6, 9.2, SHARP],
          [19.8, 13.6],
          [18.2, 15.2],
          [14.0, 18.4],
          [8.0, 19.0],
          [3.8, 16.8],
        ],
      },
      { w: 1.5, over: 0.2, p: [[9.0, 6.8], [6.2, 2.8]] },
      { w: 1.5, over: 0.2, p: [[9.0, 6.8], [11.8, 3.0]] },
      { w: 1.3, p: [[3.0, 14.2], [5.2, 15.6], [7.6, 14.4]] },
    ],
    dots: [[5.8, 11.2, 0.8]],
  },
  {
    id: "bee",
    strokes: [
      { closed: true, w: 2, p: oval(11.6, 14.8, 5.4, 4.2) },
      { w: 1.5, p: [[9.7, 10.9], [9.2, 18.6]] },
      { w: 1.5, p: [[13.3, 10.8], [13.8, 18.6]] },
      { closed: true, w: 1.4, lap: 1.6, p: oval(9.2, 7.6, 2.7, 1.9, -28) },
      { closed: true, w: 1.4, lap: 1.6, p: oval(14.6, 7.4, 2.7, 1.9, 26) },
      { w: 1.3, over: 0.2, p: [[16.9, 15.4], [19.8, 16.4]] },
    ],
    dots: [[7.6, 13.4, 0.8]],
  },
  {
    id: "snail",
    // The spiral is the doodle. Everything else is the least body that can
    // carry one.
    strokes: [
      { w: 2.2, p: [[20.4, 19.4], [8.0, 19.6], [3.4, 18.8], [2.4, 14.6], [3.4, 11.4], [5.4, 9.8]] },
      { w: 1.7, p: spiral(13.8, 12.0, 0.9, 5.2, 2.1) },
      { w: 1.2, over: 0.2, p: [[5.4, 9.8], [4.0, 6.4]] },
      { w: 1.2, over: 0.2, p: [[5.6, 9.8], [7.8, 6.8]] },
    ],
    dots: [
      [3.8, 5.8, 0.75],
      [8.1, 6.2, 0.75],
    ],
  },
  {
    id: "turtle",
    strokes: [
      {
        closed: true,
        w: 2,
        p: [
          [4.6, 15.2],
          [5.4, 10.8],
          [8.6, 8.2],
          [12, 7.6],
          [15.4, 8.2],
          [18.6, 10.8],
          [19.4, 15.2],
          [15.6, 16.4],
          [12, 16.6],
          [8.4, 16.4],
        ],
      },
      { w: 1.2, p: [[6.4, 12.6], [12, 11.6], [17.6, 12.6]] },
      { w: 1.2, p: [[12, 8.0], [12, 16.5]] },
      { closed: true, w: 1.7, lap: 1.6, p: disc(20.8, 12.6, 1.9) },
      { w: 1.8, over: 0.2, p: [[8.0, 16.2], [7.0, 19.2]] },
      { w: 1.8, over: 0.2, p: [[16.0, 16.2], [17.0, 19.2]] },
      { w: 1.2, over: 0.2, p: [[4.8, 14.8], [2.4, 16.4]] },
    ],
    dots: [[21.4, 12.1, 0.55]],
  },
  {
    id: "robot",
    strokes: [
      {
        closed: true,
        w: 2,
        p: [
          [6.0, 10.0],
          [8.0, 8.2],
          [16.0, 8.2],
          [18.0, 10.0],
          [18.0, 17.6],
          [16.0, 19.6],
          [8.0, 19.6],
          [6.0, 17.6],
        ],
      },
      { w: 1.5, p: [[12, 8.2], [12, 4.8]] },
      { w: 1.4, p: [[9.6, 16.4], [14.4, 16.4]] },
      { w: 1.5, over: 0.2, p: [[6.1, 12.8], [3.6, 12.8]] },
      { w: 1.5, over: 0.2, p: [[17.9, 12.8], [20.4, 12.8]] },
    ],
    dots: [
      [12, 3.9, 1.0],
      [9.5, 12.6, 1.15],
      [14.5, 12.6, 1.15],
    ],
  },
  {
    id: "alien",
    // The eyes are two fat strokes rather than outlines: a capsule with round
    // tips is the one shape here that stays solid black at 19 pixels.
    strokes: [
      {
        closed: true,
        w: 2,
        p: [
          [12, 3.0],
          [16.8, 4.8],
          [19.0, 9.4],
          [17.4, 15.4],
          [13.8, 20.0],
          [12, 21.4, SHARP],
          [10.2, 20.0],
          [6.6, 15.4],
          [5.0, 9.4],
          [7.2, 4.8],
        ],
      },
      { w: 3.2, head: 1, tail: 1, p: [[8.2, 9.4], [9.8, 13.6]] },
      { w: 3.2, head: 1, tail: 1, p: [[15.8, 9.4], [14.2, 13.6]] },
      { w: 1.3, p: [[10.6, 17.0], [13.4, 17.0]] },
    ],
  },
  {
    id: "mushroom",
    strokes: [
      {
        closed: true,
        w: 2,
        p: [
          [3.2, 12.4],
          [4.4, 7.6],
          [8.0, 4.8],
          [12, 4.2],
          [16.0, 4.8],
          [19.6, 7.6],
          [20.8, 12.4],
          [16.0, 13.4],
          [12, 13.6],
          [8.0, 13.4],
        ],
      },
      {
        closed: true,
        w: 1.7,
        p: [
          [9.6, 13.5],
          [9.0, 18.6],
          [10.2, 20.4],
          [12, 20.8],
          [13.8, 20.4],
          [15.0, 18.6],
          [14.4, 13.5],
        ],
      },
    ],
    dots: [
      [7.8, 9.4, 1.15],
      [12.6, 7.6, 1.15],
      [16.6, 10.2, 1.05],
    ],
  },
  {
    id: "cactus",
    strokes: [
      {
        closed: true,
        w: 2,
        p: [
          [9.4, 20.4],
          [9.4, 8.0],
          [10.4, 5.8],
          [12, 5.4],
          [13.6, 5.8],
          [14.6, 8.0],
          [14.6, 20.4],
          [12, 20.9],
        ],
      },
      { w: 2, p: [[9.5, 14.2], [6.6, 14.0], [6.2, 9.4]] },
      { w: 2, p: [[14.5, 11.6], [17.4, 11.4], [17.8, 7.2]] },
      { w: 1.3, over: 0.3, p: [[6.6, 21.4], [17.4, 21.4]] },
    ],
  },
  {
    id: "rocket",
    strokes: [
      {
        closed: true,
        w: 2,
        p: [
          [12, 2.6, SHARP],
          [15.4, 7.6],
          [16.4, 13.4],
          [15.6, 18.0],
          [8.4, 18.0],
          [7.6, 13.4],
          [8.6, 7.6],
        ],
      },
      { closed: true, w: 1.5, lap: 1.6, p: disc(12, 10.0, 2.1) },
      { closed: true, w: 1.5, lap: 1.6, p: [[8.5, 12.8, SHARP], [4.9, 17.8, SHARP], [8.4, 18.0, SHARP]] },
      { closed: true, w: 1.5, lap: 1.6, p: [[15.5, 12.8, SHARP], [19.1, 17.8, SHARP], [15.6, 18.0, SHARP]] },
      { closed: true, w: 1.4, lap: 1.4, p: [[9.6, 18.2], [10.8, 20.6], [12, 22.4, SHARP], [13.2, 20.6], [14.4, 18.2]] },
    ],
  },
  {
    id: "planet",
    strokes: [
      { closed: true, w: 2, p: disc(12, 12, 5.4) },
      { closed: true, w: 1.6, p: oval(12, 12, 9.4, 3.1, -18) },
    ],
    dots: [
      [10.0, 10.2, 0.85],
      [13.8, 13.6, 0.7],
    ],
  },
  {
    id: "star",
    strokes: [{ closed: true, w: 2, p: star(12, 12, 8.8, 3.9) }],
  },
  {
    id: "cloud",
    strokes: [
      {
        closed: true,
        w: 2,
        p: [
          [6.8, 18.0],
          [4.2, 16.2],
          [4.4, 12.8],
          [7.0, 11.0],
          [8.2, 7.6],
          [12, 6.0],
          [15.8, 7.4],
          [17.4, 10.4],
          [20.0, 12.0],
          [20.2, 15.6],
          [17.6, 18.0],
          [13.0, 18.4],
          [9.0, 18.4],
        ],
      },
    ],
  },
  {
    id: "icecream",
    strokes: [
      {
        closed: true,
        w: 1.9,
        p: [
          [7.0, 11.4],
          [6.2, 8.0],
          [8.4, 5.2],
          [12, 4.2],
          [15.6, 5.2],
          [17.8, 8.0],
          [17.0, 11.4],
        ],
      },
      { closed: true, w: 1.9, p: [[7.4, 11.8, SHARP], [16.6, 11.8, SHARP], [12, 21.6, SHARP]] },
      { w: 1.1, p: [[9.0, 14.4], [14.4, 13.0]] },
      { w: 1.1, p: [[10.2, 17.4], [13.6, 16.4]] },
    ],
    dots: [[12, 3.2, 1.0]],
  },
  {
    id: "pencil",
    // The game's own tool, laid across the disc so it is a diagonal in a set
    // of upright things.
    strokes: [
      {
        closed: true,
        w: 1.9,
        p: [
          [3.4, 20.8, SHARP],
          [5.03, 15.92, SHARP],
          [15.63, 5.32, SHARP],
          [18.89, 8.57, SHARP],
          [8.28, 19.17, SHARP],
        ],
      },
      { w: 1.3, p: [[5.03, 15.92], [8.28, 19.17]] },
      { w: 1.3, p: [[12.8, 8.14], [16.06, 11.4]] },
    ],
  },
  {
    id: "palette",
    // The other tool, and the only doodle with a hole in it - which costs
    // nothing, because a hole is just one more line.
    strokes: [
      {
        closed: true,
        w: 2,
        p: [
          [3.6, 12.2],
          [5.4, 7.2],
          [10.0, 4.6],
          [15.4, 5.0],
          [19.6, 8.0],
          [20.4, 12.6],
          [17.6, 17.0],
          [12.4, 19.6],
          [7.0, 18.6],
          [4.2, 15.6],
        ],
      },
      { closed: true, w: 1.3, lap: 1.4, p: disc(8.0, 15.8, 2.6, 8) },
    ],
    dots: [
      [7.8, 9.2, 1.1],
      [12.4, 7.4, 1.1],
      [16.6, 9.8, 1.1],
      [15.6, 14.6, 1.05],
    ],
  },
];
