<template>
  <main class="px-3.5 pb-24 pt-6">
    <div v-if="store.loading" class="py-16 text-center text-muted">出卷中…</div>

    <PaperAnnotations
      v-else :session-id="store.sessionId" :questions="store.questions" :graded="store.graded" :mode="store.mode"
      :visible-question-ids="visibleQuestionIds"
      :render-key="`${page}:${store.graded}`" @locate="locateQuestion"
    >
      <Scorecard v-if="store.graded && store.summary" :summary="store.summary" />

      <div class="mx-auto max-w-[820px] rounded-md border border-line bg-paper px-10 py-8 shadow-lg max-sm:px-4">
        <!-- 卷头：只在第一页出现完整卷头，后续页出简版页眉 -->
        <div v-if="page === 1" class="mb-2 border-b-2 border-ink pb-3.5 text-center">
          <h1 class="font-song text-2xl tracking-wide">{{ store.title }}</h1>
          <div class="text-[13px] text-muted">{{ paperMeta }}</div>
        </div>
        <div v-else class="mb-3 flex items-center justify-between border-b border-line pb-2 text-[12px] text-muted">
          <span class="font-song">{{ store.title }}</span>
          <span>第 {{ page }} 页</span>
        </div>

        <p v-if="!store.questions.length" class="py-10 text-center text-muted">暂无题目。</p>

        <template v-for="(group, gi) in visibleGroups" :key="gi">
          <h2
            v-if="group.title"
            class="mt-6 border-b border-dashed border-line pb-1 font-song text-[17px] font-bold"
          >
            {{ group.title }}
          </h2>
          <QuestionCard v-for="item in group.items" :key="item.q.id" :question="item.q" :index="item.index" />
        </template>

        <!-- 卷尾页码（试卷感） -->
        <div v-if="isExam && totalPages > 1" class="mt-6 border-t border-line pt-3 text-center font-song text-[13px] text-muted">
          — 第 {{ page }} 页 · 共 {{ totalPages }} 页 —
        </div>
      </div>

      <!-- 翻页条 -->
      <div v-if="isExam && totalPages > 1" class="mx-auto mt-3 flex max-w-[820px] flex-wrap items-center justify-center gap-1.5">
        <el-button size="small" :disabled="page === 1" @click="go(page - 1)">上一页</el-button>
        <button
          v-for="p in totalPages"
          :key="p"
          type="button"
          class="min-w-[30px] rounded border px-2 py-1 text-[13px] transition"
          :class="p === page ? 'border-primary bg-primary-soft font-bold text-primary' : 'border-line bg-white hover:border-primary'"
          @click="go(p)"
        >{{ p }}</button>
        <el-button size="small" :disabled="page === totalPages" @click="go(page + 1)">下一页</el-button>
      </div>

      <div class="mx-auto mt-4 flex max-w-[820px] items-center justify-between">
        <div class="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
          <span class="text-muted">{{ statusText }}</span>
          <span v-if="store.savingAnswerCount" class="text-muted">正在保存…</span>
          <template v-if="store.saveError">
            <span class="text-bad">答题保存失败：{{ store.saveError }}</span>
            <el-button size="small" :loading="retryingSaves" @click="retryPendingSaves">重试保存</el-button>
          </template>
        </div>
        <div class="flex gap-2">
          <el-button v-if="!store.graded" type="primary" size="large" :loading="store.grading" @click="onSubmit">
            交卷
          </el-button>
          <template v-else>
            <el-button type="primary" @click="reinforceAgain">再来一组强化</el-button>
            <el-button @click="router.push({ name: 'home' })">返回首页</el-button>
          </template>
        </div>
      </div>
    </PaperAnnotations>

    <DraftDialog />
    <NoteDrawer />
  </main>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { usePaperStore } from '@/stores/paper'
import QuestionCard from '@/components/QuestionCard.vue'
import Scorecard from '@/components/Scorecard.vue'
import DraftDialog from '@/components/DraftDialog.vue'
import NoteDrawer from '@/components/NoteDrawer.vue'
import PaperAnnotations from '@/components/PaperAnnotations.vue'

const route = useRoute()
const router = useRouter()
const store = usePaperStore()
const page = ref(1)
const retryingSaves = ref(false)

const CHOICE_PER_PAGE = 10   // 真题卷：每页 10 道单选
const SUBJ_PER_PAGE = 2      // 综合大题篇幅长，每页 2 道
const isExam = computed(() => store.mode === 'exam')

