<template>
  <article class="border-b border-[#f0ece3] py-4">
    <div class="qhtml font-song text-[16px] leading-[1.9]">
      <span class="mr-1.5 font-bold">{{ displayNo }}.</span>
      <span v-if="mode === 'reinforce' && question.year" class="text-muted">[{{ question.year }}] </span>
      <span class="mr-1.5 align-middle rounded bg-primary-soft px-1.5 text-[12px] text-primary">大题 · {{ question.subject }}</span>
      <span v-html="question.stem_html"></span>
    </div>

    <textarea
      v-model="answerText"
      :disabled="loading || !!result"
      placeholder="在此写出你的作答（设计思想 / 步骤 / 关键代码要点…）；也可先在草稿纸手写、拍照上传，这里写要点让 AI 批改"
      class="mt-3 min-h-32 w-full rounded-lg border border-line p-3 text-sm leading-6 outline-none focus:border-primary disabled:bg-[#f6f4ef]"
    />

    <div class="mt-2 flex flex-wrap items-center gap-2">
      <el-button type="primary" size="small" :loading="loading" :disabled="!answerText.trim() || !!result" @click="doGrade">
        {{ loading ? 'AI 批改中…' : 'AI 批改' }}
      </el-button>
      <button type="button" class="chip" @click="open = !open">📝 草稿 / 笔记</button>
      <span v-if="result" class="badge" :class="badgeClass">{{ result.verdict }} · 得分 {{ ratioText }}</span>
    </div>

    <div v-if="open" class="mt-2"><DraftNote :question="question" /></div>

    <div v-if="result" class="mt-3 grid gap-3">
      <div class="rounded-lg border border-line bg-[#faf8f4] p-3 text-sm leading-6">
        <div class="mb-1 font-semibold text-muted">AI 点评</div>
        <div>{{ result.comment }}</div>
      </div>
      <details class="rounded-lg border border-line bg-white p-3">
        <summary class="cursor-pointer text-sm font-semibold text-primary">查看参考答案</summary>
        <div class="qhtml mt-2 text-sm leading-7" v-html="result.reference_html"></div>
      </details>
    </div>
    <p v-if="error" class="mt-2 text-sm text-bad">{{ error }}</p>
  </article>
</template>

<script setup>
import { ref, computed } from 'vue'
import { usePaperStore } from '@/stores/paper'
import { gradeSubjective } from '@/api/cs408/quiz'
import DraftNote from './DraftNote.vue'

const props = defineProps({
  question: { type: Object, required: true },
  index: { type: Number, default: 0 },
})
const store = usePaperStore()
const open = ref(false)

// 从本场做题记录恢复：已作答/已批改则回填
const _it = store.items?.[props.question.id] || {}
const answerText = ref(_it.answer_text || '')
const loading = ref(false)
const result = ref(_it.verdict ? { verdict: _it.verdict, comment: _it.comment, reference_html: _it.reference_html } : null)
const error = ref('')

const mode = computed(() => store.mode)
const displayNo = computed(() => (mode.value === 'exam' ? props.question.number : props.index + 1))
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
  try {
    const r = await gradeSubjective(store.sessionId, props.question.id, answerText.value.trim())
    result.value = r
    store.patchLocalItem(props.question.id, {
      answer_text: answerText.value.trim(), verdict: r.verdict,
      comment: r.comment, reference_html: r.reference_html,
    })
  } catch (e) {
    error.value = e?.response?.data?.error || 'AI 批改失败，请确认后端与网关可用'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.chip { font-size: 12px; padding: 5px 11px; border-radius: 20px; border: 1px solid #ddd7cc; background: #fff; color: #6d675d; cursor: pointer; transition: 0.12s; }
.chip:hover { border-color: #b8791d; color: #b8791d; }
.badge { font-size: 12px; padding: 2px 9px; border-radius: 20px; font-weight: 600; }
.badge-ok { background: #e3f1e6; color: #2f7d47; }
.badge-bad { background: #f7e3e2; color: #c23b3b; }
.badge-fuzzy { background: #f6ecd7; color: #b8791d; }
</style>
