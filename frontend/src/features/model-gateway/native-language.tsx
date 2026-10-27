import { useEffect, useState, type ReactNode } from 'react'
import zh from '@/vendor/newapi/zh.json'
import nativeI18n from 'i18next'
import { I18nextProvider, initReactI18next } from 'react-i18next'
import { LoadingState } from '@/components/request-state'

const ready = nativeI18n.use(initReactI18next).init({
  lng: 'zh',
  fallbackLng: 'zh',
  resources: { zh },
  keySeparator: false,
  nsSeparator: false,
  interpolation: { escapeValue: false },
})

export function NativeLanguage({ children }: { children: ReactNode }) {
  const [loaded, setLoaded] = useState(nativeI18n.isInitialized)
  useEffect(() => {
    let active = true
    void ready.then(() => {
      if (active) setLoaded(true)
    })
    return () => {
      active = false
    }
  }, [])
  return loaded ? (
    <I18nextProvider i18n={nativeI18n}>{children}</I18nextProvider>
  ) : (
    <LoadingState />
  )
}
