<template>
  <el-popover
    :visible="open" trigger="click" placement="bottom-start" :width="'min(440px, calc(100vw - 24px))'"
    :show-arrow="false" :offset="10" persistent popper-class="image-host-popover"
    @update:visible="setOpen" @show="onOpen"
  >
    <template #reference>
      <button ref="trigger" type="button" class="host-trigger" aria-label="图床" aria-haspopup="dialog"
              aria-controls="quick-image-host" :aria-expanded="open">
        <Picture aria-hidden="true" /> 图床<span v-if="uploading" class="host-upload-dot" aria-label="正在上传"></span>
      </button>
    </template>
    <section id="quick-image-host" ref="panel" class="host-panel" role="dialog" aria-label="快捷图床" tabindex="-1"
             @paste="onPaste" @dragover.prevent @drop.prevent="onDrop" @keydown.esc.stop.prevent="close">
      <div class="mb-3 flex items-center justify-between gap-3">
        <div><h2 class="font-bold text-ink">快捷图床</h2><p class="mt-1 text-xs text-muted">上传图片，复制链接，继续写批注。</p></div>
        <button type="button" class="host-close" aria-label="关闭图床" @click="close"><Close aria-hidden="true" /></button>
      </div>
      <section
        class="upload-area rounded-lg border border-dashed border-line bg-paper px-3 py-4 text-center"
        tabindex="0" aria-label="图片上传区域，可粘贴或拖入图片" :aria-busy="uploading"
      >
        <input ref="fileInput" type="file" :accept="IMAGE_HOST_ACCEPT" multiple class="hidden"
               :disabled="uploading" @change="onChoose" />
        <p class="mb-3 text-xs text-ink">拖入图片，或按 Ctrl+V / ⌘V 粘贴截图</p>
        <div class="flex flex-wrap items-center justify-center gap-3">
          <button type="button" class="host-button host-button-primary" :disabled="uploading"
                  @click="fileInput?.click()">选择图片</button>
          <button type="button" class="host-button" :disabled="uploading || reading"
                  @click="pasteFromClipboard">{{ reading ? '读取中…' : '粘贴图片' }}</button>
        </div>
        <p class="mt-3 text-[11px] text-muted">PNG / JPEG / WebP / GIF · 单张最多 8 MB</p>
        <p v-if="uploading" role="status" class="mt-3 break-words text-xs text-primary">{{ uploadStatus }}</p>
      </section>

      <div v-if="uploadErrors.length" role="alert" class="mt-3 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800">
        <p>以下图片未上传，可重新选择后重试：</p>
        <ul class="mt-1 list-inside list-disc break-words">
          <li v-for="(error, index) in uploadErrors" :key="index">{{ error }}</li>
        </ul>
      </div>

      <div class="mb-2 mt-4 flex items-center justify-between gap-3">
        <h3 class="text-xs font-semibold text-ink">{{ showHistory ? '历史图片' : '最近上传' }}</h3>
        <button v-if="images.length > 1 || nextCursor" type="button" class="text-xs text-primary"
                :aria-expanded="showHistory" @click="showHistory = !showHistory">
          {{ showHistory ? '收起历史' : '历史图片' }}
        </button>
      </div>
      <p v-if="loadError" role="alert" class="mb-4 text-sm text-red-700">
        {{ loadError }} <button type="button" class="underline" :disabled="loading || uploading" @click="loadImages">重试</button>
      </p>
      <p v-if="!images.length && loading" role="status" class="py-4 text-center text-xs text-muted">正在读取图片…</p>
      <p v-else-if="!images.length && !loadError" class="py-4 text-center text-xs text-muted">
        上传后在这里复制链接。
      </p>
      <div ref="imageList" class="host-images">
        <article v-for="(image, index) in displayedImages" :key="image.id" class="min-w-0 rounded-lg border border-line bg-paper p-3">
          <div class="mb-2 flex items-center gap-3">
            <el-image class="host-preview" :src="image.url" :alt="image.filename" fit="contain" loading="lazy"
                      :preview-src-list="previewUrls" :initial-index="index"
                      preview-teleported hide-on-click-modal @show="previewing = true" @close="previewing = false">
              <template #error><span class="text-[10px] text-muted">加载失败</span></template>
            </el-image>
            <div class="min-w-0">
              <p class="truncate text-xs text-ink" :title="image.filename">{{ image.filename }}</p>
              <p class="mt-1 text-[11px] text-muted">{{ formatSize(image.size_bytes) }} · {{ formatTime(image.created_at) }}</p>
            </div>
          </div>
          <input :value="hostedImageUrl(image)" readonly :aria-label="`${image.filename}的图片直链`"
                 class="mb-2 w-full rounded border border-line bg-bgwarm px-2 py-1.5 text-xs text-muted outline-none focus:border-primary"
                 @focus="$event.target.select()" @click="$event.target.select()" />
          <div class="flex flex-wrap gap-2">
            <button type="button" class="host-button" @click="copyLink(image, false)">复制直链</button>
            <button type="button" class="host-button host-button-primary" @click="copyLink(image, true)">复制 Markdown</button>
          </div>
        </article>
      </div>
      <div v-if="showHistory && nextCursor" class="mt-3 text-center">
        <button type="button" class="host-button" :disabled="loading || uploading" @click="loadImages">
          {{ loading ? '加载中…' : '加载更多' }}
        </button>
      </div>
    </section>
  </el-popover>
