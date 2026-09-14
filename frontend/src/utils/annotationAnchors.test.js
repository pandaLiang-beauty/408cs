import assert from 'node:assert/strict'
import test from 'node:test'
import { locateText } from './annotationAnchors.js'

test('keeps the selected occurrence when the same phrase appears more than once', () => {
  assert.deepEqual(locateText('甲条件，乙条件', { quote: '条件', start_offset: 5, end_offset: 7 }), [5, 7])
})

test('finds the original quote after text is inserted before it', () => {
  assert.deepEqual(locateText('新增文字：甲条件，乙条件', { quote: '条件', start_offset: 5, end_offset: 7, prefix: '乙' }), [10, 12])
})

test('does not silently highlight an ambiguous or missing quote', () => {
  assert.equal(locateText('条件，条件', { quote: '条件', start_offset: 99, end_offset: 101 }), null)
  assert.equal(locateText('已修改的题干', { quote: '原来的文字', start_offset: 0, end_offset: 5 }), null)
})

test('uses context when a different occurrence moved into the old offset', () => {
  assert.deepEqual(locateText('甲条件，乙条件', { quote: '条件', start_offset: 1, end_offset: 3, prefix: '乙' }), [5, 7])
})

test('retains UTF-16 offsets, spaces and newlines across inline elements', () => {
  const text = '公式😀：n\n  + 1'
  const quote = '😀：n\n  + 1'
  assert.deepEqual(locateText(text, { quote, start_offset: 2, end_offset: text.length }), [2, text.length])
})
