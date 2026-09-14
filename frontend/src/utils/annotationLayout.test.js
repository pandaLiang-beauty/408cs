import assert from 'node:assert/strict'
import test from 'node:test'
import { placeAnnotations } from './annotationLayout.js'

test('keeps sparse comments beside their questions rather than packing a sidebar list', () => {
  const layout = placeAnnotations([{ key: 'q4', anchorTop: 850, height: 180 }, { key: 'q8', anchorTop: 2450, height: 210 }])
  assert.deepEqual(layout.positions, { q4: 850, q8: 2450 })
})

test('stacks comments and a draft without overlap, then returns to the next question anchor', () => {
  const layout = placeAnnotations([
    { key: 'first', anchorTop: 500, height: 300 }, { key: 'draft', anchorTop: 500, height: 400 },
    { key: 'next', anchorTop: 1600, height: 200 },
  ])
  assert.equal(layout.positions.draft, 812)
  assert.equal(layout.positions.next, 1600)
})

test('reflows after a question expands and discards positions from another page', () => {
  const before = placeAnnotations([{ key: 'q2', anchorTop: 500, height: 200 }])
  const after = placeAnnotations([{ key: 'q2', anchorTop: 800, height: 200 }])
  assert.equal(after.positions.q2 - before.positions.q2, 300)
  assert.deepEqual(placeAnnotations([]).positions, {})
})