</template>

<script setup>
import { computed, nextTick, onUnmounted, ref } from 'vue'
import { Close, Picture } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getHostedImages, uploadHostedImage } from '@/api/cs408/imageHost'
import { IMAGE_HOST_ACCEPT, copyImageLink, hostedImageMarkdown, hostedImageUrl, validateHostedImage } from '@/utils/imageHost'

const fileInput = ref(null)
const open = ref(false)
const trigger = ref(null)
const panel = ref(null)
const imageList = ref(null)
const showHistory = ref(false)
const previewing = ref(false)
const images = ref([])
const nextCursor = ref(null)
const loading = ref(false)
const loadError = ref('')
const uploading = ref(false)
const uploadStatus = ref('')
const uploadErrors = ref([])
const reading = ref(false)
const displayedImages = computed(() => showHistory.value ? images.value : images.value.slice(0, 1))
const previewUrls = computed(() => displayedImages.value.map(image => image.url))
let loaded = false
let disposed = false

onUnmounted(() => { disposed = true })
defineExpose({ open: () => { open.value = true } })

function setOpen(value) {
  if (!value && previewing.value) return
  open.value = value
}

async function onOpen() {
  if (!loaded) loadImages()
  await nextTick()
  if (open.value) panel.value?.focus({ preventScroll: true })
}

function close() {
  open.value = false
  trigger.value?.focus({ preventScroll: true })
}

function errorMessage(error, fallback) {
  return error?.response?.data?.error || error.message || fallback
}

async function loadImages() {
  if (loading.value) return
  loading.value = true
  loadError.value = ''
  try {
    const result = await getHostedImages(nextCursor.value)
    if (disposed) return
    const seen = new Set(images.value.map(image => image.id))
    images.value.push(...result.images.filter(image => !seen.has(image.id)))
    images.value.sort((a, b) => b.id - a.id)
    nextCursor.value = result.next_cursor
    loaded = true
  } catch (error) {
    if (!disposed) loadError.value = errorMessage(error, '图片列表读取失败')
  } finally {
    loading.value = false
  }
}

async function uploadFiles(files) {
  if (!files.length) return
  if (uploading.value) {
    ElMessage.info('请等待当前上传完成后重试')
    return
  }
  uploading.value = true
  uploadErrors.value = []
  let uploaded = 0
  try {
    // 逐张上传，失败不影响已成功的图片，也不在内存里同时保存多张 Base64。
    for (const [index, file] of Array.from(files).entries()) {
      if (disposed) break
      uploadStatus.value = `正在上传 ${index + 1} / ${files.length}：${file.name || '剪贴板图片'}`
      try {
        validateHostedImage(file)
        const { filesToNotePayload } = await import('@/utils/noteImages')
        const [payload] = await filesToNotePayload([file])
        const image = await uploadHostedImage(payload)
        if (disposed) break
        images.value = [image, ...images.value.filter(item => item.id !== image.id)]
        showHistory.value = false
        if (imageList.value) imageList.value.scrollTop = 0
        uploaded += 1
      } catch (error) {
        if (!disposed) uploadErrors.value.push(`${file.name || '剪贴板图片'}：${errorMessage(error, '上传失败')}`)
      }
    }
    if (uploaded && !disposed) ElMessage.success(`已上传 ${uploaded} 张图片，可复制链接`)
  } finally {
    uploading.value = false
    uploadStatus.value = ''
  }
}

