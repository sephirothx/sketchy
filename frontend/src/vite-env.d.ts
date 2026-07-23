/// <reference types="vite/client" />

// Injected at build time by vite.config.ts's `define` from the current git
// commit - see VersionBadge.tsx for where these are displayed.
declare const __APP_COMMIT_SHA__: string;
declare const __APP_COMMIT_DATE__: string;
