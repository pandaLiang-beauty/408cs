<template>
  <el-drawer
    :model-value="!!store.noteQid"
    direction="rtl"
    size="420px"
    :with-header="false"
    @update:model-value="store.openNote(null)"
  >
    <div v-if="store.noteQid" class="flex h-full flex-col">
      <div class="mb-2 border-b border-line pb-2">
        <div class="font-song text-[16px] font-bold">📝 本题笔记</div>
        <div class="text-[12px] text-muted">
          {{ meta }} · 共 {{ notes.length }} 条（跨真题/强化累积，笔记库里也能看到）
        </div>
      </div>

      <div v-if="loading" class="py-8 text-center text-sm text-muted">加载中…</div>

      <ul v-else class="flex-1 overflow-y-auto pr-1">
        <li v-for="n in notes" :key="n.id" class="mb-2 rounded-lg border border-line bg-[#faf8f4] p-2">
          <textarea
            v-model="n.body"
            rows="3"
            class="w-full resize-y rounded border border-transparent bg-transparent p-1 text-sm leading-6 outline-none focus:border-line focus:bg-white"
            @blur="onEdit(n)"
          />
          <div class="mt-1 flex items-center justify-between text-[11px] text-muted">
            <span>{{ fmt(n.created_at) }}</span>
            <button type="button" class="text-bad hover:underline" @click="onDelete(n)">删除</button>
          </div>
        </li>
        <li v-if="!notes.length" class="py-6 text-center text-sm text-muted">还没有笔记，在下面写第一条。</li>
      </ul>

      <div class="mt-2 border-t border-line pt-2">
        <textarea
          v-model="draft"
          rows="3"
          placeholder="新增一条笔记…（这次的错因、易混点、解题套路）"
          class="w-full resize-y rounded-lg border border-line p-2 text-sm outline-none focus:border-primary"
        />
        <div class="mt-1.5 flex items-center gap-2">
          <el-button type="primary" size="small" :disabled="!draft.trim()" @click="onAdd">添加</el-button>
          <el-button size="small" text @click="store.openNote(null)">关闭</el-button>
        </div>
      </div>
    </div>
  </el-drawer>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { usePaperStore } from '@/stores/paper'
import { listNotes, addNote, editNote, deleteNote } from '@/api/cs408/quiz'

// 笔记：右侧抽屉，一题多条，跨卷聚合。与草稿完全分开。
const store = usePaperStore()
const notes = ref([])
const loading = ref(false)
const draft = ref('')

const meta = computed(() => {
  const q = store.questions.find((x) => x.id === store.noteQid)
  if (!q) return ''
  const origin = q.source === 'simulate' ? `模拟卷${q.year}` : `${q.year} 年真题`
  return `${origin} 第 ${q.number} 题`
})

function fmt(s) {
  return (s || '').replace('T', ' ').slice(5, 16)
}

watch(() => store.noteQid, async (qid) => {
  notes.value = []
  draft.value = ''
  if (!qid) return
  loading.value = true
  try {
    notes.value = await listNotes(qid)
  } catch {
    ElMessage.error('笔记加载失败')
  } finally {
    loading.value = false
  }
})

async function onAdd() {
  const body = draft.value.trim()
  if (!body) return
  try {
    notes.value.push(await addNote({ question_id: store.noteQid, session_id: store.sessionId, body }))
    draft.value = ''
  } catch {
    ElMessage.error('笔记保存失败')
  }
}

async function onEdit(n) {
  try {
    await editNote(n.id, n.body)
  } catch {
    ElMessage.error('笔记更新失败')
  }
}

async function onDelete(n) {
  try {
    await deleteNote(n.id)
    notes.value = notes.value.filter((x) => x.id !== n.id)
  } catch {
    ElMessage.error('笔记删除失败')
  }
}
</script>
