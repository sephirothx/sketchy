import { execSync } from 'node:child_process'
import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { brotliCompressSync, constants as zlibConstants, gzipSync } from 'node:zlib'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import type { Plugin } from 'vite'

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

// Text the server would otherwise gzip itself, for every client, on the loop
// every room shares (#978). Images and fonts are compressed formats already.
const PRECOMPRESS = /\.(?:js|css|html|svg|json|webmanifest|txt|map)$/
const PRECOMPRESS_MIN_BYTES = 1024

/** Write a Brotli and a gzip copy beside every text file the build emits, at
    the highest settings: paid once here instead of per request on the server,
    which serves whichever copy the client accepts (`backend/app/compression.py`). */
function precompress(): Plugin {
  let outDir = 'dist'
  return {
    name: 'sketchy-precompress',
    apply: 'build',
    configResolved(config) {
      outDir = config.build.outDir
    },
    closeBundle() {
      const walk = (dir: string): string[] =>
        readdirSync(dir, { withFileTypes: true }).flatMap((entry) =>
          entry.isDirectory() ? walk(join(dir, entry.name)) : [join(dir, entry.name)],
        )
      for (const file of walk(outDir)) {
        if (!PRECOMPRESS.test(file) || statSync(file).size < PRECOMPRESS_MIN_BYTES) continue
        const bytes = readFileSync(file)
        writeFileSync(`${file}.br`, brotliCompressSync(bytes, {
          params: {
            [zlibConstants.BROTLI_PARAM_QUALITY]: zlibConstants.BROTLI_MAX_QUALITY,
            [zlibConstants.BROTLI_PARAM_SIZE_HINT]: bytes.length,
          },
        }))
        writeFileSync(`${file}.gz`, gzipSync(bytes, { level: 9 }))
      }
    },
  }
}

/** The reader's language, and on an invite link the room's page, fetched from
    the page shell - before the entry has run (#1426).

Every language is a chunk of its own, English included, and the app asks for
the reader's from inside the entry: a French reader's first paint waited for
the entry and its static imports to download and run, then for French. And an
invite link (`/room/CODE`) asked for the room's page from inside the entry
too, while the lobby's play routes competed with it. This writes the chunk
lists into `index.html` and an inline script that chooses the language the
way the app does (`resolveLocale`: a public page's URL language (#1462), the
stored choice, then the browser's languages by base tag, then English) and appends `modulepreload` links for it
- and for the room's page and its imports on `/room/`.

Appended after Vite's own tags, so the entry and vendor are asked for first:
inserted before them, the room's preloads starved vendor and the paint came
later (2,680 ms, measured). Each language's list carries its static imports
(the shared format chunk among them, without which the gain disappeared),
less what the entry already preloads. The room's stylesheets are preloaded
too: Vite's own loader holds the page's import until they arrive, and asked
for from the entry they were one more round trip before the paint. With
`crossorigin`, as the loader's own links have it: a preload in another
credentials mode is not reused, and the file is fetched three times. The inline script's hash is read by
the server at startup for its CSP (`security_headers.inline_script_hashes`). */
function preloadReaderChunks(): Plugin {
  return {
    name: 'sketchy-preload-reader-chunks',
    apply: 'build',
    transformIndexHtml: {
      order: 'post',
      handler(html, ctx) {
        const bundle = ctx.bundle
        if (!bundle) return html
        const chunks = Object.values(bundle).filter((item) => item.type === 'chunk')
        const byFile = new Map(chunks.map((chunk) => [chunk.fileName, chunk]))
        const closure = (start: string[]): string[] => {
          const seen = new Set<string>()
          const queue = [...start]
          while (queue.length) {
            const file = queue.shift()!
            if (seen.has(file)) continue
            seen.add(file)
            queue.push(...(byFile.get(file)?.imports ?? []))
          }
          return [...seen]
        }
        const entry = chunks.find((chunk) => chunk.isEntry)
        const preloaded = new Set(entry ? closure([entry.fileName]) : [])
        const own = (start: string[]) => closure(start).filter((file) => !preloaded.has(file))
        const facade = (pattern: RegExp) =>
          chunks.find((chunk) => chunk.facadeModuleId && pattern.test(chunk.facadeModuleId))
        const locales: Record<string, string[]> = {}
        for (const chunk of chunks) {
          const match = chunk.facadeModuleId?.match(/[\\/]src[\\/]content[\\/]ui[\\/]([a-z]{2})\.ts$/)
          if (match) locales[match[1]] = own([chunk.fileName])
        }
        if (!locales.en) throw new Error('sketchy-preload-reader-chunks: no English catalogue chunk')
        const room = facade(/[\\/]src[\\/]pages[\\/]GameRoomPage\.tsx$/)
        const styles = (files: string[]) =>
          new Set(files.flatMap((file) => [...(byFile.get(file)?.viteMetadata?.importedCss ?? [])]))
        const entryStyles = styles([...preloaded])
        const roomFiles = room ? own([room.fileName]) : []
        const roomStyles = [...styles(roomFiles)].filter((file) => !entryStyles.has(file))
        const plan = { locales, room: roomFiles, roomCss: roomStyles }
        const script =
          `(function(){try{var p=${JSON.stringify(plan)};var s=null;` +
          `try{s=localStorage.getItem("sketchy_locale")}catch(e){}` +
          // Own keys only: a stored "constructor" is not a language.
          `var h=function(k){return Object.prototype.hasOwnProperty.call(p.locales,k)};` +
          // A public page's address names its language first (#1462):
          // `/de/rules` is read in German whatever this browser stored. The
          // app checks the rest of the path; a prefix on any other page is a
          // 404 that fetched German for nothing.
          `var u=location.pathname.split("/")[1];` +
          `var l=u!=="en"&&h(u)?u:h(s)?s:null;` +
          `if(!l){var b=navigator.languages||[navigator.language||""];` +
          `for(var i=0;i<b.length&&!l;i++){var t=String(b[i]).toLowerCase();` +
          `if(h(t))l=t;else if(h(t.split("-")[0]))l=t.split("-")[0];}}` +
          `var f=p.locales[l||"en"];` +
          // The first path segment, not a "/room/" literal: a page's markup is
          // checked for links into rooms (test_gallery.py), and the shell is
          // every page's markup.
          `var c=[];if(location.pathname.split("/")[1]==="room"){f=f.concat(p.room);c=p.roomCss;}` +
          `for(var j=0;j<f.length;j++){var k=document.createElement("link");` +
          `k.rel="modulepreload";k.crossOrigin="";k.href="/"+f[j];document.head.appendChild(k);}` +
          `for(var n=0;n<c.length;n++){var y=document.createElement("link");` +
          `y.rel="preload";y.as="style";y.crossOrigin="";y.href="/"+c[n];document.head.appendChild(y);}` +
          `}catch(e){}})();`
        return html.replace('</head>', `  <script>${script}</script>\n  </head>`)
      },
    },
  }
}

