<template>
  <el-drawer
    :model-value="!!store.noteQid"
    direction="rtl"
    size="min(460px, 100vw)"
    :with-header="false"
    @update:model-value="store.openNote(null)"
  >
    <div v-if="store.noteQid" class="flex h-full flex-col">
      <div class="mb-2 border-b border-line pb-2">
        <div class="font-song text-[16px] font-bold">本题笔记</div>
        <div class="text-[12px] text-muted">
          {{ meta }} · 共 {{ notes.length }} 条（跨真题/强化累积，笔记库里也能看到）
        </div>
      </div>

      <div v-if="loading" class="py-8 text-center text-sm text-muted">加载中...</div>

      <ul v-else class="flex-1 overflow-y-auto pr-1">
        <li
          v-for="n in notes"
          :key="n.id"
          v-loading="uploadingNoteId === n.id"
          class="mb-2 rounded-lg border border-line bg-[#faf8f4] p-2"
        >
          <MarkdownEditor
            v-model="n.body"
            rows="3"
            aria-label="编辑笔记"
            start-preview
            placeholder="编辑笔记，可按 Ctrl+V / ⌘V 粘贴图片"
            @paste="onExistingPaste($event, n)"
            @blur="onEdit(n)"
          />
          <NoteImageGallery
            :images="n.images"
            removable
            :busy-id="deletingImageId"
            @remove="onDeleteImage(n, $event)"
          />
          <div class="mt-1 flex items-center justify-between gap-2 text-[11px] text-muted">
            <span>{{ fmt(n.updated_at || n.created_at) }}</span>
            <div class="flex shrink-0 items-center gap-1">
              <NoteImagePicker :disabled="uploadingNoteId !== null" @select="onExistingImages($event, n)" />
              <el-tooltip content="导出笔记 PNG" placement="top">
                <button type="button" class="note-toolbar-icon" aria-label="导出笔记 PNG" @click="onExport(n)">
                  <el-icon><Download /></el-icon>
                </button>
              </el-tooltip>
              <el-tooltip content="删除笔记" placement="top">
                <button type="button" class="note-toolbar-icon note-toolbar-delete" aria-label="删除笔记" @click="onDelete(n)">
                  <el-icon><Delete /></el-icon>
                </button>
              </el-tooltip>
            </div>
          </div>
        </li>
        <li v-if="!notes.length" class="py-6 text-center text-sm text-muted">还没有笔记，在下面写第一条。</li>
      </ul>

      <div :key="store.noteQid" class="mt-2 border-t border-line pt-2">
        <MarkdownEditor
          v-model="draft"
          rows="3"
          aria-label="新增笔记"
          placeholder="新增一条笔记，也可直接粘贴图片…"
          :disabled="saving"
          @paste="onDraftPaste"
        />
        <p class="mt-1 text-[11px] text-muted">支持 Ctrl+V / ⌘V 粘贴图片，也可只添加图片。</p>
        <div v-if="pendingImages.length" class="note-pending-grid">
          <div v-for="(item, index) in pendingImages" :key="item.previewUrl" class="note-pending-item">
            <img :src="item.previewUrl" alt="待上传图片" />
            <button type="button" :disabled="saving" :aria-label="`移除第 ${index + 1} 张图片`" title="移除图片" @click="removePending(index)">
              <el-icon><Close /></el-icon>
            </button>
          </div>
        </div>
        <div class="mt-1.5 flex items-center gap-2">
          <el-button type="primary" size="small" :loading="saving" :disabled="!canAdd" @click="onAdd">添加</el-button>
          <NoteImagePicker :disabled="saving" @select="addPending" />
          <span class="text-[11px] text-muted">{{ pendingImages.length }}/{{ NOTE_IMAGE_LIMIT }}</span>
          <el-button class="ml-auto" size="small" text @click="store.openNote(null)">关闭</el-button>
        </div>
      </div>
    </div>
  </el-drawer>
</template>

<script setup>
import { ref, computed, watch, onUnmounted } from 'vue'
import { Close, Delete, Download } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { usePaperStore } from '@/stores/paper'
import NoteImageGallery from '@/components/NoteImageGallery.vue'
import NoteImagePicker from '@/components/NoteImagePicker.vue'
import MarkdownEditor from '@/components/MarkdownEditor.vue'
import { questionSource } from '@/utils/questionSource'
import {
  listNotes, addNote, editNote, deleteNote, addNoteImages, deleteNoteImage,
} from '@/api/cs408/quiz'
import {
  NOTE_IMAGE_LIMIT, clipboardImageFiles, exportNoteAsPng, filesToNotePayload,
  makePendingImages, releasePendingImages, validateNoteImageFiles,
} from '@/utils/noteImages'

const store = usePaperStore()
const notes = ref([])
const loading = ref(false)
const saving = ref(false)
const draft = ref('')
const pendingImages = ref([])
const deletingImageId = ref(null)
const uploadingNoteId = ref(null)

