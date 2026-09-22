/** A chunk this tab asked for is gone: reload onto the build being served, once.

Pages, overlays and every language but English are chunks fetched on demand
(#475, #982). A deploy replaces them - their names carry a content hash - so a
tab opened before it asks for files the server no longer has, and the fetch
fails. The shell is served `no-cache`, so a reload lands on the new build and
the chunk it names.

A failed fetch does not say why it failed, and the other reason is that the
server is unreachable - a restart, a network drop - where a reload lands on
the browser's own error page, which is worse than what the app shows. So the
server is asked first, and the page reloads only if it answers. And once per
build, remembered in session storage, for the reason `protocol.ts` gives for
its own reload-once: a reload that does not fix it would otherwise spin
forever. Whatever the outcome, the failure still surfaces where it happened -
a page's crash screen, English in place of a language - until the reload
replaces it. */

const MARKER_KEY = "sketchy:chunk-reload";

export interface ChunkReloadEnvironment {
  build: string;
  storage?: Pick<Storage, "getItem" | "setItem"> | null;
  /** Whether the server answers at all right now. */
  serverAnswers: () => Promise<boolean>;
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
  if (!(await environment.serverAnswers())) return false;
  try {
    environment.storage?.setItem(MARKER_KEY, environment.build);
  } catch {
    return false;
  }
  environment.reload();
  return true;
}

/** Answer Vite's report of a failed dynamic import, for the whole app. */
export function installChunkReload(): void {
  if (typeof window === "undefined") return;
  window.addEventListener("vite:preloadError", () => {
    void reloadForMissingChunk({
      build: `${__APP_COMMIT_SHA__} ${__APP_BUILD_TIME__}`,
      storage: sessionStorage,
      serverAnswers: () =>
        fetch("/", { method: "HEAD", cache: "no-store" }).then(
          (response) => response.ok,
          () => false,
        ),
      reload: () => window.location.reload(),
    });
  });
}
