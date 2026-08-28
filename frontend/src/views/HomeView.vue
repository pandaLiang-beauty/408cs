<template>
  <main class="px-3.5 pb-24 pt-6">
    <div class="mx-auto max-w-[900px]">
      <div v-if="loading" class="py-16 text-center text-muted">加载排程…</div>

      <template v-else-if="plan">
        <!-- 倒计时 -->
        <div class="mb-4 flex flex-wrap items-end justify-between gap-2 border-b-2 border-ink pb-3">
          <div>
            <div class="font-song text-[26px] font-bold leading-tight">
              距考研初试 <span class="text-primary">{{ plan.days_left }}</span> 天
            </div>
            <div class="text-[13px] text-muted">
              初试 {{ plan.exam_date }} · 真题进度 {{ plan.progress.papers_done }} / {{ plan.progress.papers_total }} 套
            </div>
          </div>
          <div class="font-song text-[15px]">今天 · {{ fmtDate(plan.today) }} {{ plan.weekday }}</div>
        </div>

        <!-- 今日任务（一键开始，不用在日历里找） -->
        <div class="mb-5 flex flex-col gap-2.5">
          <article
            v-for="t in plan.tasks"
            :key="t.id"
            class="flex items-center gap-3 rounded-md border bg-paper px-4 py-3.5 shadow-sm"
            :class="t.status === 'done' ? 'border-ok bg-ok-soft' : 'border-primary'"
          >
            <span class="text-[22px]">{{ ICON[t.kind] }}</span>
            <div class="min-w-0 flex-1">
              <div class="font-song text-[17px] font-bold">今日 · {{ t.title }}</div>
              <div class="text-[13px] text-muted">{{ t.detail }}</div>
            </div>
            <el-button v-if="t.status !== 'done'" type="primary" :loading="startingId === t.id" @click="onStart(t)">
              {{ t.session_id ? '继续' : '开始' }}
            </el-button>
            <span v-else class="text-sm font-semibold text-ok">✓ 已完成</span>
          </article>

          <article
            v-for="t in plan.overdue"
            :key="'o' + t.id"
            class="flex items-center gap-3 rounded-md border border-amber bg-amber-soft px-4 py-3 shadow-sm"
          >
            <span class="text-[20px]">⏳</span>
            <div class="min-w-0 flex-1">
              <div class="font-song text-[16px] font-bold">补做 · {{ t.title }}</div>
              <div class="text-[12px] text-muted">原定 {{ fmtDate(t.date) }} {{ t.weekday }} · {{ t.detail }}</div>
            </div>
            <el-button :loading="startingId === t.id" @click="onStart(t)">{{ t.session_id ? '继续' : '开始' }}</el-button>
          </article>
        </div>
        <!-- 月历 -->
        <section v-if="cal" class="rounded-md border border-line bg-paper p-4 shadow-sm">
          <div class="mb-3 flex items-center justify-between">
            <div class="flex items-center gap-2">
              <el-button size="small" @click="shift(-1)">‹</el-button>
              <span class="font-song text-[17px] font-bold">{{ monthLabel }}</span>
              <el-button size="small" @click="shift(1)">›</el-button>
            </div>
            <el-button size="small" text @click="load(null)">回到本月</el-button>
          </div>

          <div class="grid grid-cols-7 gap-1.5">
            <div v-for="w in ['一','二','三','四','五','六','日']" :key="w"
                 class="pb-1 text-center text-[12px] font-semibold text-muted">{{ w }}</div>

            <div v-for="n in cal.first_weekday" :key="'pad' + n"></div>

            <button
              v-for="d in cal.days_in_month"
              :key="d"
              type="button"
              class="flex min-h-[62px] flex-col rounded-lg border p-1.5 text-left transition"
              :class="cellClass(dayOf(d))"
              :disabled="!actionable(dayOf(d))"
              @click="onCell(dayOf(d))"
            >
              <span class="text-[12px] font-bold" :class="isToday(d) ? 'text-primary' : 'text-muted'">
                {{ d }}<span v-if="isToday(d)" class="ml-0.5 font-normal">今天</span>
              </span>
              <span v-if="dayOf(d)" class="mt-0.5 truncate text-[11px] leading-4">
                {{ ICON[dayOf(d).kind] }} {{ chip(dayOf(d)) }}
              </span>
              <span v-if="dayOf(d)?.status === 'done'" class="mt-auto text-[11px] font-bold text-ok">✓</span>
            </button>
          </div>

          <div class="mt-3 flex flex-wrap gap-x-4 gap-y-1 border-t border-line pt-2 text-[11px] text-muted">
            <span>📄 精做真题</span><span>🔁 强化训练</span><span>🧪 全真模考</span>
            <span class="text-ok">■ 已完成</span><span class="text-amber">■ 欠账待补</span><span>□ 预排（可自动调整）</span>
          </div>
        </section>

        <!-- 自选（默认折叠，避免又变成"货架"） -->
        <details class="mt-4 rounded-md border border-line bg-paper px-4 py-3">
          <summary class="cursor-pointer text-sm font-semibold text-muted">▸ 自选：临时练强化 / 挑某年真题</summary>
          <div class="mt-3 flex flex-wrap gap-2">
            <el-button type="primary" plain :disabled="!stats.due" @click="go('reinforce', { all: 0 })">
              练到期知识点（{{ stats.due }}）
            </el-button>
            <el-button plain :disabled="!stats.pool" @click="go('reinforce', { all: 1 })">
              练全部薄弱点（{{ stats.pool }}）
            </el-button>
          </div>
          <div class="mt-3 grid grid-cols-[repeat(auto-fill,minmax(84px,1fr))] gap-2">
            <button
              v-for="y in years"
              :key="y.year"
              type="button"
              class="rounded-lg border border-line bg-white py-2.5 text-center text-sm font-semibold transition hover:border-primary hover:text-primary"
              @click="go('exam', { year: y.year })"
            >{{ y.year }}</button>
          </div>
        </details>
      </template>
    </div>
  </main>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getPlan, getPlanCalendar, startTask, getYears, getReinforceStats } from '@/api/cs408/quiz'

