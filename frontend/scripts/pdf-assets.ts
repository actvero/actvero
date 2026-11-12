import { readFileSync, readdirSync } from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'
import type { Plugin } from 'vite'

// Bundle PDF.js fonts and CMaps locally; documents never require a public CDN.
export function pdfAssets(): Plugin {
  const require = createRequire(import.meta.url)
  const root = path.dirname(require.resolve('pdfjs-dist/package.json'))
  const files = new Map<string, string>()
  for (const dir of ['cmaps', 'standard_fonts']) {
    for (const file of readdirSync(path.join(root, dir))) {
      files.set(`pdf-assets/${dir}/${file}`, path.join(root, dir, file))
    }
  }
  return {
    name: 'local-pdf-assets',
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const file = files.get((request.url ?? '').split('?')[0].slice(1))
        if (!file) return next()
        response.setHeader('Content-Type', 'application/octet-stream')
        response.end(readFileSync(file))
      })
    },
    generateBundle() {
      for (const [fileName, file] of files) {
        this.emitFile({ type: 'asset', fileName, source: readFileSync(file) })
      }
    },
  }
}
