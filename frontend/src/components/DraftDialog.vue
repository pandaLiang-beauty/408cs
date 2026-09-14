<template>
  <el-dialog
    :model-value="!!store.draftQid"
    title="上传草稿纸"
    width="min(520px, calc(100vw - 32px))"
    @update:model-value="close"
  >
    <div v-if="store.draftQid" class="flex flex-col items-center gap-3">
      <p class="self-start text-[13px] text-muted">
        用手机扫下面的二维码拍照上传（{{ reachHint }}）。每次追加一张，可保存多张草稿。
        链接一次有效、{{ ttl }} 分钟过期。
      </p>

      <img v-if="qrDataUrl" :src="qrDataUrl" alt="二维码" class="h-[220px] w-[220px] rounded border border-line" />
      <div v-else class="py-10 text-sm text-muted">{{ err || '生成二维码…' }}</div>

      <code v-if="url" class="w-full break-all rounded bg-[#f6f4ef] px-2 py-1 text-[11px] text-muted">{{ url }}</code>

      <div class="flex items-center gap-2">
        <el-button size="small" :loading="issuing" @click="issue">重新生成</el-button>
        <label class="cursor-pointer text-[13px] text-primary underline" :class="{ 'opacity-50': uploading }">
          {{ uploading ? '上传中…' : '或从本机选图' }}
          <input type="file" accept="image/png,image/jpeg,image/webp,image/gif" class="hidden" :disabled="uploading" @change="onFile" />
        </label>
      </div>

      <div v-if="draftImages.length" class="w-full border-t border-line pt-3">
        <div class="mb-1 text-[12px] font-semibold text-ok">✓ 已有 {{ draftImages.length }} 张草稿（本题本次作答）</div>
        <p class="mb-2 text-[12px] text-muted">点击图片可放大查看</p>
        <div class="draft-image-grid grid max-h-72 grid-cols-2 gap-2 overflow-y-auto">
          <div v-for="(image, index) in draftImages" :key="image.id" class="min-w-0 rounded border border-line bg-white p-1">
            <el-image
              :src="image.url"
              :alt="`草稿纸 ${index + 1}`"
              :preview-src-list="previewUrls"
              :initial-index="index"
              fit="contain"
              preview-teleported
              hide-on-click-modal
              class="h-40 w-full cursor-zoom-in"
            />
            <div class="text-center text-[11px] text-muted">第 {{ index + 1 }} 张</div>
          </div>
        </div>
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
import { ref, watch, onUnmounted, computed } from 'vue'
import QRCode from 'qrcode'
import { ElMessage } from 'element-plus'
import { usePaperStore } from '@/stores/paper'
import { getDraftToken, getDraftStatus, saveDraft } from '@/api/cs408/quiz'

// 草稿归属本题本次作答；每张图片都有独立地址，轮询只处理新增图片。
const store = usePaperStore()
const qrDataUrl = ref('')
const url = ref('')
const ttl = ref(10)
const err = ref('')
const draftImages = ref([])
const previewUrls = computed(() => draftImages.value.map(image => image.url))
const uploading = ref(false)
const issuing = ref(false)
let timer = null
let generation = 0
let tokenRequest = 0

// 二维码地址由后端的 STUDY_PUBLIC_BASE 决定：配了公网域名就走公网（手机用流量也行），
// 没配则回落到局域网 IP（那时手机必须和电脑同网）。提示语据此变化，避免写死误导。
const isLanUrl = computed(() =>
  /^https?:\/\/(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(url.value || ''),
)
const reachHint = computed(() =>
  isLanUrl.value ? '手机需与电脑连同一局域网' : '手机用流量也能传，不必同一 WiFi',
)

function stop() {
  clearTimeout(timer)
  timer = null
}
onUnmounted(() => {
  generation += 1
  stop()
})

function context() {
  return { sid: store.sessionId, qid: store.draftQid, generation }
}

function isCurrent(ctx) {
  return ctx.generation === generation && ctx.sid === store.sessionId && ctx.qid === store.draftQid
}

function imagesFrom(state) {
  return state?.drafts || (state?.draft_url ? [{ id: 'legacy', url: state.draft_url }] : [])
}

function applyState(ctx, state) {
  if (!isCurrent(ctx)) return 0
  const images = imagesFrom(state)
  // 上传和轮询可能交错返回；追加列表只会增长，旧响应不能隐藏刚上传的图片。
  if (images.length < draftImages.value.length) return 0
  const previous = new Set(previewUrls.value)
  if (images.length === previous.size && images.every(image => previous.has(image.url))) return 0
  const added = images.filter(image => !previous.has(image.url)).length
  draftImages.value = images
  store.patchLocalItem(ctx.qid, { drafts: images, draft_url: state.draft_url })
  return added
}

function close() {
  stop()
  store.openDraft(null)
}

async function issue() {
  const ctx = context()
  if (!ctx.sid || !ctx.qid) return
  const request = ++tokenRequest
  issuing.value = true
  err.value = ''
  qrDataUrl.value = ''
  url.value = ''
  try {
    const t = await getDraftToken(ctx.sid, ctx.qid)
    const qr = await QRCode.toDataURL(t.url, { width: 440, margin: 1 })
    if (!isCurrent(ctx) || request !== tokenRequest) return
    url.value = t.url
    ttl.value = t.ttl_minutes
    qrDataUrl.value = qr
  } catch (e) {
    if (isCurrent(ctx) && request === tokenRequest) err.value = e?.response?.data?.error || '生成失败'
  } finally {
    if (isCurrent(ctx) && request === tokenRequest) issuing.value = false
  }
}

// 首次打开立即同步；后续请求串行，避免慢网络下旧状态盖过新状态。
async function poll(ctx, notify = false) {
  try {
    const state = await getDraftStatus(ctx.sid, ctx.qid)
    const added = applyState(ctx, state)
    if (notify && added) {
      ElMessage.success(`已追加 ${added} 张草稿`)
      issue() // 手机用过的二维码换成新链接，方便继续追加。
    }
  } catch { /* 忽略单次失败，下次继续同步 */ }
  if (isCurrent(ctx)) timer = setTimeout(() => poll(ctx, true), 2500)
}

function readImage(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result)
    reader.onerror = () => reject(new Error('图片读取失败'))
    reader.readAsDataURL(file)
  })
}

async function onFile(event) {
  const file = event.target.files?.[0]
  event.target.value = '' // 允许再次选择同一文件。
  if (!file || uploading.value) return
  if (file.size > 9_000_000) {
    ElMessage.error('单张草稿图片最多 9 MB')
    return
  }
  const ctx = context() // 读取文件期间切题，也只向原题上传。
  uploading.value = true
  try {
    const data = await readImage(file)
    const state = await saveDraft(ctx.sid, ctx.qid, data)
    if (!isCurrent(ctx)) return
    applyState(ctx, state)
    ElMessage.success('已追加草稿')
  } catch (error) {
    if (isCurrent(ctx)) ElMessage.error(error?.response?.data?.error || error.message || '上传失败')
  } finally {
    if (isCurrent(ctx)) uploading.value = false
  }
}

watch(() => [store.sessionId, store.draftQid], ([sid, qid]) => {
  generation += 1
  stop()
  if (!sid || !qid) return
  draftImages.value = imagesFrom(store.items?.[qid])
  uploading.value = false
  issue()
  poll(context())
}, { immediate: true })
</script>
