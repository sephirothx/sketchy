/// <reference types="vite/client" />

// Injected at build time by vite.config.ts's `define` from the current git
// commit. Nothing shows them to a player; a bug report carries them
// (lib/bugReports.ts), and so does a chunk-reload record (lib/chunkReload.ts).
declare const __APP_COMMIT_SHA__: string;
declare const __APP_COMMIT_DATE__: string;
declare const __APP_BUILD_TIME__: string;
