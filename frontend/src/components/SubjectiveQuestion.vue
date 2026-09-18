<template>
  <article class="border-b border-[#f0ece3] py-4" :data-question-id="question.id">
    <div class="mb-1.5 flex items-center gap-2">
      <span class="font-song text-[16px] font-bold">{{ displayNo }}.</span>
      <span class="rounded bg-primary-soft px-1.5 text-[12px] text-primary">大题 · {{ question.subject || '综合' }}</span>
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

    <MarkdownContent v-if="result" :source="answerText || '未填写文字作答'" aria-label="我的作答" class="mt-3 rounded-lg border border-line bg-[#f6f4ef] p-3 text-sm" />
    <MarkdownEditor
      v-else
      v-model="answerText"
      :disabled="loading"
      aria-label="主观题作答"
      :rows="6"
      placeholder="在此写出你的作答（设计思想 / 步骤 / 关键代码要点…）；也可先在草稿纸手写、拍照上传，这里写要点让 AI 批改"
      class="mt-3"
    />

    <div class="mt-2 flex flex-wrap items-center gap-2">
      <el-button type="primary" size="small" :loading="loading" :disabled="!answerText.trim() || !!result" @click="doGrade">
        {{ loading ? 'AI 批改中…' : 'AI 批改' }}
      </el-button>
      <span v-if="loading" class="text-xs text-muted" role="status">AI 正在批改，请稍候，最长约 2 分钟</span>
      <span v-if="result" class="badge" :class="badgeClass">{{ result.verdict }} · 得分 {{ ratioText }}</span>
    </div>

    <div v-if="result" class="mt-3 grid gap-3">
      <div class="rounded-lg border border-line bg-[#faf8f4] p-3 text-sm leading-6">
        <div class="mb-1 font-semibold text-muted">AI 点评</div>
        <MarkdownContent :source="result.comment" />
      </div>
      <details class="rounded-lg border border-line bg-white p-3">
        <summary class="cursor-pointer text-sm font-semibold text-primary">查看参考答案</summary>
        <div class="qhtml mt-2 text-sm leading-7" data-annotation-region="explanation" v-html="result.reference_html"></div>
      </details>
    </div>
    <p v-if="error" class="mt-2 text-sm text-bad">{{ error }}</p>
  </article>
</template>

<script setup>
import { ref, computed } from 'vue'
import { usePaperStore } from '@/stores/paper'
import { gradeSubjective, getSession } from '@/api/cs408/quiz'
import { gradingErrorMessage } from '@/utils/gradingError'
import { questionSource } from '@/utils/questionSource'
import QuestionAnnotationButton from './QuestionAnnotationButton.vue'
import MarkdownEditor from '@/components/MarkdownEditor.vue'
import MarkdownContent from '@/components/MarkdownContent.vue'

const props = defineProps({
  question: { type: Object, required: true },
  index: { type: Number, default: 0 },
})
const store = usePaperStore()

// 从本场做题记录恢复：已作答/已批改则回填
const item = computed(() => store.items?.[props.question.id] || {})
const answerText = computed({
  get: () => item.value.answer_text || '',
  set: (value) => store.patchLocalItem(props.question.id, { answer_text: value }),
})
const loading = ref(false)
const result = computed(() => item.value.verdict ? item.value : null)
const error = ref('')

const mode = computed(() => store.mode)
const hasDraft = computed(() => !!store.items?.[props.question.id]?.draft_url)
const displayNo = computed(() => (mode.value === 'exam' ? props.question.number : props.index + 1))
const origin = computed(() => questionSource(props.question))
const ratioText = computed(() =>
  result.value && result.value.score_ratio != null ? Math.round(result.value.score_ratio * 100) + '%' : '—',
)
const badgeClass = computed(() => {
  const v = result.value?.verdict
  return v === '对' ? 'badge-ok' : v === '错' ? 'badge-bad' : 'badge-fuzzy'
})

async function doGrade() {
  if (loading.value || result.value) return
  if (!store.sessionId) {
    error.value = '尚未进入做题'
    return
  }
  loading.value = true
  error.value = ''
  const sid = store.sessionId
  const qid = props.question.id
  const student = answerText.value.trim()
  const applyResult = (r) => {
    if (store.sessionId === sid) store.patchLocalItem(qid, { answer_text: student, ...r })
  }
  try {
    applyResult(await gradeSubjective(sid, qid, student))
  } catch (e) {
    // 连接中断时后端可能已完成；恢复该题结果，不覆盖卷内其他未保存内容。
    if (!e?.response || [409, 504, 524].includes(e.response.status)) {
      try {
        const saved = (await getSession(sid)).items?.[qid]
        if (saved?.verdict) {
          applyResult(saved)
          return
        }
      } catch { /* 保留原始批改错误。 */ }
    }
    error.value = gradingErrorMessage(e)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.iconbtn { background: none; border: none; padding: 0 3px; font-size: 14px; line-height: 1; opacity: 0.45; cursor: pointer; transition: 0.12s; }
.iconbtn:hover { opacity: 1; }
.iconbtn-on { opacity: 1; color: #2f7d47; }
.badge { font-size: 12px; padding: 2px 9px; border-radius: 20px; font-weight: 600; }
.badge-ok { background: #e3f1e6; color: #2f7d47; }
.badge-bad { background: #f7e3e2; color: #c23b3b; }
.badge-fuzzy { background: #f6ecd7; color: #b8791d; }
</style>
