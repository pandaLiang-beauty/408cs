import assert from 'node:assert/strict'
import test from 'node:test'

import { createAnswerSaveQueue } from './answerSaveQueue.js'

test('serializes one question and persists the latest choice after a delayed write', async () => {
  const calls = []
  let releaseFirst
  const firstWrite = new Promise(resolve => { releaseFirst = resolve })
  const queue = createAnswerSaveQueue({
    save: async entry => {
      calls.push(entry.payload.chosen)
      if (calls.length === 1) await firstWrite
    },
  })

  queue.enqueue({ sessionId: 4, questionId: 8, payload: { chosen: 'A', fuzzy: false } })
  await Promise.resolve()
  queue.enqueue({ sessionId: 4, questionId: 8, payload: { chosen: 'B', fuzzy: false } })
  releaseFirst()

  await queue.flushAll()
  assert.deepEqual(calls, ['A', 'B'])
  assert.equal(queue.hasPendingChanges(), false)
})

test('keeps a failed answer pending and retries it during flush', async () => {
  let attempts = 0
  const errors = []
  const queue = createAnswerSaveQueue({
    save: async () => {
      attempts += 1
      if (attempts === 1) throw new Error('temporary network failure')
    },
    onError: error => errors.push(error.message),
  })

  queue.enqueue({ sessionId: 4, questionId: 8, payload: { chosen: 'C', fuzzy: true } })
  await queue.flushAll()

  assert.equal(attempts, 2)
  assert.deepEqual(errors, ['temporary network failure'])
  assert.equal(queue.hasPendingChanges(), false)
})

test('does not restore an older failed choice over a newer pending choice', async () => {
  const calls = []
  let rejectFirst
  const firstWrite = new Promise((_, reject) => { rejectFirst = reject })
  const queue = createAnswerSaveQueue({
    save: async entry => {
      calls.push(entry.payload.chosen)
      if (calls.length === 1) await firstWrite
    },
  })

  queue.enqueue({ sessionId: 4, questionId: 8, payload: { chosen: 'A', fuzzy: false } })
  await Promise.resolve()
  queue.enqueue({ sessionId: 4, questionId: 8, payload: { chosen: 'D', fuzzy: false } })
  rejectFirst(new Error('old request failed'))

  await queue.flushAll()
  assert.deepEqual(calls, ['A', 'D'])
  assert.equal(queue.hasPendingChanges(), false)
})
