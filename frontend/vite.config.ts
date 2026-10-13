/// <reference types="vitest/config" />
import path from 'path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { tanstackRouter } from '@tanstack/router-plugin/vite'
import { playwright } from '@vitest/browser-playwright'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    tanstackRouter({
      target: 'react',
      autoCodeSplitting: true,
    }),
    react(),
    tailwindcss(),
  ],
  optimizeDeps: {
    include: [
      'react',
      'react/jsx-runtime',
      'react-dom/client',
      'recharts',
      'react-hook-form',
      '@hookform/resolvers/zod',
      'zod',
      '@tanstack/react-query',
      '@tanstack/react-router',
      '@tanstack/react-table',
      '@radix-ui/react-alert-dialog',
      '@radix-ui/react-direction',
      '@radix-ui/react-radio-group',
      '@radix-ui/react-scroll-area',
      '@radix-ui/react-tooltip',
      '@radix-ui/react-progress',
      '@radix-ui/react-collapsible',
      '@radix-ui/react-dialog',
      '@radix-ui/react-dropdown-menu',
      '@radix-ui/react-label',
      '@radix-ui/react-separator',
      '@radix-ui/react-slot',
      '@radix-ui/react-tabs',
      'class-variance-authority',
      'clsx',
      'lucide-react',
      'sonner',
      'tailwind-merge',
      'react-top-loading-bar',
      'motion/react',
      '@radix-ui/react-avatar',
      '@radix-ui/react-checkbox',
      '@radix-ui/react-select',
      '@radix-ui/react-popover',
      'cmdk',
      '@radix-ui/react-slider',
      'react-easy-crop',
    ],
  },
  server: {
    proxy: {
      '/api':
        process.env.ACTVERO_API_PROXY ||
        process.env.ACTVERO_API_URL ||
        'http://127.0.0.1:5195',
    },
  },
  resolve: {
    dedupe: ['react', 'react-dom'],
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    silent: 'passed-only',
    unstubEnvs: true,
    browser: {
      enabled: true,
      provider: playwright({
        launchOptions: { executablePath: process.env.ACTVERO_TEST_BROWSER },
      }),
      instances: [{ browser: 'chromium' }],
    },
    coverage: {
      // include: ['src/**/*.{js,jsx,ts,tsx}'], // Uncomment to expand the report to all src/**/* so untested modules appear as 0% coverage.
      exclude: [
        'src/components/ui/**',
        'src/assets/**',
        'src/tanstack-table.d.ts',
        'src/routeTree.gen.ts',
        'src/test-utils/**',
        'src/routes/**',
      ],
    },
  },
})