// The API and Socket.IO endpoints are same-origin in every real deployment:
// the backend serves the built frontend itself (see SPAStaticFiles in
// backend/app/main.py). The Vite dev server on :5173 is the one exception, so
// it proxies those two prefixes to the backend to keep the frontend's URLs
// relative everywhere - which is what lets the session cookie work unchanged in
// dev, under scripts/serve.sh, in E2E, and through a tunnel.
const DEV_BACKEND = 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), preloadReaderChunks(), precompress()],
  server: {
    proxy: {
      // The backend admits a browser only from its own origin (#465). Through
      // this proxy the browser's Origin is the dev server's, so the proxy
      // presents the backend's own instead - which is the truth: the request
      // is from the page the backend serves, reached through here.
      '/api': { target: DEV_BACKEND, changeOrigin: true, headers: { origin: DEV_BACKEND } },
      '/socket.io': {
        target: DEV_BACKEND,
        changeOrigin: true,
        ws: true,
        headers: { origin: DEV_BACKEND },
        configure: (proxy) => {
          proxy.on('proxyReqWs', (proxyReq) => proxyReq.setHeader('origin', DEV_BACKEND))
        },
      },
    },
  },
  build: {
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            {
              // The libraries every page runs on, in a chunk of their own
              // (#475). Its name carries a hash of its contents, and those
              // change only when a dependency does - so a returning player's
              // browser keeps it across deploys of the app itself, which is
              // most of them, instead of downloading React again each time.
              name: 'vendor',
              test: /[\\/]node_modules[\\/](react|react-dom|scheduler|react-router|react-router-dom|zustand|socket\.io-client|socket\.io-parser|engine\.io-client|engine\.io-parser|@socket\.io[\\/]component-emitter)[\\/]/,
            },
          ],
        },
      },
    },
  },
  // An image build has no .git in its context, so the Dockerfile passes the
  // commit in instead (SKETCHY_COMMIT_SHA / SKETCHY_COMMIT_DATE, #405).
  define: {
    __APP_COMMIT_SHA__: JSON.stringify(
      process.env.SKETCHY_COMMIT_SHA || gitLog('--format=%h') + (isWorkingTreeDirty() ? '*' : ''),
    ),
    __APP_COMMIT_DATE__: JSON.stringify(
      process.env.SKETCHY_COMMIT_DATE || gitLog('--date=short --format=%cd'),
    ),
    __APP_BUILD_TIME__: JSON.stringify(buildTime),
  },
})
