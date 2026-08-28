<template>
  <main class="flex min-h-[calc(100vh-49px)] items-center justify-center px-4 py-10">
    <div class="w-full max-w-[360px] rounded-xl border border-line bg-paper p-7 shadow-lg">
      <div class="mb-5 text-center">
        <h1 class="font-song text-2xl font-bold tracking-wide text-ink">408 · 真题套卷</h1>
        <p class="mt-1 text-sm text-muted">请输入密码登录</p>
      </div>

      <el-input
        v-model="password"
        type="password"
        size="large"
        placeholder="密码"
        show-password
        :disabled="loading"
        @keyup.enter="onLogin"
      />

      <p v-if="error" class="mt-2 text-sm text-bad">{{ error }}</p>

      <el-button
        type="primary"
        size="large"
        class="mt-4 w-full"
        :loading="loading"
        @click="onLogin"
      >
        登录
      </el-button>
    </div>
  </main>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const password = ref('')
const loading = ref(false)
const error = ref('')

async function onLogin() {
  if (!password.value || loading.value) return
  loading.value = true
  error.value = ''
  try {
    await authStore.login(password.value)
    router.push({ name: 'home' })
  } catch (e) {
    // 后端 401 返回 { error: "..." }（axios 错误里取 response.data.error）
    error.value = e?.response?.data?.error || '密码错误或登录失败'
  } finally {
    loading.value = false
  }
}
</script>