function onChoose(event) {
  const files = Array.from(event.target.files || [])
  event.target.value = ''
  uploadFiles(files)
}

function onDrop(event) {
  uploadFiles(Array.from(event.dataTransfer?.files || []))
}

function onPaste(event) {
  if (!open.value) return
  const files = Array.from(event.clipboardData?.files || []).filter(file => file.type.startsWith('image/'))
  if (!files.length) return
  event.preventDefault()
  uploadFiles(files)
}

async function pasteFromClipboard() {
  if (reading.value || uploading.value) return
  reading.value = true
  try {
    const { readClipboardImageFiles } = await import('@/utils/noteImages')
    const files = await readClipboardImageFiles()
    if (disposed) return
    if (!files.length) ElMessage.info('剪贴板中没有图片，请先截图或复制图片')
    else await uploadFiles(files)
  } catch {
    if (!disposed) ElMessage.warning('无法读取剪贴板，请在浮层内按 Ctrl+V / ⌘V 粘贴，或选择图片文件')
  } finally {
    reading.value = false
  }
}

async function copyLink(image, markdown) {
  const value = markdown ? hostedImageMarkdown(image) : hostedImageUrl(image)
  try {
    await copyImageLink(value)
    ElMessage.success(markdown ? 'Markdown 图片链接已复制' : '图片直链已复制')
  } catch (error) {
    ElMessage.warning(error.message)
  }
}

function formatSize(bytes) {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatTime(value) {
  // SQLite 默认时间为 UTC，按浏览器本地时间显示。
  const date = new Date(value.replace(' ', 'T') + 'Z')
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}
</script>

<style scoped>
.host-trigger { display: inline-flex; align-items: center; gap: 5px; padding: 4px 8px; border: 1px solid #5e5143;
  border-radius: 5px; color: #e4c8b4; font-size: 12px; white-space: nowrap; cursor: pointer; }
.host-trigger:hover, .host-trigger[aria-expanded='true'] { border-color: #c99470; background: #46392d; color: #fff0e5; }
.host-trigger svg { width: 15px; height: 15px; }
.host-upload-dot { width: 6px; height: 6px; border-radius: 50%; background: #e3ac73; }
.host-panel { max-height: calc(100dvh - 100px); overflow-y: auto; overscroll-behavior: contain; outline: none; }
.host-close { width: 28px; height: 28px; padding: 5px; border-radius: 4px; color: #867464; cursor: pointer; }
.host-close:hover { background: #f3e4de; }
.host-images { display: flex; flex-direction: column; gap: 8px; max-height: 300px; overflow-y: auto; overscroll-behavior: contain; }
.upload-area:focus-visible { outline: 2px solid #b04a2f; outline-offset: 3px; }
.host-button { border: 1px solid #ddd7cc; border-radius: 5px; padding: 7px 12px; background: #fffdf9;
  color: #6d5543; font-size: 12px; cursor: pointer; }
.host-button:hover { border-color: #b04a2f; color: #b04a2f; }
.host-button-primary { border-color: #b04a2f; background: #b04a2f; color: #fff; }
.host-button-primary:hover { background: #983e28; color: #fff; }
.host-button:disabled { cursor: wait; opacity: .55; }
.host-preview { display: flex; flex-shrink: 0; width: 64px; height: 48px; align-items: center; justify-content: center;
  border: 1px solid #ddd7cc; border-radius: 4px; background: #f3efe6; cursor: zoom-in; }
</style>
