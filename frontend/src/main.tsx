import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource/fredoka/500.css'
import '@fontsource/fredoka/600.css'
import '@fontsource/nunito-sans/400.css'
import '@fontsource/nunito-sans/600.css'
import '@fontsource/nunito-sans/700.css'
import '@fontsource/nunito-sans/800.css'
import App from './App.tsx'
import { installClientErrorLog } from './lib/clientErrorLog.ts'

// Before anything renders, so an error thrown during the first paint is still
// in the buffer if the player goes on to file a bug about it.
installClientErrorLog()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
