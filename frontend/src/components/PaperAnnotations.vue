<template>
  <div v-if="graded" class="annotation-tools" :class="{ 'annotation-tools-wide': panelOpen }">
    <span>选中题干、选项或解析文字，即可添加批注</span>
    <button type="button" class="annotation-toggle" :aria-expanded="panelOpen" @click="panelOpen = !panelOpen">
      <ChatLineSquare aria-hidden="true" /> {{ panelOpen ? '收起复盘批注' : '复盘批注' }} · {{ records.length }}
      <span v-if="draft" class="unsaved-dot" title="有未保存的批注"></span>
    </button>
  </div>

  <div ref="workspace" class="annotation-workspace" :class="{ 'annotation-workspace-open': graded && panelOpen }">
    <div ref="paperContent" class="annotation-paper" @pointerup.capture="onPointerUp">
      <slot />
    </div>

    <aside v-if="graded && panelOpen" class="annotation-sidebar" aria-label="试卷复盘批注">
      <header class="annotation-sidebar-header">
        <div><strong>复盘批注 <span>{{ records.length }}</span></strong><p>本页 {{ visibleRecords.length }} 条 · 随题目排列</p></div>
        <button type="button" class="annotation-close" aria-label="收起批注边栏" @click="panelOpen = false"><Close /></button>
      </header>
      <label v-if="sortedRecords.length" class="annotation-index">
        定位批注
        <select aria-label="定位批注题目" @change="jumpToAnnotatedQuestion">
          <option value="">选择题目…</option>
          <option v-for="item in annotatedQuestions" :key="item.id" :value="item.id">{{ item.label }}</option>
        </select>
      </label>
      <button v-if="draft && !visibleIds.has(draft.question_id)" type="button" class="annotation-resume" @click="focusComposer">
        继续编辑 {{ label(draft) }} →
      </button>
      <div ref="annotationList" class="annotation-list" :style="{ height: sidebarLayout.height + 'px' }">
        <p v-if="loading" class="annotation-empty" role="status">正在读取批注…</p>
        <div v-if="loadError" class="annotation-error" role="alert">{{ loadError }} <button type="button" @click="loadRecords">重试</button></div>
        <p v-if="!loading && !loadError && !sidebarEntries.length" class="annotation-empty">
          {{ records.length ? '本页暂无批注，可从上方定位其他题目的批注。' : '选中文字或点击题号旁的「批注」，记录想法。' }}
        </p>

        <div v-for="entry in sidebarEntries" :key="entry.key" :data-annotation-entry="entry.key"
             class="annotation-entry" :style="entryStyle(entry.key)">
          <form v-if="entry.isDraft" class="annotation-composer" @submit.prevent="saveDraft">
            <div class="annotation-card-heading"><strong>{{ draft.id ? '编辑批注' : '新批注' }}</strong><span>{{ label(draft) }}</span></div>
            <blockquote v-if="draft.quote" class="annotation-source-quote">{{ draft.quote }}</blockquote>
            <MarkdownEditor
              ref="editor" v-model="draft.body" aria-label="批注内容" placeholder="写下你的疑问、思路或易错点…"
              :rows="4" :maxlength="5000" :disabled="saving" @keydown.ctrl.enter.prevent="saveDraft" @keydown.meta.enter.prevent="saveDraft"
            />
            <p v-if="saveError" class="annotation-error" role="alert">{{ saveError }}</p>
            <div class="annotation-editor-actions">
              <button type="submit" class="annotation-save" :disabled="saving || !draft.body.trim()">{{ saving ? '保存中…' : '保存批注' }}</button>
              <button type="button" :disabled="saving" @click="cancelDraft">取消</button>
            </div>
            <p class="annotation-draft-hint">{{ storageFailed ? '请保存后再离开页面' : '未保存的草稿会在此浏览器保留' }} · Ctrl / ⌘ + Enter 保存</p>
          </form>

          <article v-else :data-comment-id="entry.record.id" class="annotation-card"
                   :class="{ 'annotation-card-active': activeId === entry.record.id, 'annotation-card-resolved': entry.record.resolved }">
            <div class="annotation-card-heading"><span class="annotation-avatar">我</span><strong>{{ label(entry.record) }}</strong><time>{{ formatTime(entry.record.updated_at) }}</time></div>
            <button type="button" class="annotation-quote" :aria-label="'定位原文：' + label(entry.record)" @click="activate(entry.record)">
              <blockquote v-if="entry.record.quote" class="annotation-source-quote">{{ entry.record.quote }}</blockquote><span v-else>查看本题 ↗</span>
            </button>
            <MarkdownContent class="annotation-body" :source="entry.record.body" />
            <div class="annotation-card-actions">
              <span v-if="entry.record.resolved" class="annotation-resolved-label">✓ 已解决</span>
              <button type="button" :disabled="busyId === entry.record.id" @click="setResolved(entry.record)">{{ entry.record.resolved ? '重新打开' : '标为已解决' }}</button>
              <button type="button" :disabled="busyId === entry.record.id || saving" @click="openComposer(entry.record)">编辑</button>
              <button type="button" :disabled="busyId === entry.record.id || saving" @click="remove(entry.record)">删除</button>
            </div>
          </article>
        </div>
      </div>
    </aside>

    <svg v-if="connector" class="annotation-connector" aria-hidden="true"><path :d="connector" /></svg>
  </div>

  <Teleport to="body">
    <div v-if="pendingSelection" class="annotation-selection-toolbar" :style="toolbarStyle" role="toolbar" aria-label="选中文字批注">
      <button type="button" @pointerdown.prevent @click="openComposer(pendingSelection)"><ChatLineSquare aria-hidden="true" /> 添加批注</button>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, provide, ref, watch } from 'vue'
