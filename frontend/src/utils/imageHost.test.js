import test from 'node:test'
import assert from 'node:assert/strict'
import { IMAGE_HOST_MAX_BYTES, hostedImageMarkdown, hostedImageUrl, validateHostedImage } from './imageHost.js'
import { renderMarkdown } from './markdown.js'

test('copied links use the public domain, with the browser origin as a development fallback', () => {
  assert.equal(hostedImageUrl({ public_url: 'https://408.example.test/api/image-host/files/a.png' }, 'http://localhost:5408'),
    'https://408.example.test/api/image-host/files/a.png')
  assert.equal(hostedImageUrl({ url: '/api/image-host/files/a.png' }, 'http://localhost:5408'),
    'http://localhost:5408/api/image-host/files/a.png')
})

test('filenames containing Markdown and HTML still produce exactly one safe image', () => {
  const url = 'https://408.example.test/api/image-host/files/a.png'
  const markdown = hostedImageMarkdown({ filename: '题目[1] ![x](bad)\\_<script>\n截图.png', public_url: url })
  const rendered = renderMarkdown(markdown)
  assert.equal((rendered.match(/<img /g) || []).length, 1)
  assert.ok(rendered.includes(`src="${url}"`))
  assert.ok(!rendered.includes('<script>'))
  assert.ok(!rendered.includes('<a '))
})

test('image validation accepts supported formats up to 8 MB and rejects empty or unsupported files', () => {
  for (const type of ['image/png', 'image/jpeg', 'image/webp', 'image/gif']) {
    assert.doesNotThrow(() => validateHostedImage({ type, size: IMAGE_HOST_MAX_BYTES }))
  }
  assert.throws(() => validateHostedImage({ type: 'image/png', size: IMAGE_HOST_MAX_BYTES + 1 }), /8 MB/)
  assert.throws(() => validateHostedImage({ type: 'image/png', size: 0 }), /为空/)
  assert.throws(() => validateHostedImage({ type: 'image/svg+xml', size: 10 }), /仅支持/)
})
