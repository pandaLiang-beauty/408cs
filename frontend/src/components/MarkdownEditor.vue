<template>
  <div ref="root" class="markdown-editor">
    <div class="markdown-editor-toolbar">
      <div class="markdown-editor-modes" :aria-label="`${ariaLabel}显示方式`">
        <button type="button" :aria-pressed="!preview" @click="preview = false">编辑</button>
        <button type="button" :aria-pressed="preview" @click="preview = true">预览</button>
      </div>
      <span title="支持标题、加粗、列表、引用、代码、表格、公式，以及 ==高亮==">Markdown · ===高亮===</span>
    </div>
    <MarkdownContent v-if="preview" :source="modelValue || '暂无内容'" class="markdown-editor-preview" :aria-label="`${ariaLabel}预览`" />
    <textarea
      v-else ref="input" :value="modelValue" :rows="rows" :maxlength="maxlength" :disabled="disabled"
      :aria-label="ariaLabel" :placeholder="placeholder" class="markdown-editor-input"
      @input="$emit('update:modelValue', $event.target.value)"
      @blur="$emit('blur', $event)" @paste="$emit('paste', $event)" @keydown="$emit('keydown', $event)"
    />
  </div>
</template>

<script setup>
import { nextTick, ref } from 'vue'
import MarkdownContent from '@/components/MarkdownContent.vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  rows: { type: [Number, String], default: 4 },
  maxlength: { type: [Number, String], default: undefined },
  disabled: Boolean,
  ariaLabel: { type: String, default: '内容' },
  placeholder: { type: String, default: '支持 Markdown，可使用 ===高亮内容===' },
  startPreview: Boolean,
})
defineEmits(['update:modelValue', 'blur', 'paste', 'keydown'])
const preview = ref(props.startPreview)
const input = ref(null)
const root = ref(null)
defineExpose({
  async focus(options) {
    preview.value = false
    await nextTick()
    input.value?.focus(options)
  },
})
</script>
