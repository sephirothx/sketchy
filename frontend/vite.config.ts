import { execSync } from 'node:child_process'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Best-effort short commit SHA + commit date, embedded at build time so the
// running build can display exactly what it was built from. Falls back to
// "unknown" if git isn't available (e.g. a source archive without a .git
// directory) so a missing git binary never breaks the build.
function gitLog(args: string): string {
  try {
    return execSync(`git log -1 ${args}`, { encoding: 'utf-8' }).trim()
  } catch {
    return 'unknown'
  }
}

// True if the working tree has uncommitted changes at build time, so a dev
// build made on top of local edits doesn't silently claim to be a commit it
// isn't. Defaults to false (rather than throwing) if git isn't available.
function isWorkingTreeDirty(): boolean {
  try {
    return execSync('git status --porcelain', { encoding: 'utf-8' }).trim().length > 0
  } catch {
    return false
  }
}

function getLocalBuildTime(): string {
  const now = new Date()
  const year = now.getFullYear()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  const hours = String(now.getHours()).padStart(2, '0')
  const minutes = String(now.getMinutes()).padStart(2, '0')
  const seconds = String(now.getSeconds()).padStart(2, '0')
  return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`
}

const buildTime = getLocalBuildTime()

// The API and Socket.IO endpoints are same-origin in every real deployment:
// the backend serves the built frontend itself (see SPAStaticFiles in
// backend/app/main.py). The Vite dev server on :5173 is the one exception, so
// it proxies those two prefixes to the backend to keep the frontend's URLs
// relative everywhere - which is what lets the session cookie work unchanged in
// dev, under scripts/serve.sh, in E2E, and through a tunnel.
const DEV_BACKEND = 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: DEV_BACKEND, changeOrigin: true },
      '/socket.io': { target: DEV_BACKEND, changeOrigin: true, ws: true },
    },
  },
  define: {
    __APP_COMMIT_SHA__: JSON.stringify(gitLog('--format=%h') + (isWorkingTreeDirty() ? '*' : '')),
    __APP_COMMIT_DATE__: JSON.stringify(gitLog('--date=short --format=%cd')),
    __APP_BUILD_TIME__: JSON.stringify(buildTime),
  },
})
