<template>
  <main class="px-3.5 pb-20 pt-6">
    <div class="mx-auto max-w-[900px]">
      <h1 class="mb-1 mt-2 font-song text-[22px] font-bold">计算机 408 · 真题套卷</h1>
      <p class="mb-4 text-sm text-muted">
        做真题套卷 → 错题/模糊暴露薄弱知识点 → 强化训练用<b>同知识点的新题</b>（真题+模拟）反复练，做对多道才拉长间隔、不毕业。
      </p>
      <div class="grid gap-3.5 md:grid-cols-2">
        <section class="rounded-xl border border-line bg-paper p-[18px] shadow">
          <h2 class="mb-1.5 text-base font-semibold">🔁 强化训练（按知识点）</h2>
          <p class="mb-3 text-[13px] leading-relaxed text-muted">
            针对你做错/模糊暴露的薄弱知识点，优先出你没做过的<b>同知识点新题</b>，并穿插原错题。间隔重复、越拉越远、不毕业。
          </p>
          <div class="flex gap-2">
            <el-button type="primary" :disabled="!reinforce.due" @click="go('reinforce', { all: 0 })">
              练到期知识点（{{ reinforce.due }}）
            </el-button>
            <el-button :disabled="!reinforce.pool" @click="go('reinforce', { all: 1 })">
              练全部薄弱点（{{ reinforce.pool }}）
            </el-button>
          </div>
        </section>

        <section class="rounded-xl border border-line bg-paper p-[18px] shadow">
          <h2 class="mb-1.5 text-base font-semibold">📄 真题套卷</h2>
          <p class="mb-3 text-[13px] leading-relaxed text-muted">
            选择一年，按真实试卷分页做整套题（单选 + 综合）。每题可标「模糊」、扫码传草稿纸、写笔记。
          </p>
          <div class="grid grid-cols-[repeat(auto-fill,minmax(92px,1fr))] gap-2.5">
            <button
              v-for="y in years"
              :key="y.year"
              type="button"
              class="rounded-lg border border-line bg-white py-3.5 text-center font-semibold transition hover:-translate-y-0.5 hover:border-primary hover:text-primary hover:shadow"
              @click="go('exam', { year: y.year })"
            >
              {{ y.year }}<small class="mt-1 block text-[11px] font-normal text-muted">{{ y.count }} 题</small>
            </button>
          </div>
        </section>
      </div>
    </div>
  </main>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getYears, getReinforceStats } from '@/api/cs408/quiz'

const router = useRouter()
const years = ref([])
const reinforce = ref({ due: 0, pool: 0 })
const totalQ = computed(() => years.value.reduce((s, y) => s + y.count, 0))

onMounted(async () => {
  try {
    const [ys, rein] = await Promise.all([getYears(), getReinforceStats()])
    years.value = ys
    reinforce.value = { due: rein.due, pool: rein.pool }
  } catch {
    ElMessage.error('加载失败，请确认后端已在 8408 端口运行')
  }
})

function go(mode, query) {
  router.push({ name: 'paper', query: { mode, ...query } })
}
</script>
