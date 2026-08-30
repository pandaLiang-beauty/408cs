import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// cs408 前端：Vite 配置。前后端分离——后端只出接口(8408)，前端 dev server 独占 3000，
// /api、/drafts、/u 由这里代理过去，所以浏览器全程同源，不牵扯 CORS。
const backendTarget = process.env.STUDY_LOCAL_BACKEND || 'http://127.0.0.1:8408'

// 隧道域名：Cloudflare 把 Host 原样带过来，不在 allowedHosts 里 vite 直接 403。
const publicHost = String(process.env.STUDY_PUBLIC_HOST || '').trim()

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: process.env.STUDY_FRONTEND_HOST || '127.0.0.1',
    port: Number(process.env.STUDY_FRONTEND_PORT || 3000),
    open: false,
    ...(publicHost ? { allowedHosts: [publicHost] } : {}),
    // HMR 的 socket 按浏览器看到的地址连：隧道那边是 https/443，
    // 默认值会让客户端去连隧道外不存在的 3000。
    ...(publicHost ? { hmr: { protocol: 'wss', host: publicHost, clientPort: 443 } } : {}),
    proxy: {
      '/api': { target: backendTarget, changeOrigin: true },
      '/drafts': { target: backendTarget, changeOrigin: true },
      // 手机扫码上传草稿纸的页面在后端，前端这边只负责转发。
      '/u': { target: backendTarget, changeOrigin: true },
    },
  },
})
