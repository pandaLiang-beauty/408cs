import axiosInstance from '../axiosInstance'

// cs408 做题相关接口。每个函数返回 Promise<后端 JSON>。做题以 session 为中心。
export const getYears = () => axiosInstance.get('/years')

// 强化池概况（到期数 / 全池数），首页展示用
export const getReinforceStats = () => axiosInstance.get('/reinforce/stats')

// 建/续一场做题：exam 传 year；reinforce 传 all；fresh=true 时另起新记录
export const createSession = (payload) => axiosInstance.post('/sessions', payload)

// 按 id 取一场做题的完整状态（刷新恢复）
export const getSession = (sid) => axiosInstance.get(`/sessions/${sid}`)

// 自动保存单题作答（选项 / 模糊）
export const patchItem = (sid, qid, patch) =>
  axiosInstance.patch(`/sessions/${sid}/items/${qid}`, patch)

// 交卷：批改本卷选择题、跑 SRS
export const submitSession = (sid) => axiosInstance.post(`/sessions/${sid}/submit`)

// 上传本场做题的草稿纸
export const saveDraft = (sid, question_id, image_base64) =>
  axiosInstance.post(`/sessions/${sid}/draft`, { question_id, image_base64 })

// 签发一次性上传链接（用于生成二维码，手机扫码上传草稿纸）
export const getDraftToken = (sid, question_id) =>
  axiosInstance.post(`/sessions/${sid}/draft-token`, { question_id })

// 轮询该题草稿（手机传完后电脑端刷新）
export const getDraftStatus = (sid, question_id) =>
  axiosInstance.get(`/sessions/${sid}/draft`, { params: { question_id } })

// 大题 AI 批改（写回本场记录）
export const gradeSubjective = (sid, question_id, answer_text) =>
  axiosInstance.post(`/sessions/${sid}/grade_subjective`, { question_id, answer_text })

// 笔记：一题多条 + 笔记库
export const listNotes = (question_id) => axiosInstance.get('/notes', { params: { question_id } })
export const addNote = (payload) => axiosInstance.post('/notes', payload)
export const editNote = (id, body) => axiosInstance.patch(`/notes/${id}`, { body })
export const addNoteImages = (id, images) => axiosInstance.post(`/notes/${id}/images`, { images })
export const deleteNoteImage = (id) => axiosInstance.delete(`/note-images/${id}`)
export const deleteNote = (id) => axiosInstance.delete(`/notes/${id}`)
export const getNotebook = () => axiosInstance.get('/notebook')

// 大模型在线配置
// 学习排程（首页任务单）
export const getPlan = () => axiosInstance.get('/plan')
export const getPlanCalendar = (ym) => axiosInstance.get('/plan/calendar', { params: ym ? { ym } : {} })
export const startTask = (id) => axiosInstance.post(`/plan/tasks/${id}/start`)
export const setExamDate = (exam_date) => axiosInstance.put('/plan/config', { exam_date })

// 大模型多档配置：可存多个网关档，选一个使用
export const getLlmConfig = () => axiosInstance.get('/settings/llm')
export const createLlmProfile = (payload) => axiosInstance.post('/settings/llm/profiles', payload)
export const updateLlmProfile = (id, payload) => axiosInstance.put(`/settings/llm/profiles/${id}`, payload)
export const deleteLlmProfile = (id) => axiosInstance.delete(`/settings/llm/profiles/${id}`)
export const setActiveLlmProfile = (profile_id) => axiosInstance.put('/settings/llm/active', { profile_id })
export const setGradePrompt = (grade_prompt) => axiosInstance.put('/settings/llm/prompt', { grade_prompt })
export const getLlmModels = (profile_id) =>
  axiosInstance.get('/settings/llm/models', { params: { profile_id } })
export const testLlmProfile = (profile_id) =>
  axiosInstance.post('/settings/llm/test', null, { params: { profile_id } })
