import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as auth from '@/api/cs408/auth'

// 单用户登录状态。集中在此，视图与路由守卫只做转发。
export const useAuthStore = defineStore('auth', () => {
  const authenticated = ref(false)
  const user = ref(null)
  const known = ref(false) // 是否已向后端确认过登录态（守卫据此决定要不要 fetchMe）

  // 向后端确认当前会话是否有效，同步本地状态。
  async function fetchMe() {
    const d = await auth.me()
    authenticated.value = !!d.authenticated
    user.value = d.authenticated ? d.user : null
    known.value = true
    return authenticated.value
  }

  // 登录：失败时 axios 会 reject，向上抛出交给视图展示错误。
  async function login(password) {
    const d = await auth.login(password)
    authenticated.value = true
    user.value = d.user
    known.value = true
  }

  // 退出：无论后端是否成功，本地都清空登录态。
  async function logout() {
    try {
      await auth.logout()
    } finally {
      authenticated.value = false
      user.value = null
      known.value = true
    }
  }

  return { authenticated, user, known, fetchMe, login, logout }
})
