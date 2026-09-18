export function gradingErrorMessage(error) {
  const detail = error?.response?.data?.error || error?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (['ECONNABORTED', 'ETIMEDOUT'].includes(error?.code) || [504, 524].includes(error?.response?.status)) {
    return '等待 AI 批改超时，请稍后重试以查看结果'
  }
  if (!error?.response) return '网络连接中断，请检查网络后重试'
  return `AI 批改暂时不可用（HTTP ${error.response.status}），请稍后重试`
}
