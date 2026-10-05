<template>
  <div class="min-h-full">
    <header class="sticky top-0 z-20 flex flex-wrap items-center justify-between gap-2 bg-[#26221c] px-5 py-2.5 text-[#f3efe6] shadow">
      <div class="flex items-center gap-3">
        <RouterLink to="/" class="font-bold tracking-wide">408 · 真题套卷</RouterLink>
        <ImageHostPopover v-if="auth.authenticated" ref="imageHost" />
      </div>
      <div class="flex flex-wrap items-center gap-3">
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
        <span v-if="route.name === 'paper' && store.title" class="text-xs text-[#c9c2b4]">{{ store.title }}</span>
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
import { nextTick, ref, watch } from 'vue'
import { RouterView, RouterLink, useRouter, useRoute } from 'vue-router'
import ImageHostPopover from '@/components/ImageHostPopover.vue'
import { usePaperStore } from '@/stores/paper'
import { useAuthStore } from '@/stores/auth'

const store = usePaperStore()
const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const imageHost = ref(null)

// 兼容之前的图床书签，在首页打开同一个快捷浮层。
watch(() => [auth.authenticated, route.query.imageHost], async ([authenticated, requested]) => {
  if (!authenticated || requested !== '1') return
  await nextTick()
  imageHost.value?.open()
  const { imageHost: _requested, ...query } = route.query
  router.replace({ query })
}, { immediate: true })

// 退出登录后回到登录页（logout 内部已清空本地状态）。
async function onLogout() {
  await auth.logout()
  router.push({ name: 'login' })
}
</script>
