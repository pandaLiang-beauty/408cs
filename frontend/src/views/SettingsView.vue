<template>
  <main class="px-3.5 pb-24 pt-6">
    <div class="mx-auto max-w-[960px]">
      <h1 class="mb-1 font-song text-[22px] font-bold">⚙️ 设置</h1>
      <p class="mb-4 text-sm text-muted">可配置多个大模型（网关档），左侧选一个查看/编辑，勾「使用中」的那档用于大题批改。</p>

      <div v-if="loading" class="py-16 text-center text-muted">加载中…</div>

      <el-tabs v-else v-model="tab">
        <el-tab-pane label="大模型" name="llm">
          <div class="grid gap-4 md:grid-cols-[240px_1fr]">
            <!-- 左：档列表 -->
            <aside class="flex flex-col gap-1.5">
              <button
                v-for="p in cfg.profiles"
                :key="p.id"
                type="button"
                class="rounded-lg border px-3 py-2 text-left transition"
                :class="p.id === sel?.id
                  ? 'border-primary bg-primary-soft'
                  : 'border-line bg-white hover:border-primary'"
                @click="select(p)"
              >
                <div class="flex items-center gap-1.5">
                  <span class="truncate text-sm font-semibold">{{ p.name || '未命名' }}</span>
                  <span v-if="p.id === cfg.active_id"
                        class="shrink-0 rounded bg-primary px-1.5 text-[11px] text-white">使用中</span>
                </div>
                <div class="truncate text-[11px] text-muted">{{ p.model || '未选模型' }}</div>
              </button>

              <button
                type="button"
                class="rounded-lg border border-dashed border-line px-3 py-2 text-sm text-muted transition hover:border-primary hover:text-primary"
                :class="{ 'border-primary text-primary': sel && !sel.id }"
                @click="newProfile"
              >＋ 新增大模型</button>
            </aside>
            <!-- 右：所选档的详情 -->
            <section v-if="sel" class="flex flex-col gap-3.5 rounded-md border border-line bg-paper p-5 shadow-sm">
              <div class="flex flex-wrap items-center justify-between gap-2 border-b border-line pb-3">
                <span class="font-semibold">{{ sel.id ? (form.name || '未命名') : '新增大模型' }}</span>
                <div class="flex items-center gap-2">
                  <el-button v-if="sel.id && sel.id !== cfg.active_id" size="small" type="primary" plain
                             @click="onActivate(sel.id)">设为使用中</el-button>
                  <el-button v-if="sel.id" size="small" :loading="testing" @click="onTest">测试</el-button>
                  <el-button v-if="sel.id" size="small" text @click="onDelete">删除</el-button>
                </div>
              </div>

              <div class="grid gap-3.5 sm:grid-cols-2">
                <label class="flex flex-col gap-1 text-sm">
                  <span class="font-semibold">名称</span>
                  <input v-model="form.name" placeholder="如 vyceai / 我的直连 / 白鹿" class="inp" />
                </label>
                <label class="flex flex-col gap-1 text-sm">
                  <span class="font-semibold">API 格式</span>
                  <select v-model="form.api_format" class="inp">
                    <option value="openai">OpenAI 兼容（/chat/completions）</option>
                    <option value="anthropic">Anthropic Claude（/messages）</option>
                    <option value="responses">OpenAI Responses（/responses）</option>
                  </select>
                </label>
              </div>
              <p class="-mt-1.5 text-[12px] text-muted">{{ HINTS[form.api_format] }}</p>

              <label class="flex flex-col gap-1 text-sm">
                <span class="font-semibold">Base URL</span>
                <input v-model="form.base_url" :placeholder="'如 ' + URLS[form.api_format]" class="inp" />
              </label>

              <label class="flex flex-col gap-1 text-sm">
                <span class="font-semibold">API Key</span>
                <input v-model="form.api_key" type="password"
                       :placeholder="form.has_key ? '已配置（留空则不修改）' : '填入密钥'" class="inp" />
              </label>

              <div class="flex flex-col gap-1 text-sm">
                <span class="font-semibold">模型</span>
                <div class="flex gap-2">
                  <select v-if="models.length" v-model="form.model" class="inp flex-1">
                    <option v-for="m in models" :key="m" :value="m">{{ m }}</option>
                  </select>
                  <input v-else v-model="form.model" placeholder="手填模型名，或点右侧「获取模型」下拉选" class="inp flex-1" />
                  <el-button :loading="fetchingModels" @click="onFetchModels">获取模型</el-button>
                </div>
                <span v-if="models.length" class="text-[12px] text-muted">
                  共 {{ models.length }} 个可用模型，下拉选择即可。<button type="button" class="text-primary hover:underline" @click="models = []">改回手填</button>
                </span>
              </div>

              <label class="flex flex-col gap-1 text-sm">
                <span class="font-semibold">Temperature：{{ form.temperature }}</span>
                <input v-model.number="form.temperature" type="range" min="0" max="1" step="0.1" />
              </label>

              <div class="flex flex-wrap items-center gap-2 border-t border-line pt-3">
                <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
                <span v-if="msg" class="text-sm" :class="msgOk ? 'text-ok' : 'text-bad'">{{ msg }}</span>
              </div>
            </section>
          </div>
        </el-tab-pane>

        <el-tab-pane label="批改提示词" name="prompt">
          <div class="flex max-w-[720px] flex-col gap-2 rounded-md border border-line bg-paper p-5 shadow-sm">
            <div class="flex items-center justify-between">
              <span class="font-semibold">大题批改提示词（全局，所有档共用）</span>
              <button type="button" class="text-[12px] text-primary hover:underline" @click="resetPrompt">恢复默认</button>
            </div>
            <textarea v-model="promptDraft" rows="10"
                      class="resize-y rounded-lg border border-line p-2.5 font-mono text-[13px] leading-6 outline-none focus:border-primary" />
            <div class="flex items-center gap-2">
              <el-button type="primary" :loading="savingPrompt" @click="onSavePrompt">保存提示词</el-button>
              <span class="text-[12px] text-muted">与网关无关。打标签是一次性脚本，不在此配。</span>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>
  </main>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getLlmConfig, createLlmProfile, updateLlmProfile, deleteLlmProfile,
  setActiveLlmProfile, setGradePrompt, getLlmModels, testLlmProfile,
} from '@/api/cs408/quiz'