// 进卷：带 sid 就恢复那一场；否则建/续一场并把 sid 写回 query（刷新可恢复）。
async function load() {
  const { mode, year, all, sid, fresh } = route.query
  page.value = 1
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

function errorMessage(error, fallback) {
  return error?.response?.data?.error || error?.message || fallback
}

async function flushBeforeNavigation() {
  try {
    await store.flushAll()
    return true
  } catch (error) {
    ElMessage.error(`答题尚未保存，已取消跳转：${errorMessage(error, '请检查网络后重试')}`)
    return false
  }
}

// route.query 改变时当前组件不会卸载；两种守卫都必须有，才能覆盖所有切卷路径。
onBeforeRouteLeave(flushBeforeNavigation)
onBeforeRouteUpdate(flushBeforeNavigation)

function beforeUnload(event) {
  if (!store.hasPendingChanges()) return
  event.preventDefault()
  event.returnValue = ''
}

onMounted(() => window.addEventListener('beforeunload', beforeUnload))
onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', beforeUnload)
  void store.flushAll().catch(() => {})
})

// 真题卷按正常试卷组织并分页：单选连续为一节、综合大题为一节；强化卷保持单页连续流。
const pages = computed(() => {
  if (!isExam.value) return [[{ title: '', items: store.questions.map((q, i) => ({ q, index: i })) }]]
  const qs = [...store.questions].sort((a, b) => a.number - b.number)

  const choice = qs.filter((q) => q.qtype === 'choice')
  const subjective = qs.filter((q) => q.qtype === 'subjective')
  const out = []
  for (let i = 0; i < choice.length; i += CHOICE_PER_PAGE) {
    out.push([{
      title: i === 0 ? '一、单项选择题' : '一、单项选择题（续）',
      items: choice.slice(i, i + CHOICE_PER_PAGE).map((q, k) => ({ q, index: i + k })),
    }])
  }
  for (let i = 0; i < subjective.length; i += SUBJ_PER_PAGE) {
    out.push([{
      title: i === 0 ? '二、综合应用题' : '二、综合应用题（续）',
      items: subjective.slice(i, i + SUBJ_PER_PAGE).map((q, k) => ({ q, index: choice.length + i + k })),
    }])
  }
  return out.length ? out : [[{ title: '', items: [] }]]
})

const totalPages = computed(() => pages.value.length)
const visibleGroups = computed(() => pages.value[Math.min(page.value, totalPages.value) - 1] || [])
const visibleQuestionIds = computed(() => visibleGroups.value.flatMap(group => group.items.map(item => item.q.id)))

function go(p) {
  if (p < 1 || p > totalPages.value) return
  page.value = p
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function locateQuestion(questionId) {
  const index = pages.value.findIndex(groups => groups.some(group => group.items.some(item => item.q.id === questionId)))
  if (index >= 0) page.value = index + 1
}

const statusText = computed(() =>
  store.graded ? '已交卷' : `已作答 ${store.answeredCount} / ${store.questions.length}`,
)

// 卷头信息：真题套卷是真 408 结构（单选 80 + 综合 70 = 150）；强化卷只报题数。
const paperMeta = computed(() => {
  const qs = store.questions
  const instruction = store.graded ? '已交卷 · 可选中文字添加复盘批注' : '选出答案后点「交卷」'
  if (isExam.value) {
    const c = qs.filter((q) => q.qtype === 'choice').length
    const s = qs.filter((q) => q.qtype === 'subjective').length
    return `单选 ${c} 题 · 综合 ${s} 题 · 满分 150 分 · 共 ${totalPages.value} 页 · ${instruction}`
  }
  return `共 ${qs.length} 题 · 同知识点强化 · ${instruction}`
})

async function onSubmit() {
  try {
    await store.grade()
    page.value = 1
    window.scrollTo(0, 0)
  } catch (error) {
    ElMessage.error(`交卷失败：${errorMessage(error, '请检查网络后重试')}`)
  }
}

async function retryPendingSaves() {
  retryingSaves.value = true
  try {
    await store.retryPendingSaves()
    ElMessage.success('答题已保存')
  } catch (error) {
    ElMessage.error(`保存仍未完成：${errorMessage(error, '请检查网络后重试')}`)
  } finally {
    retryingSaves.value = false
  }
}

function reinforceAgain() {
  router.push({ name: 'paper', query: { mode: 'reinforce', all: '0', fresh: '1' } })
}
</script>