import { ChatLineSquare, Close } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { addAnnotation, deleteAnnotation, editAnnotation, listAnnotations } from '@/api/cs408/quiz'
import { PAPER_ANNOTATIONS, clearHighlights, paintHighlights, pointInRange, rangeForAnchor, regionElement, selectionAnchor } from '@/utils/annotationAnchors'
import { placeAnnotations } from '@/utils/annotationLayout'
import MarkdownEditor from '@/components/MarkdownEditor.vue'
import MarkdownContent from '@/components/MarkdownContent.vue'

const props = defineProps({ sessionId: Number, questions: { type: Array, default: () => [] }, visibleQuestionIds: { type: Array, default: null }, mode: String, graded: Boolean, renderKey: [String, Number] })
const emit = defineEmits(['locate'])
const workspace = ref(null)
const paperContent = ref(null)
const editor = ref(null)
const annotationList = ref(null)
const sidebarLayout = ref({ positions: {}, height: 120 })
const panelOpen = ref(props.graded)
const records = ref([])
const loading = ref(false)
const loadError = ref('')
const saveError = ref('')
const activeId = ref(null)
const busyId = ref(null)
const draft = ref(null)
const saving = ref(false)
const storageFailed = ref(false)
const pendingSelection = ref(null)
const toolbarStyle = ref({})
const connector = ref('')
let ranges = new Map()
let observer
let resizeObserver
const observedElements = new Set()
let paintFrame = 0
let layoutFrame = 0
let loadEpoch = 0
let disposed = false

const positions = computed(() => new Map(props.questions.map((q, i) => [q.id, i])))
const sortedRecords = computed(() => [...records.value].sort((a, b) =>
  (positions.value.get(a.question_id) ?? 9999) - (positions.value.get(b.question_id) ?? 9999) || a.id - b.id))
const visibleIds = computed(() => new Set(props.visibleQuestionIds || props.questions.map(q => q.id)))
const visibleRecords = computed(() => sortedRecords.value.filter(record => visibleIds.value.has(record.question_id)))
const sidebarEntries = computed(() => {
  const entries = visibleRecords.value.filter(record => record.id !== draft.value?.id)
    .map(record => ({ key: 'record-' + record.id, record, isDraft: false }))
  if (draft.value && visibleIds.value.has(draft.value.question_id)) entries.push({ key: 'draft', record: draft.value, isDraft: true })
  return entries.sort((a, b) => (positions.value.get(a.record.question_id) ?? 9999) - (positions.value.get(b.record.question_id) ?? 9999)
    || (a.record.id ?? Infinity) - (b.record.id ?? Infinity))
})
const annotatedQuestions = computed(() => [...new Set(sortedRecords.value.map(record => record.question_id))].map(id => ({
  id, label: label({ question_id: id, region: 'question' }) + ' · ' + records.value.filter(record => record.question_id === id).length + '条',
})))
const message = (error, fallback) => error?.response?.data?.error || fallback
const storageKey = sid => `cs408:annotation-draft:${sid}`