const tab = ref('llm')
const loading = ref(true)
const saving = ref(false)
const savingPrompt = ref(false)
const fetchingModels = ref(false)
const testing = ref(false)
const models = ref([])
const msg = ref('')
const msgOk = ref(false)
const cfg = ref({ profiles: [], active_id: null, grade_prompt: '', default_grade_prompt: '' })
const promptDraft = ref('')
const sel = ref(null)   // 当前在右侧编辑的档（{id:null} 表示新增）
const form = reactive({
  name: '', api_format: 'openai', base_url: '', model: '',
  temperature: 0.2, api_key: '', has_key: false,
})

const HINTS = {
  openai: '兼容 OpenAI 的网关：vyceai / 白鹿 / DeepSeek / 通义 / 自建直连等，请求 /chat/completions，Bearer 鉴权。',
  anthropic: 'Claude 官方原生接口，请求 /messages，用 x-api-key + anthropic-version 头。',
  responses: 'OpenAI Responses 接口，请求 /responses，Bearer 鉴权。',
}
const URLS = {
  openai: 'https://vyceai.com/v1',
  anthropic: 'https://api.anthropic.com/v1',
  responses: 'https://api.openai.com/v1',
}

function fill(p) {
  Object.assign(form, {
    name: p.name || '', api_format: p.api_format || 'openai', base_url: p.base_url || '',
    model: p.model || '', temperature: p.temperature ?? 0.2, api_key: '', has_key: !!p.has_key,
  })
}

