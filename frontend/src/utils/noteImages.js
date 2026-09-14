import { renderMarkdown } from '@/utils/markdown'

const ACCEPTED_IMAGE_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/gif'])

export const NOTE_IMAGE_LIMIT = 8
export const NOTE_IMAGE_MAX_BYTES = 8 * 1024 * 1024
export const NOTE_IMAGE_TOTAL_BYTES = 24 * 1024 * 1024

export function validateNoteImageFiles(files, currentCount = 0, currentBytes = 0) {
  const images = Array.from(files || [])
  if (currentCount + images.length > NOTE_IMAGE_LIMIT) {
    throw new Error(`一条笔记最多 ${NOTE_IMAGE_LIMIT} 张图片`)
  }
  for (const file of images) {
    if (!ACCEPTED_IMAGE_TYPES.has(file.type)) {
      throw new Error('仅支持 PNG、JPEG、WebP 或 GIF 图片')
    }
    if (file.size > NOTE_IMAGE_MAX_BYTES) {
      throw new Error('单张图片不能超过 8 MB')
    }
  }
  const totalBytes = images.reduce((sum, file) => sum + file.size, currentBytes)
  if (totalBytes > NOTE_IMAGE_TOTAL_BYTES) {
    throw new Error('一条笔记图片总计不能超过 24 MB')
  }
  return images
}

export function clipboardImageFiles(event) {
  const files = Array.from(event.clipboardData?.items || [])
    .filter((item) => item.kind === 'file' && item.type.startsWith('image/'))
    .map((item) => item.getAsFile())
    .filter(Boolean)
  if (files.length) return files
  return Array.from(event.clipboardData?.files || [])
    .filter((file) => file.type.startsWith('image/'))
}

export async function readClipboardImageFiles() {
  const clipboard = globalThis.navigator?.clipboard
  if (!clipboard?.read) {
    throw new Error('当前浏览器不支持读取剪贴板，请在笔记输入框按 Ctrl+V / ⌘V 粘贴图片')
  }
  try {
    const items = await clipboard.read()
    const files = []
    for (const item of items) {
      // 同一张图片可能有多个格式，只读取其中一个，避免重复添加。
      const type = item.types.find((value) => ACCEPTED_IMAGE_TYPES.has(value))
        || item.types.find((value) => value.startsWith('image/'))
      if (!type) continue
      const blob = await item.getType(type)
      const extension = type === 'image/jpeg' ? 'jpg' : type.slice('image/'.length)
      files.push(new File([blob], `clipboard-${Date.now()}-${files.length + 1}.${extension}`, { type }))
    }
    return files
  } catch {
    throw new Error('无法读取剪贴板，请允许浏览器访问，或在笔记输入框按 Ctrl+V / ⌘V 粘贴图片')
  }
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result)
    reader.onerror = () => reject(new Error('图片读取失败'))
    reader.readAsDataURL(file)
  })
}

export async function filesToNotePayload(files) {
  return Promise.all(Array.from(files).map(async (file, index) => ({
    image_base64: await fileToDataUrl(file),
    filename: file.name || `clipboard-${Date.now()}-${index + 1}.png`,
  })))
}

export function makePendingImages(files) {
  return Array.from(files).map((file) => ({
    file,
    previewUrl: URL.createObjectURL(file),
  }))
}

export function releasePendingImages(items) {
  for (const item of items) URL.revokeObjectURL(item.previewUrl)
}


async function loadCanvasImage(url) {
  const response = await fetch(url, { credentials: 'same-origin' })
  if (!response.ok) throw new Error('笔记图片加载失败')
  const blob = await response.blob()
  const objectUrl = URL.createObjectURL(blob)
  try {
    const image = new Image()
    image.src = objectUrl
    await image.decode()
    return { image, objectUrl }
  } catch (error) {
    URL.revokeObjectURL(objectUrl)
    throw error
  }
}

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export async function exportNoteAsPng(note, contextLabel = '') {
  const { toBlob } = await import('html-to-image')
  const imageResults = await Promise.allSettled((note.images || []).map(item => loadCanvasImage(item.url)))
  const loadedImages = imageResults.filter(result => result.status === 'fulfilled').map(result => result.value)
  const root = document.createElement('section')
  root.className = 'note-export'
  root.style.cssText = 'position:fixed;left:-20000px;top:0'
  root.setAttribute('aria-hidden', 'true')
  try {
    const failed = imageResults.find(result => result.status === 'rejected')
    if (failed) throw failed.reason
    root.innerHTML = '<h1 class="note-export-title">408 学习笔记</h1><p class="note-export-source"></p><div class="note-export-body markdown-content"></div><div class="note-export-images"></div><p class="note-export-time"></p>'
    root.querySelector('.note-export-source').textContent = contextLabel || '题目笔记'
    root.querySelector('.note-export-body').innerHTML = renderMarkdown(note.body)
    root.querySelector('.note-export-time').textContent = String(note.updated_at || note.created_at || '').replace('T', ' ').slice(0, 16)
    for (const { image } of loadedImages) root.querySelector('.note-export-images').appendChild(image)
    document.body.appendChild(root)
    await Promise.all([...root.querySelectorAll('img')].map(image => image.decode()))
    // Force layout before waiting for the fonts used by this note's formulas.
    root.getBoundingClientRect()
    await document.fonts.ready
    const height = Math.ceil(root.getBoundingClientRect().height)
    if (height > 30000) throw new Error('笔记内容过长，无法生成单张图片')
    const blob = await toBlob(root, {
      pixelRatio: 1, width: 1200, height, backgroundColor: '#fdfdfb',
      style: { position: 'static', left: 'auto', top: 'auto' },
    })
    if (!blob) throw new Error('笔记图片生成失败')
    saveBlob(blob, '408-note-' + note.id + '.png')
  } finally {
    root.remove()
    loadedImages.forEach(item => URL.revokeObjectURL(item.objectUrl))
  }
}
