import assert from 'node:assert/strict'
import test from 'node:test'
import { renderMarkdown } from './markdown.js'

test('renders headings, nested lists, tables and task lists used in study notes', () => {
  const html = renderMarkdown('# 要点\n\n- [x] 一项\n  - 子项\n\n| 方法 | 代价 |\n| --- | --- |\n| 查找 | O(n) |')
  for (const tag of ['<h1>要点</h1>', 'type="checkbox"', '<table>', '<td>O(n)</td>']) assert(html.includes(tag))
})

test('supports triple and Typora double highlight delimiters with inline formatting', () => {
  assert.match(renderMarkdown('===**平衡树**===，==高度=='), /<mark><strong>平衡树<\/strong><\/mark>，<mark>高度<\/mark>/)
  assert.match(renderMarkdown('===一=== 和 ===二==='), /<mark>一<\/mark> 和 <mark>二<\/mark>/)
  assert.doesNotMatch(renderMarkdown('===不配对=='), /<mark>/)
})

test('keeps highlight syntax literal in code and escaped text', () => {
  const html = renderMarkdown('`===代码===`\n\n```js\na === b\n==literal==\n```\n\n\\=\\=\\=原文\\=\\=\\=')
  assert.doesNotMatch(html, /<mark>/)
  assert(html.includes('a === b'))
  assert(html.includes('===原文==='))
})

test('retains existing plain-text line breaks', () => {
  assert.equal(renderMarkdown('第一行\n第二行'), '<p>第一行<br>\n第二行</p>\n')
})

test('does not execute HTML, event handlers, script links or trusted TeX commands', () => {
  const html = renderMarkdown('<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n[x](javascript:alert(1))\n\n![x](data:text/html,test)\n\n$\\href{javascript:alert(1)}{x}$')
  assert.doesNotMatch(html, /<script|<img[^>]+onerror|href="javascript:|src="data:text\/html/i)
  assert(html.includes('&lt;script&gt;'))
})

test('renders formulas with the same KaTeX version as the app stylesheet', () => {
  const html = renderMarkdown('复杂度 $O(n^2)$\n\n$$\\sum_{i=1}^n i$$')
  assert.match(html, /class="katex"/)
  assert.match(html, /class="katex-display"/)
  assert.match(html, /class="base"/)
})
