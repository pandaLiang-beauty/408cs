<template>
  <main class="px-3.5 pb-24 pt-6">
    <div class="mx-auto max-w-[820px]">
      <h1 class="mb-1 font-song text-[22px] font-bold">📓 笔记库</h1>
      <p class="mb-4 text-sm text-muted">
        按题聚合所有笔记（同一题在真题/强化里写的都汇到一处）。共 {{ groups.length }} 题 · {{ noteCount }} 条笔记。
      </p>

      <div class="mb-4 flex flex-wrap items-center gap-2">
        <input
          v-model="kw"
          placeholder="搜索笔记 / 题干…"
          class="w-56 rounded-lg border border-line px-3 py-1.5 text-sm outline-none focus:border-primary"
        />
        <button
          v-for="s in subjects"
          :key="s"
          type="button"
          class="rounded-full border px-3 py-1 text-xs transition"
          :class="subj === s ? 'border-primary bg-primary-soft text-primary' : 'border-line text-muted hover:border-primary'"
          @click="subj = subj === s ? '' : s"
        >
          {{ s }}
        </button>
      </div>

      <div v-if="loading" class="py-16 text-center text-muted">加载中…</div>
      <p v-else-if="!filtered.length" class="py-16 text-center text-muted">还没有匹配的笔记。做题时点「草稿 / 笔记」即可添加。</p>

      <div v-else class="flex flex-col gap-4">
        <section v-for="g in filtered" :key="g.question_id" class="rounded-md border border-line bg-paper p-4 shadow-sm">
          <div class="mb-1 flex items-center gap-2 text-xs text-muted">
            <span class="rounded bg-bgwarm px-1.5 py-0.5">{{ g.year }} · {{ g.qtype === 'choice' ? '单选' : '综合' }} 第 {{ g.number }} 题</span>
            <span v-if="g.subject">{{ g.subject }}</span>
            <span v-for="t in tagsOf(g)" :key="t" class="rounded-full bg-primary-soft px-2 py-0.5 text-primary">{{ t }}</span>
          </div>
          <div class="qhtml mb-2 line-clamp-2 font-song text-[15px] leading-[1.8] text-ink" v-html="g.stem_html"></div>
          <ul class="flex flex-col gap-1.5">
            <li
              v-for="n in g.notes"
              :key="n.id"
              v-loading="uploadingNoteId === n.id"
              class="rounded border border-line bg-[#faf8f4] px-2.5 py-1.5 text-sm leading-6"
            >
              <form v-if="editingId === n.id" @submit.prevent="saveEdit(n)">
                <textarea
                  v-model="editBody"
                  rows="3"
                  aria-label="编辑笔记"
                  class="w-full resize-y rounded border border-line bg-white p-1.5 text-sm leading-6 outline-none focus:border-primary"
                  placeholder="编辑笔记"
                  @paste="onPasteImage($event, n)"
                  @keydown.esc.prevent="cancelEdit"
                />
                <div class="mt-1 flex items-center gap-2">
                  <button
                    type="submit"
                    class="rounded bg-primary px-2.5 py-1 text-xs text-white disabled:cursor-not-allowed disabled:opacity-60"
                    :disabled="savingNoteId === n.id"
                  >
                    {{ savingNoteId === n.id ? '保存中…' : '保存' }}
                  </button>
                  <button
                    type="button"
                    class="rounded px-2.5 py-1 text-xs text-muted hover:bg-bgwarm"
                    :disabled="savingNoteId === n.id"
                    @click="cancelEdit"
                  >
                    取消
                  </button>
                  <el-tooltip content="添加图片" placement="top">
                    <label class="note-toolbar-icon" aria-label="添加图片">
                      <el-icon><Picture /></el-icon>
                      <input type="file" accept="image/png,image/jpeg,image/webp,image/gif" multiple class="hidden" @change="onChooseImages($event, n)" />
                    </label>
                  </el-tooltip>
                </div>
              </form>
              <template v-else>
                <div v-if="n.body" class="whitespace-pre-wrap">{{ n.body }}</div>
                <div class="mt-0.5 flex items-center justify-between gap-2 text-[11px] text-muted">
                  <span>{{ fmt(n.updated_at || n.created_at) }}</span>
                  <div class="flex shrink-0 items-center gap-1">
                    <el-tooltip content="导出笔记 PNG" placement="top">
                      <button type="button" class="note-toolbar-icon" aria-label="导出笔记 PNG" @click="exportImage(n, g)">
                        <el-icon><Download /></el-icon>
                      </button>
                    </el-tooltip>
                    <el-tooltip content="编辑笔记" placement="top">
                      <button type="button" class="note-toolbar-icon" aria-label="编辑笔记" @click="beginEdit(n)">
                        <el-icon><Edit /></el-icon>
                      </button>
                    </el-tooltip>
                  </div>
                </div>
              </template>
              <NoteImageGallery
                :images="n.images"
                :removable="editingId === n.id"
                :busy-id="deletingImageId"
                @remove="removeImage(n, $event)"
              />
            </li>
          </ul>
        </section>
      </div>
    </div>
  </main>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Download, Edit, Picture } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import NoteImageGallery from '@/components/NoteImageGallery.vue'