const router = useRouter()
const loading = ref(true)
const plan = ref(null)
const cal = ref(null)
const years = ref([])
const stats = ref({ due: 0, pool: 0 })
const startingId = ref(null)
const ICON = { exam: '📄', reinforce: '🔁', mock: '🧪' }

function fmtDate(s) {
  const [, m, d] = (s || '').split('-')
  return `${Number(m)}月${Number(d)}日`
}
const monthLabel = computed(() => {
  const [y, m] = (cal.value?.month || '').split('-')
  return `${y} 年 ${Number(m)} 月`
})

// 日历取值：按“日”找当天的排程条目
const byDate = computed(() => Object.fromEntries((cal.value?.days || []).map((d) => [d.date, d])))
function dateStr(d) {
  return `${cal.value.month}-${String(d).padStart(2, '0')}`
}
function dayOf(d) {
  return byDate.value[dateStr(d)]
}
function isToday(d) {
  return dateStr(d) === cal.value.today
}
function chip(e) {
  if (e.kind === 'reinforce') return '强化'
  return e.kind === 'mock' ? `模考${e.ref_year}` : `${e.ref_year}`
}
function actionable(e) {
  return !!e && !e.planned && e.status !== 'done'
}
function cellClass(e) {
  const t = e && e.date === cal.value.today
  if (!e) return 'border-transparent bg-transparent cursor-default'
  if (e.status === 'done') return 'border-ok bg-ok-soft cursor-default'
  if (e.planned) return 'border-dashed border-line bg-white/60 text-muted cursor-default'
  if (t) return 'border-primary bg-primary-soft font-semibold'
  return 'border-amber bg-amber-soft'          // 过期未做 = 欠账
}

async function load(ym) {
  cal.value = await getPlanCalendar(ym)
}
function shift(n) {
  const [y, m] = cal.value.month.split('-').map(Number)
  const d = new Date(y, m - 1 + n, 1)
  load(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`)
}

onMounted(async () => {
  try {
    const [p, c, ys, st] = await Promise.all([getPlan(), getPlanCalendar(), getYears(), getReinforceStats()])
    plan.value = p
    cal.value = c
    years.value = ys
    stats.value = { due: st.due, pool: st.pool }
  } catch {
    ElMessage.error('加载失败，请确认后端已在 8408 端口运行')
  } finally {
    loading.value = false
  }
})

// 开始任务：后端建/续对应的卷并绑定，前端带 sid 进卷面
async function onStart(t) {
  startingId.value = t.id
  try {
    const r = await startTask(t.id)
    const q = r.mode === 'exam'
      ? { mode: 'exam', year: r.year, sid: r.session_id }
      : { mode: 'reinforce', all: '0', sid: r.session_id }
    router.push({ name: 'paper', query: q })
  } catch (e) {
    ElMessage.error(e?.response?.data?.error || '无法开始该任务')
  } finally {
    startingId.value = null
  }
}
function onCell(e) {
  if (actionable(e)) onStart(e)
}
function go(mode, query) {
  router.push({ name: 'paper', query: { mode, ...query } })
}
</script>
