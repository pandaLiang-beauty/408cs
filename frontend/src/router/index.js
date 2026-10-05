import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

// 单用户，密码登录。页面：登录 / 首页选卷 / 做卷。
const routes = [
  { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue') },
  { path: '/', name: 'home', component: () => import('@/views/HomeView.vue') },
  { path: '/paper', name: 'paper', component: () => import('@/views/PaperView.vue') },
  { path: '/notebook', name: 'notebook', component: () => import('@/views/NotebookView.vue') },
  { path: '/images', redirect: { path: '/', query: { imageHost: '1' } } },
  { path: '/settings', name: 'settings', component: () => import('@/views/SettingsView.vue') },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})

// 全局登录守卫：未登录只能进 /login，已登录不再回登录页。
router.beforeEach(async (to) => {
  const auth = useAuthStore()
  // 首次导航时向后端确认一次登录态（依赖 HttpOnly 会话 cookie）。
  if (!auth.known) {
    try {
      await auth.fetchMe()
    } catch {
      // 网络/后端异常按未登录处理，交由后续判断跳登录页。
    }
  }
  if (!auth.authenticated && to.name !== 'login') return { name: 'login' }
  if (auth.authenticated && to.name === 'login') return { name: 'home' }
})

export default router