const canAdd = computed(() => !saving.value && (!!draft.value.trim() || pendingImages.value.length > 0))
const meta = computed(() => {
  const q = store.questions.find((item) => item.id === store.noteQid)
  if (!q) return ''
  return `${questionSource(q)} 第 ${q.number} 题`
})

function fmt(value) {
  return (value || '').replace('T', ' ').slice(5, 16)
}

function clearPending() {
  releasePendingImages(pendingImages.value)
  pendingImages.value = []
}

function addPending(files) {
  if (saving.value) return 0
  try {
    const currentBytes = pendingImages.value.reduce((sum, item) => sum + item.file.size, 0)
    const valid = validateNoteImageFiles(files, pendingImages.value.length, currentBytes)
    pendingImages.value.push(...makePendingImages(valid))
    return valid.length
  } catch (error) {
    ElMessage.warning(error.message)
    return 0
  }
}

function onDraftPaste(event) {
  const files = clipboardImageFiles(event)
  if (!files.length) return
  event.preventDefault()
  const added = addPending(files)
  if (added) ElMessage.success(`已粘贴 ${added} 张图片`)
}

function removePending(index) {
  URL.revokeObjectURL(pendingImages.value[index].previewUrl)
  pendingImages.value.splice(index, 1)
}

async function uploadToNote(note, files) {
  const currentBytes = (note.images || []).reduce((sum, item) => sum + item.size_bytes, 0)
  const valid = validateNoteImageFiles(files, note.images?.length || 0, currentBytes)
  if (!valid.length) return
  const payload = await filesToNotePayload(valid)
  const updated = await addNoteImages(note.id, payload)
  note.images = updated.images
  note.updated_at = updated.updated_at
}

function onExistingPaste(event, note) {
  const files = clipboardImageFiles(event)
  if (!files.length) return
  event.preventDefault()
  return onExistingImages(files, note)
}

async function onExistingImages(files, note) {
  if (!files.length || uploadingNoteId.value !== null) return
  uploadingNoteId.value = note.id
  try {
    await uploadToNote(note, files)
    ElMessage.success('图片已添加')
  } catch (error) {
    ElMessage.error(error?.response?.data?.error || error.message || '图片上传失败')
  } finally {
    uploadingNoteId.value = null
  }
}

watch(() => store.noteQid, async (qid) => {
  notes.value = []
  draft.value = ''
  clearPending()
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

onUnmounted(clearPending)

async function onAdd() {
  if (!canAdd.value) return
  saving.value = true
  try {
    const images = await filesToNotePayload(pendingImages.value.map((item) => item.file))
    notes.value.push(await addNote({
      question_id: store.noteQid,
      session_id: store.sessionId,
      body: draft.value.trim(),
      images,
    }))
    draft.value = ''
    clearPending()
  } catch (error) {
    ElMessage.error(error?.response?.data?.error || error.message || '笔记保存失败')
  } finally {
    saving.value = false
  }
}

async function onEdit(note) {
  if (!note.body.trim() && !note.images?.length) return
  try {
    Object.assign(note, await editNote(note.id, note.body))
  } catch (error) {
    ElMessage.error(error?.response?.data?.error || '笔记更新失败')
  }
}

async function onDeleteImage(note, image) {
  if (!note.body.trim() && note.images.length === 1) {
    ElMessage.warning('笔记至少需要文字或一张图片')
    return
  }
  deletingImageId.value = image.id
  try {
    if (note.images.length === 1 && note.body.trim()) {
      Object.assign(note, await editNote(note.id, note.body))
    }
    await deleteNoteImage(image.id)
    note.images = note.images.filter((item) => item.id !== image.id)
  } catch (error) {
    ElMessage.error(error?.response?.data?.error || '图片删除失败')
  } finally {
    deletingImageId.value = null
  }
}

async function onDelete(note) {
  try {
    await ElMessageBox.confirm('这条笔记及其图片将被删除。', '删除笔记', {
      confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning',
    })
    await deleteNote(note.id)
    notes.value = notes.value.filter((item) => item.id !== note.id)
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error('笔记删除失败')
  }
}

async function onExport(note) {
  try {
    await exportNoteAsPng(note, meta.value)
  } catch (error) {
    ElMessage.error(error.message || '笔记图片生成失败')
  }
}
</script>

<style scoped>
.note-pending-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px;
  margin-top: 7px;
}
.note-pending-item {
  position: relative;
  overflow: hidden;
  border: 1px solid #ddd7cc;
  border-radius: 5px;
  background: #fff;
  aspect-ratio: 4 / 3;
}
.note-pending-item img { width: 100%; height: 100%; object-fit: contain; }
.note-pending-item button {
  position: absolute;
  top: 4px;
  right: 4px;
  display: inline-flex;
  width: 26px;
  height: 26px;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  background: rgb(38 34 28 / 88%);
  color: #fff;
}
.note-toolbar-icon {
  display: inline-flex;
  width: 30px;
  height: 30px;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  color: #b04a2f;
  cursor: pointer;
}
.note-toolbar-icon:hover { background: #f3e4de; }
.note-toolbar-delete { color: #c23b3b; }
.note-toolbar-delete:hover { background: #f7e3e2; }
</style>
