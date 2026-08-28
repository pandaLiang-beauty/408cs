import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// cs408 前端：Vite 配置。开发时把 /api、/drafts 代理到 Python 后端(8408)。
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 3000,
    open: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8408', changeOrigin: true },
      '/drafts': { target: 'http://127.0.0.1:8408', changeOrigin: true },
    },
  },
})
