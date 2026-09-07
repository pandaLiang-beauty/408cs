<template>
  <div v-if="images.length" class="note-image-grid">
    <div v-for="(image, index) in images" :key="image.id" class="note-image-item">
      <el-image
        class="note-image-preview"
        :src="image.url"
        :alt="image.filename || '笔记图片'"
        :preview-src-list="previewUrls"
        :initial-index="index"
        fit="contain"
        preview-teleported
        hide-on-click-modal
      />
      <div class="note-image-actions">
        <el-tooltip content="下载原图" placement="top">
          <a
            :href="image.download_url"
            :download="image.filename || `note-image-${image.id}`"
            class="note-image-action"
            :aria-label="`下载 ${image.filename || '笔记图片'}`"
            @click.stop
          >
            <el-icon><Download /></el-icon>
          </a>
        </el-tooltip>
        <el-tooltip v-if="removable" content="删除图片" placement="top">
          <button
            type="button"
            class="note-image-action note-image-delete"
            :disabled="busyId === image.id"
            :aria-label="`删除 ${image.filename || '笔记图片'}`"
            @click.stop="$emit('remove', image)"
          >
            <el-icon><Delete /></el-icon>
          </button>
        </el-tooltip>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Delete, Download } from '@element-plus/icons-vue'

const props = defineProps({
  images: { type: Array, default: () => [] },
  removable: { type: Boolean, default: false },
  busyId: { type: Number, default: null },
})

defineEmits(['remove'])

const previewUrls = computed(() => props.images.map((image) => image.url))
</script>

<style scoped>
.note-image-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(132px, 1fr));
  gap: 8px;
  margin-top: 8px;
}
.note-image-item {
  position: relative;
  min-width: 0;
  overflow: hidden;
  border: 1px solid #ddd7cc;
  border-radius: 6px;
  background: #fff;
  aspect-ratio: 4 / 3;
}
.note-image-preview {
  width: 100%;
  height: 100%;
  cursor: zoom-in;
}
.note-image-actions {
  position: absolute;
  right: 6px;
  bottom: 6px;
  display: flex;
  gap: 5px;
}
.note-image-action {
  display: inline-flex;
  width: 30px;
  height: 30px;
  align-items: center;
  justify-content: center;
  border: 1px solid rgb(255 255 255 / 70%);
  border-radius: 4px;
  background: rgb(38 34 28 / 88%);
  color: #fff;
  cursor: pointer;
}
.note-image-action:hover { background: #1c1a17; }
.note-image-action:disabled { cursor: wait; opacity: .55; }
.note-image-delete:hover { background: #c23b3b; }
</style>
