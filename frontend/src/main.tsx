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

// Before anything renders, so an error thrown during the first paint is still
// in the buffer if the player goes on to file a bug about it.
installClientErrorLog()
installCrashTestSeam()

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
