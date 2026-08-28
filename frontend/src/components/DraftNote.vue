<template>
  <div class="flex flex-col gap-3">
    <!-- 草稿纸：本场做题各存一份 -->
    <div class="flex flex-col gap-1.5 text-xs text-muted">
      <label class="cursor-pointer">
        📷 上传草稿纸（本次作答）：<span class="text-primary underline">选择图片</span>
        <input type="file" accept="image/*" class="hidden" @change="onFile" />
      </label>
      <img
        v-if="draftUrl"
        :src="draftUrl"
        alt="草稿纸"
        class="max-h-40 max-w-[220px] rounded border border-line"
      />
    </div>

    <!-- 笔记：一题多条，跨卷聚合（看题时都能看到） -->
    <div>
      <div class="mb-1 text-xs font-semibold text-muted">
        个人笔记 · 本题共 {{ notes.length }} 条（跨套卷/强化累积）
      </div>

      <div v-if="loading" class="text-xs text-muted">加载笔记…</div>

      <ul v-else class="flex flex-col gap-2">
        <li
          v-for="n in notes"
          :key="n.id"
          class="rounded-lg border border-line bg-[#faf8f4] p-2 text-sm"
        >
          <textarea
            v-model="n.body"
            class="w-full resize-y rounded border border-transparent bg-transparent p-1 leading-6 outline-none focus:border-line focus:bg-white"
            rows="2"
            @blur="onEdit(n)"
          />
          <div class="mt-1 flex items-center justify-between text-[11px] text-muted">
            <span>{{ fmt(n.created_at) }}</span>
            <button type="button" class="text-bad hover:underline" @click="onDelete(n)">删除</button>
          </div>
        </li>
      </ul>

      <div class="mt-2 flex gap-2">
        <textarea
          v-model="draftBody"
          placeholder="新增一条笔记…（比如这次的错因、易混点、解题套路）"
          class="min-h-14 flex-1 rounded-lg border border-line p-2 text-sm outline-none focus:border-primary"
        />
        <el-button type="primary" size="small" :disabled="!draftBody.trim()" @click="onAdd">添加</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { usePaperStore } from '@/stores/paper'
import { saveDraft, listNotes, addNote, editNote, deleteNote } from '@/api/cs408/quiz'

// 每题的「草稿纸（本场一份）+ 个人笔记（一题多条、跨卷聚合）」。
const props = defineProps({ question: { type: Object, required: true } })
const store = usePaperStore()

const draftUrl = ref(store.items?.[props.question.id]?.draft_url || '')
const notes = ref([])
const loading = ref(true)
const draftBody = ref('')
const qid = computed(() => props.question.id)

onMounted(async () => {
  try {
    notes.value = await listNotes(qid.value)
  } catch {
    ElMessage.error('笔记加载失败')
  } finally {
    loading.value = false
  }
})

function fmt(s) {
  return (s || '').replace('T', ' ').slice(5, 16)
}

function onFile(e) {
  const file = e.target.files?.[0]
  if (!file) return
  if (!store.sessionId) return ElMessage.error('尚未进入做题，无法上传草稿')
  const reader = new FileReader()
  reader.onload = async () => {
    draftUrl.value = reader.result
    try {
      const r = await saveDraft(store.sessionId, qid.value, reader.result)
      if (r.draft_url) {
        draftUrl.value = r.draft_url
        store.patchLocalItem(qid.value, { draft_url: r.draft_url })
      }
    } catch {
      ElMessage.error('草稿纸上传失败')
    }
  }
  reader.readAsDataURL(file)
}

async function onAdd() {
  const body = draftBody.value.trim()
  if (!body) return
  try {
    const n = await addNote({ question_id: qid.value, session_id: store.sessionId, body })
    notes.value.push(n)
    draftBody.value = ''
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
