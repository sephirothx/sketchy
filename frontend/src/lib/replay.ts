import type { DecodedCanvasAction } from "./canvasHistory";
import { shapeOutlinePoints } from "./canvasGeometry.ts";
import type { Point } from "./canvasGeometry.ts";

/** How long a replay takes, whatever the drawing: a doodle is not over in a
 * blink and a dense one does not drag. */
export const REPLAY_MIN_SECONDS = 2.5;
export const REPLAY_MAX_SECONDS = 9;
/** What a dot, a fill or a clear costs, measured in stroke segments: the
 * window of time it takes on the bar before it lands. */
export const REPLAY_STEP_COST = 12;

export interface ReplayPosition {
  action: number;
  /** Along a stroke: a position in segments, fractional between two points. */
  point: number;
}

export interface ReplayPlan {
  /** The whole drawing, in stroke segments (steps cost `stepCost` each). */
  total: number;
  pointsPerSecond: number;
  stepCost: number;
  seconds: number;
  /** How far along the replay is, 0..1, at the given action and point. */
  fractionAt(action: number, point: number): number;
  /** The position a fraction of the way through: what a scrub lands on. */
  positionAt(fraction: number): ReplayPosition;
}

/**
 * A stroke, as the replay draws it: the points it grows through, closed
 * for a shape's outline. Null for what lands whole - a dot, a fill, a clear.
 */
export function replayStroke(
  action: DecodedCanvasAction,
): { points: Point[]; width: number; color: string } | null {
  if (action.kind === "path" && action.points.length > 1) {
    return { points: action.points, width: action.width, color: action.color };
  }
  if (action.kind === "shape") {
    const outline = shapeOutlinePoints(action.payload.from, action.payload.to, action.payload.shape);
    if (outline.length < 2) return null;
    return { points: [...outline, outline[0]], width: action.payload.width, color: action.payload.color };
  }
  return null;
}

function cost(action: DecodedCanvasAction): number {
  // A stroke is measured in segments, which is what the replay draws
  // through; anything that lands whole takes a fixed window of time.
  const stroke = replayStroke(action);
  return stroke ? stroke.points.length - 1 : REPLAY_STEP_COST;
}

/**
 * The pace a replay runs at: the drawing's points spread over a duration
 * that grows with its size between a floor and a ceiling, so every drawing
 * plays for a few seconds and a stroke's speed is proportional to its
 * length. Pure, so the suite can hold it to its edges.
 */
export function replayPlan(actions: readonly DecodedCanvasAction[]): ReplayPlan {
  const costs = actions.map(cost);
  const total = costs.reduce((sum, value) => sum + value, 0);
  const seconds = Math.min(REPLAY_MAX_SECONDS, Math.max(REPLAY_MIN_SECONDS, total / 220));
  const pointsPerSecond = Math.max(1, total / seconds);
  const before: number[] = [];
  let running = 0;
  for (const value of costs) {
    before.push(running);
    running += value;
  }
  return {
    total,
    pointsPerSecond,
    stepCost: REPLAY_STEP_COST,
    seconds,
    fractionAt(action, point) {
      if (total === 0 || action >= actions.length) return 1;
      return Math.min(1, (before[action] + Math.min(point, costs[action])) / total);
    },
    positionAt(fraction) {
      const target = Math.min(1, Math.max(0, fraction)) * total;
      if (total === 0 || target >= total) return { action: actions.length, point: 0 };
      let index = 0;
      while (index < actions.length - 1 && before[index + 1] <= target) index += 1;
      // Part way through the action's window: along a stroke, or waiting
      // for something that lands whole at the window's end.
      return { action: index, point: Math.min(costs[index], target - before[index]) };
    },
  };
}

export interface ReplayPainter {
  /** Draw the stretch `from..to` (in segments) of a stroke. */
  span(stroke: { points: Point[]; width: number; color: string }, from: number, to: number): void;
  /** Apply a whole action: a dot, a fill, a clear. */
  whole(action: DecodedCanvasAction): void;
}

/**
 * Advance a replay by `budget` segments, painting what that uncovers, and
 * return the new position with what is left of the budget. Every action
 * takes a window of the bar: a stroke or a shape's outline grows through
 * its window part of a segment at a time, and a dot, a fill or a clear
 * lands whole when its window is spent - so the bar moves at one pace
 * whatever is being drawn, which is what makes it read as time. Pure apart
 * from the painter, so the suite can drive it frame by frame.
 */
export function stepReplay(
  actions: readonly DecodedCanvasAction[],
  plan: ReplayPlan,
  position: ReplayPosition,
  budget: number,
  painter: ReplayPainter,
): { position: ReplayPosition; left: number } {
  let { action: index, point } = position;
  let left = budget;
  while (left > 0 && index < actions.length) {
    const action = actions[index];
    const stroke = replayStroke(action);
    const end = stroke ? stroke.points.length - 1 : plan.stepCost;
    const to = Math.min(end, point + left);
    // A remainder too small to move the position - floating-point dust
    // left by the subtraction below - would otherwise loop forever. It is
    // spent, not owed: the frame ends here and the next one carries on.
    if (to - point < 1e-6) {
      if (end - point < 1e-6) {
        // Dust short of the end is the end: finish the action rather than
        // sit a hair's breadth before it forever.
        if (!stroke) painter.whole(action);
        index += 1;
        point = 0;
        continue;
      }
      left = 0;
      break;
    }
    if (stroke) painter.span(stroke, point, to);
    left -= to - point;
    point = to;
    if (point >= end) {
      if (!stroke) painter.whole(action);
      index += 1;
      point = 0;
    }
  }
  return { position: { action: index, point }, left: index < actions.length ? left : 0 };
}
