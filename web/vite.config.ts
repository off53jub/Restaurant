import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  base: './',
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['icons/192.png', 'icons/512.png', 'robots.txt'],
      manifest: {
        name: '外食メモ',
        short_name: '外食',
        description: 'Tokyo restaurant search (personal)',
        start_url: './',
        display: 'standalone',
        orientation: 'portrait',
        background_color: '#111111',
        theme_color: '#111111',
        icons: [
          { src: 'icons/192.png', sizes: '192x192', type: 'image/png' },
          { src: 'icons/512.png', sizes: '512x512', type: 'image/png' },
          { src: 'icons/maskable.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' }
        ]
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,png,svg,woff2}'],
        globIgnores: [
          '**/sql-asm*',
          '**/sql-wasm-debug*',
          '**/sql-wasm-browser-debug*',
          '**/worker.sql-asm*',
          '**/worker.sql-wasm-debug*'
        ],
        runtimeCaching: [
          {
            urlPattern: ({ url }) => url.pathname.endsWith('/sql-wasm.wasm') || url.pathname.includes('sql-wasm-') && url.pathname.endsWith('.wasm'),
            handler: 'CacheFirst',
            options: {
              cacheName: 'sqljs-wasm',
              expiration: { maxEntries: 2, maxAgeSeconds: 60 * 60 * 24 * 30 }
            }
          }
        ],
        maximumFileSizeToCacheInBytes: 5 * 1024 * 1024
      }
    })
  ],
  optimizeDeps: { exclude: ['sql.js'] },
  test: {
    globals: true,
    environment: 'node'
  }
})
