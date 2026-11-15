import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@/styles/index.css'
import { DirectionProvider } from '@/context/direction-provider'
import { FontProvider } from '@/context/font-provider'
import { ThemeProvider } from '@/context/theme-provider'
import { DesignSystemPage } from '@/features/design-system/page'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider storageKey='actvero-design-theme'>
      <FontProvider>
        <DirectionProvider>
          <DesignSystemPage />
        </DirectionProvider>
      </FontProvider>
    </ThemeProvider>
  </StrictMode>
)
