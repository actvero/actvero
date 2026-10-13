// Build the shared Tailwind stylesheet before starting local identity services.
// This CSS-only build is independent of application routes and type checking.
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { execFileSync } from 'node:child_process'
import { build } from 'vite'
import tailwindcss from '@tailwindcss/vite'

const root = fileURLToPath(new URL('../', import.meta.url))
const result = await build({
  configFile: false,
  root,
  plugins: [tailwindcss()],
  logLevel: 'warn',
  build: {
    write: false,
    rollupOptions: { input: fileURLToPath(new URL('../src/styles/index.css', import.meta.url)) },
  },
})
const outputs = Array.isArray(result) ? result.flatMap(r => r.output) : result.output
const css = outputs.find(asset => asset.type === 'asset' && asset.fileName.endsWith('.css'))
if (!css || css.type !== 'asset' || !css.source.length) throw new Error('No compiled identity CSS')
const destination = new URL('../../identity/themes/actvero/login/resources/css/', import.meta.url)
await mkdir(destination, { recursive: true })
await writeFile(new URL('generated.css', destination), css.source)
execFileSync('python3', ['../scripts/build-identity-theme.py', '--version'], {
  cwd: root,
  stdio: 'inherit',
})
console.log('身份页面已同步统一主题（独立 CSS 构建）。')
