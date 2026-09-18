import assert from 'node:assert/strict'
import test from 'node:test'
import { gradingErrorMessage } from './gradingError.js'

test('shows the specific backend grading error', () => {
  const reason = 'AI 批改失败：当前模型已被网关停用，请在「设置」中切换模型'
  assert.equal(gradingErrorMessage({ response: { status: 502, data: { error: reason } } }), reason)
  assert.equal(gradingErrorMessage({ response: { data: { detail: '未登录' } } }), '未登录')
})

test('distinguishes timeouts, dropped connections and proxy errors', () => {
  for (const error of [{ code: 'ECONNABORTED' }, { code: 'ETIMEDOUT' }, { response: { status: 504 } }, { response: { status: 524 } }]) {
    assert.match(gradingErrorMessage(error), /超时.*重试/)
  }
  assert.match(gradingErrorMessage({ code: 'ERR_NETWORK' }), /网络连接中断/)
  assert.match(gradingErrorMessage({ response: { status: 502, data: '<html>Bad Gateway</html>' } }), /HTTP 502/)
})
