<template>
  <div class="mx-auto mb-3.5 max-w-[820px] rounded-xl border border-line bg-paper p-4 px-5 shadow">
    <div class="text-3xl font-extrabold text-primary">{{ summary.correct }} / {{ summary.total }}</div>
    <div class="mt-1.5 flex flex-wrap items-baseline gap-5 text-sm text-muted">
      <span>正确率 {{ percent }}%</span>
      <span>错题 {{ summary.wrong }}</span>
      <span>标记模糊 {{ summary.fuzzy }}</span>
      <span class="text-primary">错题 + 蒙对/模糊 已进强化池</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({ summary: { type: Object, required: true } })
const percent = computed(() =>
  props.summary.total ? Math.round((props.summary.correct / props.summary.total) * 100) : 0,
)
</script>
