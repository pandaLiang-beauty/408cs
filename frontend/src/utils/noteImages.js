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
  return Array.from(event.clipboardData?.items || [])
    .filter((item) => item.kind === 'file' && item.type.startsWith('image/'))
    .map((item) => item.getAsFile())
    .filter(Boolean)
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

function wrapText(context, text, maxWidth) {
  const lines = []
  for (const paragraph of String(text || '').split('\n')) {
    if (!paragraph) {
      lines.push('')
      continue
    }
    let line = ''
    for (const char of paragraph) {
      const candidate = line + char
      if (line && context.measureText(candidate).width > maxWidth) {
        lines.push(line)
        line = char
      } else {
        line = candidate
      }
    }
    lines.push(line)
  }
  return lines
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

function canvasBlob(canvas) {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error('笔记图片生成失败')), 'image/png')
  })
}

export async function exportNoteAsPng(note, contextLabel = '') {
  const width = 1200
  const padding = 72
  const contentWidth = width - padding * 2
  const lineHeight = 52
  const probe = document.createElement('canvas').getContext('2d')
  probe.font = '32px "Microsoft YaHei", sans-serif'
  const lines = note.body ? wrapText(probe, note.body, contentWidth) : []
  const loadedImages = await Promise.all((note.images || []).map((item) => loadCanvasImage(item.url)))
  const imageLayouts = loadedImages.map(({ image }) => {
    const scale = Math.min(1, contentWidth / image.naturalWidth, 900 / image.naturalHeight)
    return { width: Math.round(image.naturalWidth * scale), height: Math.round(image.naturalHeight * scale) }
  })

  const textHeight = lines.length ? lines.length * lineHeight + 28 : 0
  const imagesHeight = imageLayouts.reduce((sum, item) => sum + item.height + 30, 0)
  const height = Math.max(460, 210 + textHeight + imagesHeight + 100)
  if (height > 30000) {
    loadedImages.forEach((item) => URL.revokeObjectURL(item.objectUrl))
    throw new Error('笔记内容过长，无法生成单张图片')
  }

  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  ctx.fillStyle = '#fdfdfb'
  ctx.fillRect(0, 0, width, height)
  ctx.fillStyle = '#b04a2f'
  ctx.fillRect(0, 0, 18, height)

  ctx.fillStyle = '#1c1a17'
  ctx.font = 'bold 44px "Microsoft YaHei", sans-serif'
  ctx.fillText('408 学习笔记', padding, 82)
  ctx.fillStyle = '#6d675d'
  ctx.font = '25px "Microsoft YaHei", sans-serif'
  ctx.fillText(contextLabel || '题目笔记', padding, 128, contentWidth)
  ctx.strokeStyle = '#ddd7cc'
  ctx.lineWidth = 2
  ctx.beginPath()
  ctx.moveTo(padding, 158)
  ctx.lineTo(width - padding, 158)
  ctx.stroke()

  let y = 215
  ctx.fillStyle = '#1c1a17'
  ctx.font = '32px "Microsoft YaHei", sans-serif'
  for (const line of lines) {
    ctx.fillText(line, padding, y)
    y += lineHeight
  }
  if (lines.length) y += 12

  try {
    loadedImages.forEach(({ image }, index) => {
      const layout = imageLayouts[index]
      ctx.fillStyle = '#ffffff'
      ctx.fillRect(padding, y, layout.width, layout.height)
      ctx.drawImage(image, padding, y, layout.width, layout.height)
      ctx.strokeStyle = '#ddd7cc'
      ctx.strokeRect(padding, y, layout.width, layout.height)
      y += layout.height + 30
    })
    ctx.fillStyle = '#6d675d'
    ctx.font = '22px "Microsoft YaHei", sans-serif'
    const timestamp = String(note.updated_at || note.created_at || '').replace('T', ' ').slice(0, 16)
    ctx.fillText(timestamp, padding, height - 52)
    saveBlob(await canvasBlob(canvas), `408-note-${note.id}.png`)
  } finally {
    loadedImages.forEach((item) => URL.revokeObjectURL(item.objectUrl))
  }
}
