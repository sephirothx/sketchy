/** Where thumbnails are drawn: one worker, one job at a time (#1282).

A thumbnail's replay is synchronous and its cost is whatever the history
makes the renderer do - an accepted turn of 100 full-canvas fills froze the
page for 1.18 s, and a gallery page could hold several. So thumbnails are
drawn on a worker (`workers/thumbnail.worker.ts`), and the page only asks
and waits.

Bounded three ways. One worker, sent one job at a time, so at most one
history, one full-size buffer and one scaled copy exist off the page, and
the worker is let go once the queue has been idle a while. At most
`MAX_PENDING_THUMBNAILS` jobs wait: past that the oldest is dropped with
`ThumbnailDropped`, and its card asks again when it next comes into view.
And a job whose card went, or whose drawing changed, is cancelled: taken
out of the queue if it is still waiting, its answer thrown away if it is
not - a worker cannot be interrupted mid-replay, but nothing waits on it.

Where no worker can be had - none in this environment, or one that failed
to start or died - the same `renderThumbnail` runs on the page, one at a
time as before: the same image, at the old price. */

import type { ThumbnailAnswer, ThumbnailJob } from "../workers/thumbnail.worker.ts";
import { renderThumbnail, type ThumbnailImage } from "./thumbnailRender.ts";

export const MAX_PENDING_THUMBNAILS = 48;
/** How long an idle worker is kept, with its full-size buffer, for the next
    card a scroll brings in. */
export const IDLE_WORKER_MS = 20_000;

/** The job waited past `MAX_PENDING_THUMBNAILS` newer ones and was dropped. */
export class ThumbnailDropped extends Error {}

/** The caller no longer wants the job: its card went or its drawing changed. */
export class ThumbnailCancelled extends Error {}

export interface ThumbnailWorker {
  postMessage(message: ThumbnailJob, transfer: Transferable[]): void;
  onmessage: ((event: MessageEvent<ThumbnailAnswer>) => void) | null;
  onerror: ((event: ErrorEvent) => void) | null;
  terminate(): void;
}

interface Job {
  id: number;
  bytes: ArrayBuffer;
  pixelWidth: number;
  resolve: (image: ThumbnailImage | null) => void;
  reject: (error: Error) => void;
  cancelled: boolean;
  forget: () => void;
}

export interface ThumbnailQueueOptions {
  /** Starts the worker; absent, or throwing, means drawing on the page. */
  createWorker?: () => ThumbnailWorker;
  renderOnPage?: (bytes: ArrayBuffer, pixelWidth: number) => Promise<ThumbnailImage | null>;
  maxPending?: number;
  idleMs?: number;
}

export interface ThumbnailQueue {
  /** `bytes` drawn `pixelWidth` device pixels wide; null for a history that
      does not decode. `bytes` is copied, never transferred away. */
  draw(bytes: ArrayBuffer, pixelWidth: number, signal?: AbortSignal): Promise<ThumbnailImage | null>;
  /** Jobs waiting, and whether one is being drawn: for tests and benchmarks. */
  load(): { pending: number; running: boolean; worker: boolean };
}

export function createThumbnailQueue({
  createWorker,
  renderOnPage = renderThumbnail,
  maxPending = MAX_PENDING_THUMBNAILS,
  idleMs = IDLE_WORKER_MS,
}: ThumbnailQueueOptions = {}): ThumbnailQueue {
  // undefined: not started yet; null: none to be had, draw on the page.
  let worker: ThumbnailWorker | null | undefined;
  let idle: ReturnType<typeof setTimeout> | null = null;
  const pending: Job[] = [];
  let running: Job | null = null;
  let nextId = 1;

  function obtainWorker(): ThumbnailWorker | null {
    if (worker !== undefined) return worker;
    try {
      worker = createWorker ? createWorker() : null;
    } catch {
      worker = null;
    }
    if (worker) {
      const own = worker;
      own.onmessage = (event) => {
        const job = running;
        if (!job || event.data.id !== job.id) return;
        const answer = event.data;
        settle(job, answer.png === null
          ? null
          : { png: new Uint8Array(answer.png), width: answer.width, height: answer.height });
      };
      own.onerror = () => {
        // A worker that died - a chunk that would not load, an exception
        // outside a job - is not asked again: the job it held, and every
        // later one, is drawn on the page instead.
        own.terminate();
        worker = null;
        const job = running;
        if (job) runOnPage(job);
      };
    }
    return worker;
  }

  function settle(job: Job, image: ThumbnailImage | null): void {
    if (running === job) running = null;
    job.forget();
    if (job.cancelled) job.reject(new ThumbnailCancelled());
    else job.resolve(image);
    pump();
  }

  function runOnPage(job: Job): void {
    renderOnPage(job.bytes, job.pixelWidth).then(
      (image) => settle(job, image),
      () => settle(job, null),
    );
  }

  function pump(): void {
    if (running) return;
    const job = pending.shift();
    if (!job) {
      scheduleIdle();
      return;
    }
    if (idle !== null) {
      clearTimeout(idle);
      idle = null;
    }
    running = job;
    const own = obtainWorker();
    if (!own) {
      runOnPage(job);
      return;
    }
    const bytes = job.bytes;
    // The worker's copy, transferred: the job keeps nothing it would need
    // were the worker to die, since the page path reads `job.bytes`.
    const copy = bytes.slice(0);
    own.postMessage({ id: job.id, bytes: copy, pixelWidth: job.pixelWidth }, [copy]);
  }

  function scheduleIdle(): void {
    if (idle !== null || !worker || idleMs <= 0) return;
    idle = setTimeout(() => {
      idle = null;
      if (running || pending.length || !worker) return;
      worker.terminate();
      worker = undefined;
    }, idleMs);
  }

  return {
    draw(bytes, pixelWidth, signal) {
      return new Promise((resolve, reject) => {
        if (signal?.aborted) {
          reject(new ThumbnailCancelled());
          return;
        }
        const job: Job = {
          id: nextId++,
          bytes: bytes.slice(0),
          pixelWidth,
          resolve,
          reject,
          cancelled: false,
          forget: () => undefined,
        };
        if (signal) {
          const onAbort = () => {
            job.cancelled = true;
            const index = pending.indexOf(job);
            if (index >= 0) {
              pending.splice(index, 1);
              job.forget();
              reject(new ThumbnailCancelled());
            }
          };
          signal.addEventListener("abort", onAbort, { once: true });
          job.forget = () => signal.removeEventListener("abort", onAbort);
        }
        pending.push(job);
        while (pending.length > maxPending) {
          const dropped = pending.shift()!;
          dropped.forget();
          dropped.reject(new ThumbnailDropped());
        }
        pump();
      });
    },
    load() {
      return { pending: pending.length, running: running !== null, worker: Boolean(worker) };
    },
  };
}

const pageQueue = createThumbnailQueue({
  createWorker: typeof Worker === "undefined"
    ? undefined
    : () => new Worker(new URL("../workers/thumbnail.worker.ts", import.meta.url), { type: "module" }) as ThumbnailWorker,
});

/** Draw a thumbnail on the page's one thumbnail worker. */
export function drawThumbnail(
  bytes: ArrayBuffer,
  pixelWidth: number,
  signal?: AbortSignal,
): Promise<ThumbnailImage | null> {
  return pageQueue.draw(bytes, pixelWidth, signal);
}
