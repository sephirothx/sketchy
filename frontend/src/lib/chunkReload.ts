/** A chunk this tab asked for is gone: reload onto the build being served, once.

Pages, overlays and every language but English are chunks fetched on demand
(#475, #982). A deploy replaces them - their names carry a content hash - so a
tab opened before it asks for files the server no longer has, and the fetch
fails. The shell is served `no-cache`, so a reload lands on the new build and
the chunk it names.

A failed fetch does not say why it failed, and the other reasons are a server
that is unreachable (a restart, a network drop - a reload there lands on the
browser's own error page) or a request that simply failed once (a reload
there throws away the page for nothing, and the client error log a crash
report would read). So the chunk is asked for again, and the page reloads
only when the server answers that it is not there: a 404. Where the browser's
error does not name the chunk (Safari's), a server that answers at all is
the best evidence there is. And once per
build, remembered in session storage, for the reason `protocol.ts` gives for
its own reload-once: a reload that does not fix it would otherwise spin
forever. Whatever the outcome, the failure still surfaces where it happened -
a page's crash screen, English in place of a language - until the reload
replaces it. */

const MARKER_KEY = "sketchy:chunk-reload";

export interface ChunkReloadEnvironment {
  build: string;
  storage?: Pick<Storage, "getItem" | "setItem"> | null;
  /** Whether the chunk that failed is gone from the server (a 404). */
  chunkIsGone: () => Promise<boolean>;
  reload: () => void;
}

/** Settles with whether a failed chunk fetch was answered with a reload. */
export async function reloadForMissingChunk(environment: ChunkReloadEnvironment): Promise<boolean> {
  try {
    if (environment.storage?.getItem(MARKER_KEY) === environment.build) return false;
  } catch {
    // Without storage this load cannot tell whether it already tried, and a
    // reload loop is the one outcome worse than the crash page.
    return false;
  }
  if (!(await environment.chunkIsGone())) return false;
  try {
    environment.storage?.setItem(MARKER_KEY, environment.build);
  } catch {
    return false;
  }
  environment.reload();
  return true;
}

/** The chunk URL a failed dynamic import names, where the browser says. */
export function failedChunkUrl(error: unknown): string | null {
  const message = error instanceof Error ? error.message : String(error ?? "");
  return message.match(/https?:\/\/\S+?\.(?:js|css)\b/)?.[0] ?? null;
}

/** Answer Vite's report of a failed dynamic import, for the whole app. */
export function installChunkReload(): void {
  if (typeof window === "undefined") return;
  window.addEventListener("vite:preloadError", (event) => {
    const url = failedChunkUrl((event as Event & { payload?: unknown }).payload);
    void reloadForMissingChunk({
      build: `${__APP_COMMIT_SHA__} ${__APP_BUILD_TIME__}`,
      storage: sessionStorage,
      chunkIsGone: () =>
        fetch(url ?? "/", { method: "HEAD", cache: "no-store" }).then(
          (response) => (url ? response.status === 404 : response.ok),
          () => false,
        ),
      reload: () => window.location.reload(),
    });
  });
}
