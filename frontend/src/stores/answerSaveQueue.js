/**
 * Per-question persistence coordinator.
 *
 * Each session/question pair has one ordered write chain. A newer local
 * answer is held as the next snapshot, never sent concurrently with an older
 * snapshot, so a delayed request cannot overwrite a newer choice.
 */
export function createAnswerSaveQueue({ save, onStateChange, onError, onSuccess } = {}) {
  const pending = new Map()
  const active = new Set()
  const chains = new Map()
  let revision = 0

  function keyFor(sessionId, questionId) {
    return `${Number(sessionId)}:${Number(questionId)}`
  }

  function notifyState() {
    onStateChange?.({ pending: pending.size, active: active.size })
  }

  function appendDrain(key) {
    const previous = chains.get(key) || Promise.resolve()
    const next = previous.then(() => drain(key), () => drain(key))
    chains.set(key, next)
    void next.finally(() => {
      if (chains.get(key) === next) chains.delete(key)
      notifyState()
    })
    return next
  }

  async function drain(key) {
    while (pending.has(key)) {
      const entry = pending.get(key)
      pending.delete(key)
      active.add(key)
      notifyState()
      try {
        await save(entry)
        onSuccess?.(entry)
      } catch (error) {
        // A newer snapshot may already be waiting. Never put this older one
        // back over it; the queued write will persist the latest answer.
        const newer = pending.get(key)
        if (!newer || newer.revision <= entry.revision) pending.set(key, entry)
        onError?.(error, entry)
        return false
      } finally {
        active.delete(key)
        notifyState()
      }
    }
    return true
  }

  function enqueue({ sessionId, questionId, payload }) {
    const normalizedSessionId = Number(sessionId)
    const normalizedQuestionId = Number(questionId)
    if (!normalizedSessionId || !normalizedQuestionId) return Promise.resolve(false)
    const key = keyFor(normalizedSessionId, normalizedQuestionId)
    pending.set(key, {
      key,
      sessionId: normalizedSessionId,
      questionId: normalizedQuestionId,
      payload: { ...payload },
      revision: ++revision,
    })
    notifyState()
    return appendDrain(key)
  }

  function retryPending() {
    return Promise.all([...pending.keys()].map(appendDrain))
  }

  async function waitForCurrentWrites() {
    await Promise.all([...chains.values()])
  }

  async function flushAll() {
    await waitForCurrentWrites()
    if (pending.size) {
      await retryPending()
      await waitForCurrentWrites()
    }
    if (pending.size) throw new Error('仍有答题内容未保存')
  }

  function hasPendingChanges() {
    return pending.size > 0 || active.size > 0 || chains.size > 0
  }

  return { enqueue, flushAll, retryPending, hasPendingChanges }
}
