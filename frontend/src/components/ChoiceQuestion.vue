<template>
  <article class="border-b border-[#f0ece3] py-4" :class="gradedClass" :data-question-id="question.id">
    <div class="mb-1.5 flex items-center gap-2">
      <span class="font-song text-[16px] font-bold">{{ displayNo }}.</span>
      <button
        type="button"
        class="tri"
        :class="{ 'tri-on': answer.fuzzy }"
        :disabled="editingDisabled"
        :title="answer.fuzzy ? '已标模糊（点此取消）' : '标记模糊（拿不准）'"
        @click="store.toggleFuzzy(question.id)"
      >{{ answer.fuzzy ? '▲' : '△' }}</button>
      <button
        type="button"
        class="iconbtn"
        :class="{ 'iconbtn-on': hasDraft }"
        :title="hasDraft ? '已有草稿纸（点开查看/追加）' : '上传草稿纸（手机扫码拍照）'"
        @click="store.openDraft(question.id)"
      >📷<span v-if="hasDraft" class="ml-0.5 text-[11px]">✓</span></button>
      <button type="button" class="iconbtn" title="本题笔记（右侧打开）" @click="store.openNote(question.id)">📝</button>
      <QuestionAnnotationButton :question-id="question.id" :number="displayNo" />
    </div>
    <div class="qhtml font-song text-[16px] leading-[1.9]">
      <span v-if="mode === 'reinforce'" class="text-muted">[{{ origin }}] </span>
      <span data-annotation-region="stem" v-html="question.stem_html"></span>
    </div>

    <!-- 知识点：交卷后才显示，考试时不剧透 -->
    <div v-if="graded && tagList.length" class="mt-2">
      <span
        v-for="t in tagList"
        :key="t"
        class="mr-1.5 inline-block rounded-full bg-primary-soft px-2 py-0.5 text-[11px] text-primary"
      >{{ t }}</span>
    </div>

    <div class="mt-2.5 grid grid-cols-2 gap-x-5 gap-y-2">
      <button
        v-for="o in question.options"
        :key="o.key"
        type="button"
        class="flex items-start gap-2.5 rounded-lg border px-3 py-2 text-left transition font-song"
        :class="optClass(o.key)"
        :disabled="editingDisabled"
        @click="choose(o.key, $event)"
      >
        <span class="min-w-[18px] font-bold">{{ o.key }}</span>
        <span class="qhtml" :data-annotation-region="`option:${o.key}`" v-html="o.text"></span>
      </button>
    </div>

    <div v-if="graded && result" class="mt-2">
      <span class="badge" :class="badgeClass">{{ badgeText }}</span>
    </div>
    <details v-if="graded && result?.reference_html" class="mt-3 rounded-lg border border-line bg-white p-3">
      <summary class="cursor-pointer text-sm font-semibold text-primary">查看解析</summary>
      <div class="qhtml question-explanation mt-2 text-sm leading-7" data-annotation-region="explanation" v-html="result.reference_html"></div>
      <a v-if="question.source_url" :href="question.source_url" target="_blank" rel="noopener noreferrer" class="mt-2 inline-block text-xs text-primary underline">
        原题来源：{{ origin }} · 第 {{ question.number }} 题
      </a>
    </details>
  </article>
</template>

<script setup>
import { computed, inject } from 'vue'
import { usePaperStore } from '@/stores/paper'
import { questionSource } from '@/utils/questionSource'
import QuestionAnnotationButton from './QuestionAnnotationButton.vue'
import { PAPER_ANNOTATIONS } from '@/utils/annotationAnchors'

const props = defineProps({
  question: { type: Object, required: true },
  index: { type: Number, default: 0 },
})
const store = usePaperStore()
const annotations = inject(PAPER_ANNOTATIONS, null)

const mode = computed(() => store.mode)
const graded = computed(() => store.graded)
const editingDisabled = computed(() => store.graded || store.grading)
const answer = computed(() => store.answers[props.question.id] || { chosen: '', fuzzy: false })
const result = computed(() => store.results[props.question.id])
const hasDraft = computed(() => !!store.items?.[props.question.id]?.draft_url)
const displayNo = computed(() => (mode.value === 'exam' ? props.question.number : props.index + 1))
const origin = computed(() => questionSource(props.question))
const tagList = computed(() => (props.question.tags || '').split(/[,，]/).filter(Boolean))

function choose(key, event) {
  if (annotations?.ignoreAnswerClick(event)) return
  store.setChosen(props.question.id, key)
}

function optClass(k) {
  if (!graded.value) {
    return answer.value.chosen === k
      ? 'border-primary bg-primary-soft'
      : editingDisabled.value
        ? 'cursor-not-allowed border-line bg-white opacity-70'
        : 'border-line bg-white hover:border-primary hover:bg-primary-soft'
  }
  const r = result.value
  if (!r) return 'border-line bg-white'
  if (k === r.answer) return 'border-ok bg-ok-soft'
  if (k === r.chosen && !r.is_correct) return 'border-bad bg-bad-soft'
  return 'border-line bg-white'
}

const gradedClass = computed(() => {
  const r = result.value
  if (!graded.value || !r) return ''
  return r.is_correct ? 'bg-gradient-to-r from-ok-soft to-transparent' : 'bg-gradient-to-r from-bad-soft to-transparent'
})
const badgeText = computed(() => {
  const r = result.value
  if (!r) return ''
  const label = r.is_correct ? (r.result === 'fuzzy' ? '蒙对/模糊' : '✓ 正确') : (r.chosen ? '✗ 做错' : '✗ 未作答')
  return `${label} · 正确答案 ${r.answer}`
})
const badgeClass = computed(() => {
  const r = result.value
  if (!r) return ''
  return r.is_correct ? (r.result === 'fuzzy' ? 'badge-fuzzy' : 'badge-ok') : 'badge-bad'
})
</script>
<style scoped>
.tri { background: none; border: none; padding: 0 2px; font-size: 18px; line-height: 1; color: #b9b3a7; cursor: pointer; transition: 0.12s; }
.tri:hover { color: #b8791d; }
.tri:disabled { cursor: default; }
.tri-on { color: #b8791d; }
.iconbtn { background: none; border: none; padding: 0 3px; font-size: 14px; line-height: 1; opacity: 0.45; cursor: pointer; transition: 0.12s; }
.iconbtn:hover { opacity: 1; }
.iconbtn-on { opacity: 1; color: #2f7d47; }
.badge { font-size: 12px; padding: 2px 9px; border-radius: 20px; font-weight: 600; }
.badge-ok { background: #e3f1e6; color: #2f7d47; }
.badge-bad { background: #f7e3e2; color: #c23b3b; }
.badge-fuzzy { background: #f6ecd7; color: #b8791d; }
.question-explanation :deep(p + p) { margin-top: 8px; }
.question-explanation :deep(ul) { list-style: disc; padding-left: 1.5em; }
.question-explanation :deep(ol) { list-style: decimal; padding-left: 1.5em; }
.question-explanation :deep(h3), .question-explanation :deep(h4) { margin-top: 8px; font-weight: 600; }
</style>