import { addNoteImages, deleteNoteImage, editNote, getNotebook } from '@/api/cs408/quiz'
import {
  clipboardImageFiles, exportNoteAsPng, filesToNotePayload, validateNoteImageFiles,
} from '@/utils/noteImages'

const groups = ref([])
const loading = ref(true)
const kw = ref('')
const subj = ref('')
const editingId = ref(null)
const editBody = ref('')
const savingNoteId = ref(null)
const deletingImageId = ref(null)
const uploadingNoteId = ref(null)
const subjects = ['数据结构', '组成原理', '操作系统', '计算机网络']

onMounted(async () => {
  try {
    groups.value = await getNotebook()
  } catch {
    ElMessage.error('笔记库加载失败')
  } finally {
    loading.value = false
  }
})

const noteCount = computed(() => groups.value.reduce((s, g) => s + g.notes.length, 0))
function tagsOf(g) {
  return (g.tags || '').split(/[,，]/).filter(Boolean)
}
function fmt(s) {
  return (s || '').replace('T', ' ').slice(0, 16)
}

function beginEdit(note) {
  editingId.value = note.id
  editBody.value = note.body
}

function cancelEdit() {
  if (savingNoteId.value) return
  editingId.value = null
  editBody.value = ''
}

async function saveEdit(note) {
  const body = editBody.value.trim()
  if (!body && !note.images?.length) {
    ElMessage.warning('笔记至少需要文字或一张图片')
    return
  }
  savingNoteId.value = note.id
  try {
    Object.assign(note, await editNote(note.id, body))
    editingId.value = null
    editBody.value = ''
    ElMessage.success('笔记已更新')
  } catch (error) {
    ElMessage.error(error?.response?.data?.error || '笔记更新失败')
  } finally {
    savingNoteId.value = null
  }
}

async function uploadImages(note, files) {
  const currentBytes = (note.images || []).reduce((sum, image) => sum + image.size_bytes, 0)
  const valid = validateNoteImageFiles(files, note.images?.length || 0, currentBytes)
  if (!valid.length) return
  const updated = await addNoteImages(note.id, await filesToNotePayload(valid))
  note.images = updated.images
  note.updated_at = updated.updated_at
}

async function onPasteImage(event, note) {
  const files = clipboardImageFiles(event)
  if (!files.length) return
  event.preventDefault()
  if (uploadingNoteId.value === note.id) return
  uploadingNoteId.value = note.id
  try {
    await uploadImages(note, files)
    ElMessage.success(`已粘贴 ${files.length} 张截图`)
  } catch (error) {
    ElMessage.error(error?.response?.data?.error || error.message || '图片上传失败')
  } finally {
    uploadingNoteId.value = null
  }
}

async function onChooseImages(event, note) {
  if (uploadingNoteId.value === note.id) return
  uploadingNoteId.value = note.id
  try {
    await uploadImages(note, event.target.files)
    ElMessage.success('图片已添加')
  } catch (error) {
    ElMessage.error(error?.response?.data?.error || error.message || '图片上传失败')
  } finally {
    uploadingNoteId.value = null
    event.target.value = ''
  }
}

async function removeImage(note, image) {
  const body = editingId.value === note.id ? editBody.value.trim() : note.body.trim()
  if (!body && note.images.length === 1) {
    ElMessage.warning('笔记至少需要文字或一张图片')
    return
  }
  deletingImageId.value = image.id
  try {
    if (note.images.length === 1 && body !== note.body) {
      Object.assign(note, await editNote(note.id, body))
      editBody.value = body
    }
    await deleteNoteImage(image.id)
    note.images = note.images.filter((item) => item.id !== image.id)
  } catch (error) {
    ElMessage.error(error?.response?.data?.error || '图片删除失败')
  } finally {
    deletingImageId.value = null
  }
}

async function exportImage(note, group) {
  const label = `${group.year} 年 · ${group.subject || '408'} · 第 ${group.number} 题`
  try {
    await exportNoteAsPng(note, label)
  } catch (error) {
    ElMessage.error(error.message || '笔记图片生成失败')
  }
}

const filtered = computed(() => {
  const k = kw.value.trim()
  return groups.value.filter((g) => {
    if (subj.value && g.subject !== subj.value) return false
    if (!k) return true
    const hay = g.stem_html + ' ' + g.notes.map((n) => n.body).join(' ')
    return hay.includes(k)
  })
})
</script>

<style scoped>
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
</style>
