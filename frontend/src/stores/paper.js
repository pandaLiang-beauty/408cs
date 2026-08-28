import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as quiz from '@/api/cs408/quiz'

// 一场做题（session）的完整状态与操作。答题即自动保存到后端，刷新可恢复。
export const usePaperStore = defineStore('paper', () => {
  const sessionId = ref(null)
  const mode = ref('exam') // exam | reinforce
  const year = ref(null)
  const title = ref('')
  const questions = ref([])
  const answers = ref({}) // qid -> { chosen, fuzzy }  （本地可编辑镜像）
  const items = ref({}) // qid -> 后端做题记录（含 draft_url / 大题批改 / 交卷后正确答案）
  const graded = ref(false)
  const loading = ref(false)
  const summary = ref(null) // { total, correct, wrong, fuzzy }

  // 交卷后的展示数据直接复用 items（其中含 answer / is_correct / result）
  const results = computed(() => items.value)
  const answeredCount = computed(
    () => Object.values(answers.value).filter((a) => a.chosen).length,
  )

  function _title(kind, y) {
    return kind === 'exam' ? `${y} 年 408 真题` : '强化训练卷'
  }

  function _apply(payload) {
    sessionId.value = payload.session_id
    mode.value = payload.kind
    year.value = payload.year
    title.value = _title(payload.kind, payload.year)
    questions.value = payload.questions
    items.value = payload.items || {}
    graded.value = payload.status === 'graded'
    const a = {}
    payload.questions.forEach((q) => {
      const it = payload.items?.[q.id]
      a[q.id] = { chosen: it?.chosen || '', fuzzy: !!it?.fuzzy }
    })
    answers.value = a
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

  // ---- 自动保存：离散动作（选项/模糊）改动即立即保存，避免"点完马上刷新"丢失 ----
  const _inflight = {} // qid -> 最近一次保存的 Promise
  function _save(qid) {
    const a = answers.value[qid]
    if (!sessionId.value || !a) return
    const p = quiz
      .patchItem(sessionId.value, qid, { chosen: a.chosen, fuzzy: a.fuzzy })
      .catch(() => {}) // 失败静默：下次改动会重发
    _inflight[qid] = p
    return p
  }
  async function flushAll() {
    await Promise.all(Object.values(_inflight))
  }

  function setChosen(qid, key) {
    if (graded.value || !answers.value[qid]) return
    answers.value[qid].chosen = key
    _save(qid)
  }

  function toggleFuzzy(qid) {
    if (graded.value || !answers.value[qid]) return
    answers.value[qid].fuzzy = !answers.value[qid].fuzzy
    _save(qid)
  }

  async function grade() {
    if (graded.value || !sessionId.value) return
    await flushAll()
    const res = await quiz.submitSession(sessionId.value)
    _apply(res)
    summary.value = { total: res.total, correct: res.correct, wrong: res.wrong, fuzzy: res.fuzzy }
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
    sessionId, mode, year, title, questions, answers, items, graded, loading, summary,
    results, answeredCount, draftQid, noteQid,
    loadSession, startSession, setChosen, toggleFuzzy, grade, flushAll, patchLocalItem,
    openDraft, openNote,
  }
})
