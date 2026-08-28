<template>
  <main class="px-3.5 pb-24 pt-6">
    <div class="mx-auto max-w-[820px]">
      <h1 class="mb-1 font-song text-[22px] font-bold">📓 笔记库</h1>
      <p class="mb-4 text-sm text-muted">
        按题聚合所有笔记（同一题在真题/强化里写的都汇到一处）。共 {{ groups.length }} 题 · {{ noteCount }} 条笔记。
      </p>

      <div class="mb-4 flex flex-wrap items-center gap-2">
        <input
          v-model="kw"
          placeholder="搜索笔记 / 题干…"
          class="w-56 rounded-lg border border-line px-3 py-1.5 text-sm outline-none focus:border-primary"
        />
        <button
          v-for="s in subjects"
          :key="s"
          type="button"
          class="rounded-full border px-3 py-1 text-xs transition"
          :class="subj === s ? 'border-primary bg-primary-soft text-primary' : 'border-line text-muted hover:border-primary'"
          @click="subj = subj === s ? '' : s"
        >
          {{ s }}
        </button>
      </div>

      <div v-if="loading" class="py-16 text-center text-muted">加载中…</div>
      <p v-else-if="!filtered.length" class="py-16 text-center text-muted">还没有匹配的笔记。做题时点「草稿 / 笔记」即可添加。</p>

      <div v-else class="flex flex-col gap-4">
        <section v-for="g in filtered" :key="g.question_id" class="rounded-md border border-line bg-paper p-4 shadow-sm">
          <div class="mb-1 flex items-center gap-2 text-xs text-muted">
            <span class="rounded bg-bgwarm px-1.5 py-0.5">{{ g.year }} · {{ g.qtype === 'choice' ? '单选' : '综合' }} 第 {{ g.number }} 题</span>
            <span v-if="g.subject">{{ g.subject }}</span>
            <span v-for="t in tagsOf(g)" :key="t" class="rounded-full bg-primary-soft px-2 py-0.5 text-primary">{{ t }}</span>
          </div>
          <div class="qhtml mb-2 line-clamp-2 font-song text-[15px] leading-[1.8] text-ink" v-html="g.stem_html"></div>
          <ul class="flex flex-col gap-1.5">
            <li v-for="n in g.notes" :key="n.id" class="rounded border border-line bg-[#faf8f4] px-2.5 py-1.5 text-sm leading-6">
              <div class="whitespace-pre-wrap">{{ n.body }}</div>
              <div class="mt-0.5 text-[11px] text-muted">{{ fmt(n.created_at) }}</div>
            </li>
          </ul>
        </section>
      </div>
    </div>
  </main>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getNotebook } from '@/api/cs408/quiz'

const groups = ref([])
const loading = ref(true)
const kw = ref('')
const subj = ref('')
const subjects = ['数据结构', '组成原理', '操作系统', '计算机网络']

onMounted(async () => {
  try {
    groups.value = await getNotebook()
  } catch {
    ElMessage.error('笔记库加载失败')
  } finally {
    loading.value = false
  }
})

const noteCount = computed(() => groups.value.reduce((s, g) => s + g.notes.length, 0))
function tagsOf(g) {
  return (g.tags || '').split(/[,，]/).filter(Boolean)
}
function fmt(s) {
  return (s || '').replace('T', ' ').slice(0, 16)
}

const filtered = computed(() => {
  const k = kw.value.trim()
  return groups.value.filter((g) => {
    if (subj.value && g.subject !== subj.value) return false
    if (!k) return true
    const hay = g.stem_html + ' ' + g.notes.map((n) => n.body).join(' ')
    return hay.includes(k)
  })
})
</script>