function label(annotation) {
  const q = props.questions.find(q => q.id === annotation.question_id)
  const number = props.mode === 'exam' && q ? q.number : (positions.value.get(annotation.question_id) ?? 0) + 1
  const location = annotation.region === 'stem' ? '题干' : annotation.region === 'explanation' ? '解析' : annotation.region.startsWith('option:') ? `选项 ${annotation.region.slice(7)}` : '整题'
  return `第 ${number} 题 · ${location}`
}

function formatTime(value) {
  const date = new Date(/Z$|[+-]\d\d:\d\d$/.test(value) ? value : value.replace(' ', 'T') + 'Z')
  return Number.isNaN(date.getTime()) ? '' : new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }).format(date)
}

async function loadRecords() {
  const sid = props.sessionId
  const epoch = ++loadEpoch
  if (!sid || !props.graded) return
  loading.value = true
  loadError.value = ''
  try {
    const result = await listAnnotations(sid)
    if (!disposed && epoch === loadEpoch && sid === props.sessionId) records.value = result
  } catch (error) {
    if (!disposed && epoch === loadEpoch) loadError.value = message(error, '批注读取失败，请重试')
  } finally {
    if (!disposed && epoch === loadEpoch) loading.value = false
  }
}

watch(() => props.sessionId, sid => {
  records.value = []
  activeId.value = null
  draft.value = null
  pendingSelection.value = null
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey(sid)) || 'null')
    if (saved?.session_id === sid && typeof saved.body === 'string' && props.questions.some(q => q.id === saved.question_id)) {
      draft.value = saved
      panelOpen.value = true
    }
  } catch { storageFailed.value = true }
  void loadRecords()
}, { immediate: true })

watch(draft, value => {
  if (!value) return
  try { localStorage.setItem(storageKey(value.session_id), JSON.stringify(value)) }
  catch { storageFailed.value = true }
}, { deep: true, flush: 'sync' })

function discardStoredDraft(sid) {
  try { localStorage.removeItem(storageKey(sid)) } catch { storageFailed.value = true }
}

async function focusComposer() {
  if (!draft.value) return
  emit('locate', draft.value.question_id)
  panelOpen.value = true
  await nextTick()
  updateLayout()
  await nextTick()
  // Template refs inside v-for are arrays, even with only one composer.
  await (Array.isArray(editor.value) ? editor.value[0] : editor.value)?.focus({ preventScroll: true })
  workspace.value?.querySelector('[data-annotation-entry="draft"]')?.scrollIntoView({ block: 'nearest' })
}

function jumpToAnnotatedQuestion(event) {
  const record = sortedRecords.value.find(record => record.question_id === Number(event.target.value))
  event.target.value = ''
  if (record) void activate(record)
}

function entryStyle(key) {
  const top = sidebarLayout.value.positions[key]
  return top === undefined ? { visibility: 'hidden' } : { top: top + 'px' }
}

