<template>
  <div class="flex shrink-0 items-center gap-1">
    <input
      ref="fileInput"
      type="file"
      accept="image/png,image/jpeg,image/webp,image/gif"
      multiple
      class="hidden"
      :disabled="disabled || reading"
      @change="onChoose"
    />
    <el-tooltip content="从文件添加图片" placement="top">
      <button
        type="button"
        class="note-image-picker-button"
        aria-label="添加图片"
        :disabled="disabled || reading"
        @click="fileInput?.click()"
      >
        <el-icon><Picture /></el-icon>
      </button>
    </el-tooltip>
    <el-tooltip content="从剪贴板添加图片，也可在输入框按 Ctrl+V / ⌘V" placement="top">
      <button
        type="button"
        class="note-image-picker-button note-image-paste-button"
        aria-label="粘贴图片"
        :aria-busy="reading"
        :disabled="disabled || reading"
        @click="onPaste"
      >
        <el-icon><DocumentCopy /></el-icon>
        <span>{{ reading ? '读取中…' : '粘贴图片' }}</span>
      </button>
    </el-tooltip>
  </div>
</template>

<script setup>
import { onUnmounted, ref } from 'vue'
import { DocumentCopy, Picture } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { readClipboardImageFiles } from '@/utils/noteImages'

const props = defineProps({ disabled: { type: Boolean, default: false } })
const emit = defineEmits(['select'])
const fileInput = ref(null)
const reading = ref(false)
let disposed = false

onUnmounted(() => { disposed = true })

function onChoose(event) {
  const files = Array.from(event.target.files || [])
  event.target.value = ''
  if (!props.disabled && files.length) emit('select', files)
}

async function onPaste() {
  if (props.disabled || reading.value) return
  reading.value = true
  try {
    const files = await readClipboardImageFiles()
    if (disposed || props.disabled) return
    if (!files.length) {
      ElMessage.warning('剪贴板中没有图片，请先截图或复制图片')
      return
    }
    emit('select', files)
  } catch (error) {
    if (!disposed) ElMessage.warning(error.message)
  } finally {
    reading.value = false
  }
}
</script>

<style scoped>
.note-image-picker-button {
  display: inline-flex;
  width: 30px;
  height: 30px;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  color: #b04a2f;
  cursor: pointer;
}
.note-image-picker-button:hover { background: #f3e4de; }
.note-image-picker-button:disabled { cursor: wait; opacity: .55; }
.note-image-paste-button {
  width: auto;
  gap: 4px;
  padding: 0 6px;
  font-size: 12px;
  white-space: nowrap;
}
</style>
