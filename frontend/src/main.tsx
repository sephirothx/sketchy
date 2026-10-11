import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource/fredoka/500.css'
import '@fontsource/fredoka/600.css'
import '@fontsource/nunito-sans/400.css'
import '@fontsource/nunito-sans/600.css'
import '@fontsource/nunito-sans/700.css'
import '@fontsource/nunito-sans/800.css'
import App from './App.tsx'
import { CrashBoundary } from './components/CrashBoundary.tsx'
import { CrashPage } from './pages/CrashPage.tsx'
import { installClientErrorLog } from './lib/clientErrorLog.ts'
import { installCrashTestSeam } from './lib/crashTestSeam.ts'
import { installChunkReload } from './lib/chunkReload.ts'
import { installScrollHandles } from './lib/scrollHandles.ts'
import { prefetchPlayRoutes, prefetchRouteFor } from './routeModules.ts'
import { beforeFirstPaint } from './lib/startup.ts'
import { useAuthStore } from './store/authStore.ts'
import { initialLocaleReady } from './store/settingsStore.ts'

// Before anything renders, so an error thrown during the first paint is still
// in the buffer if the player goes on to file a bug about it.
installClientErrorLog()
installCrashTestSeam()
installChunkReload()
// Before the first paint, so no page is ever laid out beside a scrollbar's
// lane (#1222).
installScrollHandles()

// The page this address draws is a chunk of its own (#475): fetched now, while
// the paint waits on the account below, rather than once it is over.
const routeFetched = prefetchRouteFor(window.location.pathname)

// The account's language outranks the browser's (R-I18N-06), and is only
// known once the account is: so the first paint waits for it, bounded, and
// App's own lookup finds it already answered (lib/startup.ts). The browser's
// own language is fetched alongside rather than after (#982), so a guest's
// paint waits for whichever of the two is slower, not for both in turn.
// Whatever the bound, never without words: English is a chunk like every
// other language now (#1426), so until one has arrived there is nothing to
// render with. A shell whose chunks are all gone is reloaded by chunkReload.
void Promise.all([
  beforeFirstPaint(Promise.all([useAuthStore.getState().fetchMe(), initialLocaleReady])),
  initialLocaleReady.catch(() => undefined),
]).then(() => {
// On an invite link the room's own chunks come first: the lobby's play routes
// fetched alongside them competed with the page being opened (#1426).
void routeFetched.then(prefetchPlayRoutes)
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {/* Outside the router and every provider on purpose: nothing that can
        crash sits above this boundary, which is why its two ways out are hard
        navigations rather than routes. Every store in memory belongs to the
        tree that just failed; what the browser stores - settings, the upgrade
        marker - is left exactly as it was. */}
    <CrashBoundary
      scope="app"
      renderFallback={({ error, componentStack }) => (
        <CrashPage
          scope="app"
          error={error}
          componentStack={componentStack}
          onReload={() => window.location.reload()}
          onBackToLobby={() => {
            window.location.href = '/'
          }}
        />
      )}
    >
      <App />
    </CrashBoundary>
  </StrictMode>,
)
})
