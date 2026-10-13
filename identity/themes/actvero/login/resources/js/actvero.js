// A desktop fresh-login request must let the user enter another account. Keycloak
// initially binds prompt=login to the SSO user; restart its flow rather than merely
// revealing a username input while the server still holds the previous identity.
const loginForm = document.getElementById('kc-form-login')
const resetLogin = document.getElementById('reset-login')
const loginPrompt = new URLSearchParams(window.location.search).get('prompt') || ''
if (loginForm?.dataset.actveroClient === 'actvero-desktop' &&
    loginPrompt.split(' ').includes('login') &&
    !document.getElementById('username') && resetLogin) {
  const restart = new URL(resetLogin.href, window.location.href)
  if (restart.origin === window.location.origin &&
      restart.pathname.endsWith('/login-actions/restart') &&
      restart.searchParams.get('client_id') === 'actvero-desktop') {
    // The restart URL is generated and validated by Keycloak. It preserves this
    // attempt's PKCE/state/nonce. Its next URL has no prompt, so this runs once.
    window.location.replace(restart.href)
  }
}

const themePreference = document.cookie.split('; ').find(value => value.startsWith('vite-ui-theme='))?.split('=')[1]
const systemTheme = window.matchMedia('(prefers-color-scheme: dark)')
function applyTheme() {
  document.documentElement.classList.toggle('dark', themePreference === 'dark' || (themePreference !== 'light' && systemTheme.matches))
}
applyTheme()
systemTheme.addEventListener('change', applyTheme)
document.addEventListener('submit', function (event) {
  const button = event.target.querySelector('button[type="submit"],input[type="submit"]')
  if (button) { button.disabled = true }
})
document.querySelectorAll('[data-actvero-password]').forEach(function (button) {
  button.addEventListener('click', function () {
    const input = document.getElementById(button.dataset.actveroPassword)
    const show = input.type === 'password'
    input.type = show ? 'text' : 'password'
    button.setAttribute('aria-label', show ? button.dataset.hideLabel : button.dataset.showLabel)
    button.querySelector('[data-eye]').hidden = !show
    button.querySelector('[data-eye-off]').hidden = show
  })
})
