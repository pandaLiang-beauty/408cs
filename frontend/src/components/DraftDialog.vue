<template>
  <el-dialog
    :model-value="!!store.draftQid"
    title="上传草稿纸"
    width="420"
    @update:model-value="close"
  >
    <div v-if="store.draftQid" class="flex flex-col items-center gap-3">
      <p class="self-start text-[13px] text-muted">
        用手机扫下面的二维码拍照上传（{{ reachHint }}）。链接一次有效、{{ ttl }} 分钟过期。
      </p>

      <img v-if="qrDataUrl" :src="qrDataUrl" alt="二维码" class="h-[220px] w-[220px] rounded border border-line" />
      <div v-else class="py-10 text-sm text-muted">{{ err || '生成二维码…' }}</div>

      <code v-if="url" class="w-full break-all rounded bg-[#f6f4ef] px-2 py-1 text-[11px] text-muted">{{ url }}</code>

      <div class="flex items-center gap-2">
        <el-button size="small" @click="issue">重新生成</el-button>
        <label class="cursor-pointer text-[13px] text-primary underline">
          或从本机选图
          <input type="file" accept="image/*" class="hidden" @change="onFile" />
        </label>
      </div>

      <div v-if="draftUrl" class="w-full border-t border-line pt-3">
        <div class="mb-1 text-[12px] font-semibold text-ok">✓ 已有草稿（本题本次作答）</div>
        <img :src="draftUrl" alt="草稿纸" class="max-h-64 w-full rounded border border-line object-contain" />
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

// 草稿纸：电脑上出二维码 → 手机扫码上传 → 这里轮询到图就显示。也支持本机选图。
const store = usePaperStore()
const qrDataUrl = ref('')
const url = ref('')
const ttl = ref(10)
const err = ref('')
const draftUrl = ref('')
let timer = null

// 二维码地址由后端的 STUDY_PUBLIC_BASE 决定：配了公网域名就走公网（手机用流量也行），
// 没配则回落到局域网 IP（那时手机必须和电脑同网）。提示语据此变化，避免写死误导。
const isLanUrl = computed(() =>
  /^https?:\/\/(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(url.value || ''),
)
const reachHint = computed(() =>
  isLanUrl.value ? '手机需与电脑连同一局域网' : '手机用流量也能传，不必同一 WiFi',
)

function stop() {
  clearInterval(timer)
  timer = null
}
onUnmounted(stop)

function close() {
  stop()
  store.openDraft(null)
}

async function issue() {
  const qid = store.draftQid
  err.value = ''
  qrDataUrl.value = ''
  url.value = ''
  try {
    const t = await getDraftToken(store.sessionId, qid)
    url.value = t.url
    ttl.value = t.ttl_minutes
    qrDataUrl.value = await QRCode.toDataURL(t.url, { width: 440, margin: 1 })
  } catch (e) {
    err.value = e?.response?.data?.error || '生成失败'
  }
}

// 轮询：手机传完后自动出现缩略图
function poll() {
  stop()
  timer = setInterval(async () => {
    const qid = store.draftQid
    if (!qid) return stop()
    try {
      const r = await getDraftStatus(store.sessionId, qid)
      if (r.draft_url && r.draft_url !== draftUrl.value) {
        draftUrl.value = r.draft_url + '?t=' + Date.now()
        store.patchLocalItem(qid, { draft_url: r.draft_url })
        ElMessage.success('草稿纸已上传')
      }
    } catch { /* 忽略单次失败 */ }
  }, 2500)
}

function onFile(e) {
  const file = e.target.files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = async () => {
    try {
      const r = await saveDraft(store.sessionId, store.draftQid, reader.result)
      draftUrl.value = r.draft_url + '?t=' + Date.now()
      store.patchLocalItem(store.draftQid, { draft_url: r.draft_url })
      ElMessage.success('已上传')
    } catch {
      ElMessage.error('上传失败')
    }
  }
  reader.readAsDataURL(file)
}

watch(() => store.draftQid, (qid) => {
  if (!qid) return stop()
  draftUrl.value = store.items?.[qid]?.draft_url || ''
  issue()
  poll()
})
</script>
