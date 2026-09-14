import assert from 'node:assert/strict'
import test from 'node:test'
import { placeAnnotations } from './annotationLayout.js'

test('keeps sparse comments beside their text anchors', () => {
  const layout = placeAnnotations([{ key: 'q4', anchorTop: 850, height: 180 }, { key: 'q8', anchorTop: 2450, height: 210 }])
  assert.deepEqual(layout.positions, { q4: 850, q8: 2450 })
})

test('orders comments by text position even when created in reverse order in the same question', () => {
  const layout = placeAnnotations([
    { key: 'later-paragraph', anchorTop: 900, height: 100 },
    { key: 'earlier-paragraph', anchorTop: 300, height: 100 },
  ])
  assert.deepEqual(layout.positions, { 'earlier-paragraph': 300, 'later-paragraph': 900 })
})

test('keeps the selected comment at its text and moves overlapping neighbors aside', () => {
  const layout = placeAnnotations([
    { key: 'before', anchorTop: 700, height: 200 },
    { key: 'selected', anchorTop: 750, height: 200 },
    { key: 'after', anchorTop: 800, height: 100 },
  ], 12, 'selected')
  assert.equal(layout.positions.selected, 750)
  assert.equal(layout.positions.before, 538)
  assert.equal(layout.positions.after, 962)
})

test('keeps crowded comments inside the page when there is no room above the selected text', () => {
  const layout = placeAnnotations([
    { key: 'before', anchorTop: 0, height: 200 },
    { key: 'middle', anchorTop: 10, height: 100 },
    { key: 'selected', anchorTop: 40, height: 100 },
  ], 12, 'selected')
  assert.equal(layout.positions.before, 0)
  assert.equal(layout.positions.middle, 212)
  assert.equal(layout.positions.selected, 324)
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