async function openComposer(anchor) {
  if (!props.graded || !anchor || saving.value) return
  if (draft.value && (draft.value.body.trim() || draft.value.id)) {
    ElMessage.info('请先保存或取消正在编辑的批注')
    await focusComposer()
    return
  }
  draft.value = { ...anchor, session_id: props.sessionId, body: anchor.id ? anchor.body : '', client_id: anchor.client_id || globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}` }
  activeId.value = anchor.id || null
  saveError.value = ''
  panelOpen.value = true
  pendingSelection.value = null
  window.getSelection()?.removeAllRanges()
  await focusComposer()
}

function cancelDraft() {
  if (saving.value) return
  discardStoredDraft(draft.value.session_id)
  draft.value = null
  saveError.value = ''
}

function replaceRecord(record) {
  const index = records.value.findIndex(item => item.id === record.id)
  if (index < 0) records.value.push(record)
  else records.value[index] = record
}

async function saveDraft() {
  if (saving.value || !draft.value?.body.trim()) return
  const { session_id: sid, id, ...payload } = draft.value
  saving.value = true
  saveError.value = ''
  try {
    const saved = id ? await editAnnotation(sid, id, { body: payload.body }) : await addAnnotation(sid, payload)
    discardStoredDraft(sid)
    if (!disposed && props.sessionId === sid) {
      replaceRecord(saved)
      draft.value = null
      activeId.value = saved.id
    }
  } catch (error) {
    if (!disposed && props.sessionId === sid) saveError.value = message(error, '保存失败，批注草稿已保留，请重试')
  } finally { if (!disposed) saving.value = false }
}

async function setResolved(record) {
  if (busyId.value !== null) return
  const sid = props.sessionId
  busyId.value = record.id
  try {
    const saved = await editAnnotation(sid, record.id, { resolved: !record.resolved })
    if (!disposed && sid === props.sessionId) replaceRecord(saved)
  } catch (error) { ElMessage.error(message(error, '更新失败，原批注已保留')) }
  finally { busyId.value = null }
}

async function remove(record) {
  const sid = props.sessionId
  try {
    await ElMessageBox.confirm('删除这条批注？', '删除批注', { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' })
    busyId.value = record.id
    await deleteAnnotation(sid, record.id)
    if (!disposed && sid === props.sessionId) {
      records.value = records.value.filter(item => item.id !== record.id)
      if (activeId.value === record.id) activeId.value = null
      if (draft.value?.id === record.id) cancelDraft()
    }
  } catch (error) { if (error !== 'cancel' && error !== 'close') ElMessage.error(message(error, '删除失败，批注仍然保留')) }
  finally { busyId.value = null }
}

async function activate(record) {
  activeId.value = record.id
  panelOpen.value = true
  emit('locate', record.question_id)
  await nextTick()
  await nextTick()
  if (disposed) return
  const element = regionElement(paperContent.value, record)
  const target = element || regionElement(paperContent.value, { ...record, region: 'question' })
  if (!target) return
  const details = element?.closest('details')
  if (details) details.open = true
  const range = rangeForAnchor(element, record)
  const rect = range?.getBoundingClientRect() || target.getBoundingClientRect()
  if (!range && record.region !== 'question') ElMessage.info('原文位置有变化，已定位到对应题目；批注内容仍保留')
  window.scrollBy({ top: rect.top - window.innerHeight * 0.3, behavior: 'smooth' })
  schedulePaint()
}

function hitAnnotation(event) {
  return [...records.value].reverse().find(record => (!record.resolved || activeId.value === record.id) && pointInRange(ranges.get(record.id), event.clientX, event.clientY))
}

provide(PAPER_ANNOTATIONS, {
  enabled: computed(() => props.graded),
  startQuestion: question_id => openComposer({ question_id, region: 'question', quote: '', start_offset: null, end_offset: null, prefix: '', suffix: '' }),
  countForQuestion: questionId => records.value.filter(item => item.question_id === questionId).length,
  ignoreAnswerClick: event => props.graded && (!!selectionAnchor(paperContent.value) || !!hitAnnotation(event)),
})

function captureSelection() {
  if (disposed) return
  pendingSelection.value = props.graded ? selectionAnchor(paperContent.value) : null
  scheduleLayout()
}

function onPointerUp(event) {
  if (!props.graded) return
  captureSelection()
  if (!pendingSelection.value) {
    const found = hitAnnotation(event)
    if (found) void activate(found)
  }
}

function updateLayout() {
  layoutFrame = 0
  if (disposed) return
  if (annotationList.value && props.graded && panelOpen.value) {
    const base = annotationList.value.getBoundingClientRect()
    const entries = sidebarEntries.value.flatMap(entry => {
      const question = regionElement(paperContent.value, { question_id: entry.record.question_id, region: 'question' })
      const card = annotationList.value.querySelector(`[data-annotation-entry="${entry.key}"]`)
      return question && card ? [{ key: entry.key, anchorTop: question.getBoundingClientRect().top - base.top, height: card.getBoundingClientRect().height }] : []
    })
    sidebarLayout.value = placeAnnotations(entries)
  }
  const targets = new Set([workspace.value, paperContent.value,
    ...(paperContent.value?.querySelectorAll('[data-question-id]') || []),
    ...(annotationList.value?.querySelectorAll('[data-annotation-entry]') || [])].filter(Boolean))
  for (const node of observedElements) if (!targets.has(node)) { resizeObserver?.unobserve(node); observedElements.delete(node) }
  for (const node of targets) if (!observedElements.has(node)) { resizeObserver?.observe(node); observedElements.add(node) }
  if (pendingSelection.value) {
    const range = rangeForAnchor(regionElement(paperContent.value, pendingSelection.value), pendingSelection.value)
    const rect = range?.getBoundingClientRect()
    if (rect && rect.bottom > 0 && rect.top < window.innerHeight) {
      toolbarStyle.value = { left: `${Math.max(8, Math.min(rect.left, window.innerWidth - 150))}px`, top: `${Math.min(rect.bottom + 8, window.innerHeight - 48)}px` }
    } else pendingSelection.value = null
  }
  connector.value = ''
  if (!props.graded || !panelOpen.value || !activeId.value || draft.value) return
  const card = workspace.value?.querySelector(`[data-comment-id="${activeId.value}"]`)
  const from = ranges.get(activeId.value)?.getClientRects()?.[0]
  if (!card || !from?.width || from.bottom < 45 || from.top > innerHeight) return
  const base = workspace.value.getBoundingClientRect()
  const to = card.getBoundingClientRect()
  const x1 = from.right - base.left + 3
  const y1 = from.top - base.top - 2
  const x2 = to.left - base.left
  const y2 = to.top - base.top + 24
  const middle = x2 - 12
  connector.value = `M ${x1} ${y1} H ${middle} V ${y2} H ${x2}`
}

function scheduleLayout() {
  if (!disposed && !layoutFrame) layoutFrame = requestAnimationFrame(updateLayout)
}

function schedulePaint() {
  if (disposed || paintFrame) return
  paintFrame = requestAnimationFrame(() => {
    paintFrame = 0
    if (!paperContent.value || disposed) return
    observer?.disconnect()
    ranges = paintHighlights(paperContent.value, props.graded ? records.value : [], activeId.value, props.graded ? draft.value : null)
    observer?.observe(paperContent.value, { subtree: true, childList: true, characterData: true })
    scheduleLayout()
  })
}

watch([records, activeId, () => props.renderKey, panelOpen], () => nextTick(schedulePaint), { deep: true, flush: 'post' })
watch(sidebarEntries, () => nextTick(scheduleLayout), { flush: 'post' })
watch(() => draft.value ? [draft.value.question_id, draft.value.region, draft.value.quote, draft.value.start_offset, draft.value.end_offset].join('|') : '', schedulePaint)
watch(() => props.graded, value => {
  if (value) { panelOpen.value = true; void loadRecords() }
  else { panelOpen.value = false; pendingSelection.value = null }
  schedulePaint()
})

onMounted(() => {
  observer = new MutationObserver(schedulePaint)
  observer.observe(paperContent.value, { subtree: true, childList: true, characterData: true })
  resizeObserver = new ResizeObserver(scheduleLayout)
  scheduleLayout()
  document.addEventListener('selectionchange', captureSelection)
  window.addEventListener('scroll', scheduleLayout, true)
  window.addEventListener('resize', scheduleLayout)
  document.fonts?.ready.then(schedulePaint)
  schedulePaint()
})

onBeforeUnmount(() => {
  disposed = true
  loadEpoch++
  observer?.disconnect()
  resizeObserver?.disconnect()
  cancelAnimationFrame(paintFrame)
  cancelAnimationFrame(layoutFrame)
  document.removeEventListener('selectionchange', captureSelection)
  window.removeEventListener('scroll', scheduleLayout, true)
  window.removeEventListener('resize', scheduleLayout)
  clearHighlights(paperContent.value)
})
</script>

<style scoped>
.annotation-tools { display: flex; align-items: center; justify-content: space-between; gap: 12px; max-width: 820px; margin: 0 auto 10px; font-size: 12px; color: #6d675d; }
.annotation-toggle { display: inline-flex; align-items: center; gap: 5px; flex-shrink: 0; padding: 6px 10px; border: 1px solid #cfb5a7; border-radius: 6px; color: #91422d; background: #fdfdfb; cursor: pointer; }
.annotation-toggle svg, .annotation-selection-toolbar svg { width: 16px; height: 16px; }
.unsaved-dot { width: 6px; height: 6px; border-radius: 50%; background: #b8791d; }
.annotation-workspace { position: relative; max-width: 820px; margin: auto; }
.annotation-paper { min-width: 0; }
.annotation-sidebar { position: relative; min-width: 0; align-self: start; z-index: 5; }
.annotation-sidebar-header { display: flex; justify-content: space-between; align-items: center; padding: 14px 16px; background: #fffdf9; border: 1px solid #e4ddd4; border-radius: 8px; }
.annotation-sidebar-header strong { font-size: 16px; }.annotation-sidebar-header strong span { margin-left: 6px; color: #9b8070; font-size: 13px; }
.annotation-sidebar-header p { margin-top: 3px; color: #8b8074; font-size: 11px; }
.annotation-close { border: 0; background: transparent; padding: 5px; color: #786b60; cursor: pointer; }.annotation-close svg { width: 18px; height: 18px; }
.annotation-index { display: flex; align-items: center; gap: 10px; margin: 12px 0; color: #827363; font-size: 12px; }
.annotation-index select { flex: 1; min-width: 0; padding: 6px 8px; border: 1px solid #d8cfc5; border-radius: 5px; background: #fffdf9; color: #67584a; }
.annotation-resume { margin: 8px 0; color: #a6452e; font-size: 12px; cursor: pointer; }
.annotation-list { position: relative; margin-top: 12px; }
.annotation-entry { position: absolute; left: 0; right: 0; }
.annotation-empty { padding: 14px 5px; font-size: 13px; color: #8a7d6f; line-height: 1.9; }
.annotation-card, .annotation-composer { border: 1px solid #e3dbd2; background: #fffdf9; border-radius: 7px; padding: 12px; overflow-wrap: anywhere; }
.annotation-card-active, .annotation-composer { border-color: #c76750; box-shadow: 0 0 0 1px #c767501a; }
.annotation-card-resolved { background: #f5f6f2; }.annotation-card-resolved .annotation-body { color: #6b7264; }
.annotation-card-heading { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; font-size: 11px; color: #766759; }.annotation-card-heading strong { color: #4b4037; font-weight: 600; }.annotation-card-heading time { margin-left: auto; font-size: 10px; color: #8d847a; }
.annotation-avatar { display: inline-flex; align-items: center; justify-content: center; background: #b4533c; color: white; border-radius: 50%; width: 22px; height: 22px; font-size: 11px; }
.annotation-quote { display: block; text-align: left; width: 100%; margin-top: 9px; color: #967154; font-size: 12px; cursor: pointer; }.annotation-quote:hover { color: #b04a2f; }
.annotation-source-quote { border-left: 2px solid #d4aa87; padding: 4px 8px; background: #faf5ee; color: #80654e; font-size: 12px; line-height: 1.65; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; white-space: pre-wrap; }
.annotation-composer .annotation-source-quote { margin: 10px 0; }
.annotation-body { margin: 12px 0; font-size: 13px; line-height: 1.8; color: #342f28; }
.annotation-card-actions, .annotation-editor-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; font-size: 11px; }.annotation-card-actions { padding-top: 9px; border-top: 1px solid #f0ebe4; justify-content: flex-end; }
.annotation-card-actions button, .annotation-editor-actions button { cursor: pointer; color: #966851; }.annotation-card-actions button:hover { text-decoration: underline; }.annotation-sidebar button:disabled { opacity: .5; cursor: default; }
.annotation-resolved-label { color: #6b845b; margin-right: auto; }
.annotation-composer .markdown-editor { margin-top: 10px; }
.annotation-editor-actions { margin-top: 8px; }.annotation-editor-actions .annotation-save { padding: 6px 10px; background: #b04a2f; color: white; border-radius: 5px; font-size: 12px; }
.annotation-draft-hint { margin-top: 9px; font-size: 10px; line-height: 1.6; color: #958471; }
.annotation-error { margin: 8px 0; font-size: 12px; color: #b63b2d; line-height: 1.7; }.annotation-error button { text-decoration: underline; cursor: pointer; }
.annotation-connector { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; overflow: visible; z-index: 2; }.annotation-connector path { fill: none; stroke: #c86d55; stroke-width: 1; }
.annotation-selection-toolbar { position: fixed; z-index: 2100; background: #fffdf9; border: 1px solid #cba995; border-radius: 7px; box-shadow: 0 4px 16px #35231824; }.annotation-selection-toolbar button { display: flex; gap: 6px; align-items: center; padding: 8px 12px; color: #9e432c; font-size: 13px; cursor: pointer; }
.annotation-tools-wide, .annotation-workspace-open { max-width: 1164px; }
.annotation-workspace-open { display: grid; grid-template-columns: minmax(0, 820px) 320px; gap: 24px; }
</style>