async function reload(keepId) {
  cfg.value = await getLlmConfig()
  promptDraft.value = cfg.value.grade_prompt
  const id = keepId ?? sel.value?.id
  const found = cfg.value.profiles.find((p) => p.id === id) || cfg.value.profiles[0]
  if (found) {
    sel.value = found
    fill(found)
  }
}

onMounted(async () => {
  try {
    await reload()
  } catch {
    ElMessage.error('加载配置失败')
  } finally {
    loading.value = false
  }
})

function select(p) {
  sel.value = p
  fill(p)
  models.value = []
  msg.value = ''
}

function newProfile() {
  sel.value = { id: null }
  fill({ api_format: 'openai', temperature: 0.2 })
  models.value = []
  msg.value = ''
}

// 保存当前表单（新增或更新），返回该档 id
async function persist() {
  const payload = {
    name: form.name, api_format: form.api_format, base_url: form.base_url,
    model: form.model, temperature: form.temperature, api_key: form.api_key || null,
  }
  let id = sel.value?.id
  if (id) {
    cfg.value = await updateLlmProfile(id, payload)
  } else {
    cfg.value = await createLlmProfile(payload)
    id = Math.max(...cfg.value.profiles.map((p) => p.id))
  }
  await reload(id)
  return id
}

async function onSave() {
  saving.value = true
  try {
    await persist()
    msgOk.value = true
    msg.value = '✓ 已保存'
  } catch (e) {
    msgOk.value = false
    msg.value = '✗ ' + (e?.response?.data?.error || '保存失败')
  } finally {
    saving.value = false
  }
}

async function onFetchModels() {
  fetchingModels.value = true
  msg.value = ''
  try {
    const id = await persist()          // 拉模型要用已保存的地址/密钥
    const r = await getLlmModels(id)
    models.value = r.models
    msgOk.value = true
    msg.value = `✓ 拉到 ${r.models.length} 个模型`
  } catch (e) {
    msgOk.value = false
    msg.value = '✗ ' + (e?.response?.data?.error || '获取模型失败')
  } finally {
    fetchingModels.value = false
  }
}

async function onActivate(id) {
  try {
    cfg.value = await setActiveLlmProfile(id)
    await reload(id)
    ElMessage.success('已切换当前使用的大模型')
  } catch (e) {
    ElMessage.error(e?.response?.data?.error || '切换失败')
  }
}

async function onTest() {
  testing.value = true
  msg.value = ''
  try {
    const r = await testLlmProfile(sel.value.id)
    msgOk.value = true
    msg.value = '✓ 可用：' + r.reply
  } catch (e) {
    msgOk.value = false
    msg.value = '✗ ' + (e?.response?.data?.error || '调用失败')
  } finally {
    testing.value = false
  }
}

async function onDelete() {
  try {
    await ElMessageBox.confirm(`删除「${form.name || '未命名'}」？`, '确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    cfg.value = await deleteLlmProfile(sel.value.id)
    sel.value = null
    await reload()
    ElMessage.success('已删除')
  } catch (e) {
    ElMessage.error(e?.response?.data?.error || '删除失败')
  }
}

function resetPrompt() {
  promptDraft.value = cfg.value.default_grade_prompt || ''
}

async function onSavePrompt() {
  savingPrompt.value = true
  try {
    cfg.value = await setGradePrompt(promptDraft.value)
    promptDraft.value = cfg.value.grade_prompt
    ElMessage.success('提示词已保存')
  } catch (e) {
    ElMessage.error(e?.response?.data?.error || '保存失败')
  } finally {
    savingPrompt.value = false
  }
}
</script>

<style scoped>
.inp {
  border: 1px solid #ddd7cc;
  border-radius: 8px;
  padding: 8px 12px;
  outline: none;
  background: #fff;
  transition: 0.12s;
}
.inp:focus { border-color: #b04a2f; }
</style>
