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

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  define: {
    __APP_COMMIT_SHA__: JSON.stringify(gitLog('--format=%h') + (isWorkingTreeDirty() ? '*' : '')),
    __APP_COMMIT_DATE__: JSON.stringify(gitLog('--date=short --format=%cd')),
  },
})
