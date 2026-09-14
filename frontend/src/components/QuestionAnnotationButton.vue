<template>
  <button
    v-if="enabled"
    type="button"
    class="question-annotation-button"
    :title="'为本次作答添加整题批注；选中文字可批注具体内容'"
    :aria-label="`为第 ${number} 题添加批注`"
    @click="annotations.startQuestion(questionId)"
  >
    <ChatLineSquare aria-hidden="true" />
    批注<span v-if="count"> {{ count }}</span>
  </button>
</template>

<script setup>
import { computed, inject } from 'vue'
import { ChatLineSquare } from '@element-plus/icons-vue'
import { PAPER_ANNOTATIONS } from '@/utils/annotationAnchors'

const props = defineProps({ questionId: Number, number: Number })
const annotations = inject(PAPER_ANNOTATIONS, null)
const enabled = computed(() => !!annotations?.enabled.value)
const count = computed(() => annotations?.countForQuestion(props.questionId) || 0)
</script>

<style scoped>
.question-annotation-button { display: inline-flex; align-items: center; gap: 4px; margin-left: auto; border: 0; background: transparent; color: #8c6754; font-size: 12px; cursor: pointer; padding: 3px 5px; border-radius: 4px; }
.question-annotation-button:hover { background: #f3e4de; color: #b04a2f; }
.question-annotation-button svg { width: 15px; height: 15px; }
</style>
