export const IMAGE_HOST_ACCEPT = 'image/png,image/jpeg,image/webp,image/gif'
export const IMAGE_HOST_MAX_BYTES = 8 * 1024 * 1024

export function validateHostedImage(file) {
  if (!IMAGE_HOST_ACCEPT.split(',').includes(file.type)) {
    throw new Error('仅支持 PNG、JPEG、WebP 或 GIF 图片')
  }
  if (!file.size) throw new Error('图片为空')
  if (file.size > IMAGE_HOST_MAX_BYTES) throw new Error('单张图片不能超过 8 MB')
}

export function hostedImageUrl(image, origin = globalThis.location?.origin) {
  return new URL(image.public_url || image.url, origin).href
}

export function hostedImageMarkdown(image, origin) {
  // 文件名只是替代文字；转义标记，避免方括号等字符破坏 Markdown 图片语法。
  const alt = String(image.filename || '图片').replace(/[\r\n]/g, ' ').replace(/[\\`*_[\]<>!]/g, '\\$&')
  return `![${alt}](<${hostedImageUrl(image, origin)}>)`
}

export async function copyImageLink(value) {
  try {
    await navigator.clipboard.writeText(value)
    return
  } catch {
    // 局域网 HTTP 或浏览器权限限制时，仍允许通过用户点击复制。
  }
  const previous = document.activeElement
  const input = document.createElement('textarea')
  input.value = value
  input.style.cssText = 'position:fixed;left:-9999px;top:0'
  document.body.appendChild(input)
  input.select()
  try {
    if (!document.execCommand('copy')) throw new Error('复制失败，请选中链接后手动复制')
  } finally {
    input.remove()
    previous?.focus({ preventScroll: true })
  }
}
