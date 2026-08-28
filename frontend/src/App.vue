<template>
  <div class="min-h-full">
    <header class="sticky top-0 z-20 flex items-center justify-between bg-[#26221c] px-5 py-2.5 text-[#f3efe6] shadow">
      <RouterLink to="/" class="font-bold tracking-wide">408 · 真题套卷</RouterLink>
      <div class="flex items-center gap-3">
        <RouterLink
          to="/notebook"
          class="text-xs text-[#c9c2b4] transition hover:text-[#f3efe6]"
        >
          📓 笔记库
        </RouterLink>
        <RouterLink
          to="/settings"
          class="text-xs text-[#c9c2b4] transition hover:text-[#f3efe6]"
        >
          ⚙️ 设置
        </RouterLink>
        <span class="text-xs text-[#c9c2b4]">{{ store.title }}</span>
        <button
          v-if="auth.authenticated"
          type="button"
          class="rounded border border-[#4a4339] px-2 py-0.5 text-xs text-[#c9c2b4] transition hover:border-[#c9c2b4] hover:text-[#f3efe6]"
          @click="onLogout"
        >
          退出
        </button>
      </div>
    </header>
    <RouterView />
  </div>
</template>

<script setup>
import { RouterView, RouterLink, useRouter } from 'vue-router'
import { usePaperStore } from '@/stores/paper'
import { useAuthStore } from '@/stores/auth'

const store = usePaperStore()
const auth = useAuthStore()
const router = useRouter()

// 退出登录后回到登录页（logout 内部已清空本地状态）。
async function onLogout() {
  await auth.logout()
  router.push({ name: 'login' })
}
</script>
