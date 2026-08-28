<template>
  <SubjectiveQuestion v-if="question.qtype === 'subjective'" :question="question" :index="index" />
  <ChoiceQuestion v-else :question="question" :index="index" />
</template>

<script setup>
// 按题型分发：选择题走 ChoiceQuestion，大题走 SubjectiveQuestion（AI 批改）。
import ChoiceQuestion from './ChoiceQuestion.vue'
import SubjectiveQuestion from './SubjectiveQuestion.vue'

defineProps({
  question: { type: Object, required: true },
  index: { type: Number, default: 0 },
})
</script>
