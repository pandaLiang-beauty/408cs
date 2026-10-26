import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as quiz from '@/api/cs408/quiz'
import { createAnswerSaveQueue } from './answerSaveQueue'

// 一场做题（session）的完整状态与操作。答题即自动保存到后端，刷新可恢复。
export const usePaperStore = defineStore('paper', () => {
  const sessionId = ref(null)
  const mode = ref('exam') // exam | reinforce | reinforce_subjective
  const year = ref(null)
  const title = ref('')
  const questions = ref([])
  const answers = ref({}) // qid -> { chosen, fuzzy }  （本地可编辑镜像）
  const items = ref({}) // qid -> 后端做题记录（含 draft_url / 大题批改 / 交卷后正确答案）
  const graded = ref(false)
  const loading = ref(false)
  const grading = ref(false)
  const summary = ref(null) // { total, correct, wrong, fuzzy }
  const savingAnswerCount = ref(0)
  const saveErrors = ref({}) // sessionId:questionId -> message

  // 交卷后的展示数据直接复用 items（其中含 answer / is_correct / result）
  const results = computed(() => items.value)
  const answeredCount = computed(
    () => Object.values(answers.value).filter((a) => a.chosen).length,
  )
  const saveError = computed(() => Object.values(saveErrors.value)[0] || '')

  function _title(kind, y) {
    if (kind === 'exam') return `${y} 年 408 真题`
    return kind === 'reinforce_subjective' ? '大题强化卷' : '选择题强化卷'
  }

  function _apply(payload) {
    sessionId.value = payload.session_id
    mode.value = payload.kind
    year.value = payload.year
    title.value = _title(payload.kind, payload.year)
    if (payload.kind === 'reinforce' && payload.questions.some(q => q.qtype === 'subjective')) {
      title.value = '强化训练卷'
    }
    questions.value = payload.questions
    items.value = payload.items || {}
    graded.value = payload.status === 'graded'
    const a = {}
    payload.questions.forEach((q) => {
      const it = payload.items?.[q.id]
      a[q.id] = { chosen: it?.chosen || '', fuzzy: !!it?.fuzzy }
    })
    answers.value = a
    if (graded.value) {
      const choiceItems = payload.questions.filter((q) => q.qtype === 'choice')
      const correct = choiceItems.filter((q) => items.value[q.id]?.is_correct).length
      const fuzzy = choiceItems.filter((q) => items.value[q.id]?.fuzzy).length
      summary.value = {
        total: choiceItems.length,
        correct,
        wrong: choiceItems.length - correct,
        fuzzy,
      }
    } else {
      summary.value = null
    }
  }

  async function loadSession(sid) {
    loading.value = true
    try {
      _apply(await quiz.getSession(sid))
    } finally {
      loading.value = false
    }
  }

  // 建/续一场做题；返回 session_id，供视图写进路由 query 以便刷新恢复。
  async function startSession({ kind, year: y, all, fresh }) {
    loading.value = true
    try {
      _apply(await quiz.createSession({ kind, year: y, all: !!all, fresh: !!fresh }))
      return sessionId.value
    } finally {
      loading.value = false
    }
  }

  // ---- 自动保存：同一题的请求严格串行，避免慢请求覆盖后一次选择 ----
  const answerSaveQueue = createAnswerSaveQueue({
    save: ({ sessionId: savedSessionId, questionId, payload }) =>
      quiz.patchItem(savedSessionId, questionId, payload),
    onStateChange: ({ pending, active }) => {
      savingAnswerCount.value = pending + active
    },
    onError: (error, entry) => {
      const message = error?.response?.data?.error || error?.message || '答题保存失败，请重试'
      saveErrors.value = { ...saveErrors.value, [entry.key]: message }
    },
    onSuccess: (entry) => {
      if (!(entry.key in saveErrors.value)) return
      const next = { ...saveErrors.value }
      delete next[entry.key]
      saveErrors.value = next
    },
  })

  function _save(qid) {
    const a = answers.value[qid]
    if (!sessionId.value || !a) return Promise.resolve(false)
    // 入队时即冻结快照与会话，不能等到请求执行时再读响应式状态。
    return answerSaveQueue.enqueue({
      sessionId: sessionId.value,
      questionId: qid,
      payload: { chosen: a.chosen, fuzzy: a.fuzzy },
    })
  }

  async function flushAll() {
    await answerSaveQueue.flushAll()
  }

  async function retryPendingSaves() {
    await answerSaveQueue.flushAll()
  }

  function hasPendingChanges() {
    return answerSaveQueue.hasPendingChanges()
  }

  function setChosen(qid, key) {
    if (graded.value || grading.value || !answers.value[qid]) return
    answers.value[qid].chosen = key
    void _save(qid)
  }

  function toggleFuzzy(qid) {
    if (graded.value || grading.value || !answers.value[qid]) return
    answers.value[qid].fuzzy = !answers.value[qid].fuzzy
    void _save(qid)
  }

  async function grade() {
    if (graded.value || grading.value || !sessionId.value) return
    grading.value = true
    try {
      await flushAll()
      const res = await quiz.submitSession(sessionId.value)
      _apply(res)
      summary.value = { total: res.total, correct: res.correct, wrong: res.wrong, fuzzy: res.fuzzy }
    } finally {
      grading.value = false
    }
  }

  // 组件回写：大题批改结果 / 草稿地址 更新到 items
  function patchLocalItem(qid, patch) {
    items.value[qid] = { ...(items.value[qid] || {}), ...patch }
  }

  // 弹层归属：草稿二维码弹窗 / 笔记右侧抽屉，各只挂一个实例，由卷面统一渲染
  const draftQid = ref(null)
  const noteQid = ref(null)
  const openDraft = (qid) => (draftQid.value = qid)
  const openNote = (qid) => (noteQid.value = qid)

  return {
    sessionId, mode, year, title, questions, answers, items, graded, loading, grading, summary,
    savingAnswerCount, saveError, results, answeredCount, draftQid, noteQid,
    loadSession, startSession, setChosen, toggleFuzzy, grade, flushAll, retryPendingSaves,
    hasPendingChanges, patchLocalItem,
    openDraft, openNote,
  }
})
