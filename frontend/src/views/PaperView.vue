<template>
  <main class="px-3.5 pb-24 pt-6">
    <div v-if="store.loading" class="py-16 text-center text-muted">出卷中…</div>

    <template v-else>
      <Scorecard v-if="store.graded && store.summary" :summary="store.summary" />

      <div class="mx-auto max-w-[820px] rounded-md border border-line bg-paper px-10 py-8 shadow-lg max-sm:px-4">
        <div class="mb-2 border-b-2 border-ink pb-3.5 text-center">
          <h1 class="font-song text-2xl tracking-wide">{{ store.title }}</h1>
          <div class="text-[13px] text-muted">{{ paperMeta }}</div>
        </div>

        <p v-if="!store.questions.length" class="py-10 text-center text-muted">暂无题目。</p>

        <template v-for="(group, gi) in groups" :key="gi">
          <h2
            v-if="group.title"
            class="mt-6 border-b border-dashed border-line pb-1 font-song text-[17px] font-bold"
          >
            {{ group.title }}
          </h2>
          <QuestionCard v-for="item in group.items" :key="item.q.id" :question="item.q" :index="item.index" />
        </template>
      </div>

      <div class="mx-auto mt-4 flex max-w-[820px] items-center justify-between">
        <span class="text-sm text-muted">{{ statusText }}</span>
        <div class="flex gap-2">
          <el-button v-if="!store.graded" type="primary" size="large" :loading="submitting" @click="onSubmit">
            交卷
          </el-button>
          <template v-else>
            <el-button type="primary" @click="reinforceAgain">再来一组强化</el-button>
            <el-button @click="router.push({ name: 'home' })">返回首页</el-button>
          </template>
        </div>
      </div>
    </template>
  </main>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { usePaperStore } from '@/stores/paper'
import QuestionCard from '@/components/QuestionCard.vue'
import Scorecard from '@/components/Scorecard.vue'

const route = useRoute()
const router = useRouter()
const store = usePaperStore()
const submitting = ref(false)

// 进卷：带 sid 就恢复那一场；否则建/续一场并把 sid 写回 query（刷新可恢复）。
async function load() {
  const { mode, year, all, sid, fresh } = route.query
  try {
    if (sid) {
      await store.loadSession(Number(sid))
      return
    }
    if (mode === 'exam' && year) {
      const id = await store.startSession({ kind: 'exam', year: Number(year), fresh: fresh === '1' })
      router.replace({ name: 'paper', query: { mode, year, sid: id } })
    } else if (mode === 'reinforce') {
      const id = await store.startSession({ kind: 'reinforce', all: all === '1', fresh: fresh === '1' })
      router.replace({ name: 'paper', query: { mode, all: all || '0', sid: id } })
    } else {
      router.replace({ name: 'home' })
    }
  } catch {
    ElMessage.error('加载失败，请确认后端已在 8408 端口运行')
  }
}
onMounted(load)
watch(() => route.fullPath, load)


// 按正常试卷组织：不按科目分类。选择题连续为一节、综合大题为一节。
const groups = computed(() => {
  const qs = [...store.questions].sort((a, b) => a.number - b.number)
  if (store.mode !== 'exam') return [{ title: '', items: qs.map((q, i) => ({ q, index: i })) }]
  const choice = qs.filter((q) => q.qtype === 'choice')
  const subjective = qs.filter((q) => q.qtype === 'subjective')
  const out = []
  if (choice.length) out.push({ title: '一、单项选择题', items: choice.map((q, i) => ({ q, index: i })) })
  if (subjective.length) out.push({ title: '二、综合应用题', items: subjective.map((q, i) => ({ q, index: choice.length + i })) })
  return out
})

const statusText = computed(() =>
  store.graded ? '已交卷' : `已作答 ${store.answeredCount} / ${store.questions.length}`,
)

// 卷头信息：真题套卷是真 408 结构（单选 80 + 综合 70 = 150）；强化卷只报题数。
const paperMeta = computed(() => {
  const qs = store.questions
  if (store.mode === 'exam') {
    const c = qs.filter((q) => q.qtype === 'choice').length
    const s = qs.filter((q) => q.qtype === 'subjective').length
    return `单选 ${c} 题 · 综合 ${s} 题 · 满分 150 分 · 选出答案后点「交卷」`
  }
  return `共 ${qs.length} 题 · 选出答案后点「交卷」`
})

async function onSubmit() {
  submitting.value = true
  try {
    await store.grade()
    window.scrollTo(0, 0)
  } catch {
    ElMessage.error('交卷失败，请检查后端是否运行')
  } finally {
    submitting.value = false
  }
}

function reinforceAgain() {
  router.push({ name: 'paper', query: { mode: 'reinforce', all: '0', fresh: '1' } })
}
</script>
