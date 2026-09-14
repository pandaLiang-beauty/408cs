export const PAPER_ANNOTATIONS = Symbol('paper-annotations')

export function locateText(text, anchor) {
  const { quote, start_offset: start, end_offset: end, prefix = '', suffix = '' } = anchor
  if (!quote) return null
  if (Number.isInteger(start) && end > start && text.slice(start, end) === quote
      && (!prefix || text.slice(0, start).endsWith(prefix))
      && (!suffix || text.slice(end).startsWith(suffix))) return [start, end]
  const matches = []
  for (let offset = text.indexOf(quote); offset >= 0; offset = text.indexOf(quote, offset + 1)) {
    const before = text.slice(0, offset)
    const after = text.slice(offset + quote.length)
    const score = (prefix && before.endsWith(prefix) ? 1 : 0) + (suffix && after.startsWith(suffix) ? 1 : 0)
    matches.push({ offset, score })
  }
  matches.sort((a, b) => b.score - a.score)
  if (!matches.length || (matches.length > 1 && matches[0].score === matches[1].score)) return null
  return [matches[0].offset, matches[0].offset + quote.length]
}

export function regionElement(root, anchor) {
  const question = root?.querySelector(`[data-question-id="${Number(anchor.question_id)}"]`)
  if (anchor.region === 'question') return question
  return [...(question?.querySelectorAll('[data-annotation-region]') || [])]
    .find(element => element.dataset.annotationRegion === anchor.region) || null
}

function textNodes(element) {
  const walker = element.ownerDocument.createTreeWalker(element, 4) // SHOW_TEXT；偏移与 DOM Range 一致
  const nodes = []
  for (let node = walker.nextNode(); node; node = walker.nextNode()) nodes.push(node)
  return nodes
}

export function rangeForAnchor(element, anchor) {
  if (!element || anchor.region === 'question') return null
  const bounds = locateText(element.textContent, anchor)
  if (!bounds) return null
  const range = element.ownerDocument.createRange()
  let offset = 0
  let started = false
  for (const node of textNodes(element)) {
    const next = offset + node.length
    if (!started && bounds[0] <= next) {
      range.setStart(node, bounds[0] - offset)
      started = true
    }
    if (started && bounds[1] <= next) {
      range.setEnd(node, bounds[1] - offset)
      return range
    }
    offset = next
  }
  return null
}

export function selectionAnchor(root, selection = window.getSelection()) {
  if (!selection?.rangeCount || selection.isCollapsed) return null
  const range = selection.getRangeAt(0)
  const startElement = range.startContainer.nodeType === 1 ? range.startContainer : range.startContainer.parentElement
  const region = startElement?.closest('[data-annotation-region]')
  if (!region || !root?.contains(region) || !region.contains(range.endContainer)) return null
  const question = region.closest('[data-question-id]')
  if (!question) return null
  const prefixRange = range.cloneRange()
  prefixRange.selectNodeContents(region)
  prefixRange.setEnd(range.startContainer, range.startOffset)
  const start = prefixRange.toString().length
  const quote = range.toString()
  if (!quote.trim() || quote.length > 10000) return null
  const end = start + quote.length
  const text = region.textContent
  if (text.slice(start, end) !== quote) return null
  return {
    question_id: Number(question.dataset.questionId), region: region.dataset.annotationRegion,
    quote, start_offset: start, end_offset: end,
    prefix: Array.from(text.slice(0, start)).slice(-32).join(''),
    suffix: Array.from(text.slice(end)).slice(0, 32).join(''),
  }
}

export function pointInRange(range, x, y) {
  return range && [...range.getClientRects()].some(rect =>
    rect.width > 0 && rect.height > 0 && x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom)
}

const HIGHLIGHTS = ['cs408-comments', 'cs408-comment-active', 'cs408-comment-draft']

export function clearHighlights(root) {
  for (const name of HIGHLIGHTS) globalThis.CSS?.highlights?.delete(name)
  for (const mark of root?.querySelectorAll('mark[data-paper-annotation]') || []) mark.replaceWith(...mark.childNodes)
  for (const region of root?.querySelectorAll('[data-annotation-region]') || []) region.normalize()
  for (const question of root?.querySelectorAll('[data-active-question-annotation]') || []) question.removeAttribute('data-active-question-annotation')
}

function markFallback(element, anchor, active) {
  const bounds = locateText(element.textContent, anchor)
  if (!bounds) return
  let offset = 0
  for (const node of textNodes(element)) {
    const next = offset + node.length
    const start = Math.max(bounds[0] - offset, 0)
    const end = Math.min(bounds[1] - offset, node.length)
    if (end > start && node.parentElement?.namespaceURI === 'http://www.w3.org/1999/xhtml') {
      if (end < node.length) node.splitText(end)
      const selected = start ? node.splitText(start) : node
      const mark = element.ownerDocument.createElement('mark')
      mark.dataset.paperAnnotation = String(anchor.id || 'draft')
      mark.className = active ? 'annotation-mark annotation-mark-active' : 'annotation-mark'
      selected.replaceWith(mark)
      mark.append(selected)
    }
    offset = next
  }
}

export function paintHighlights(root, annotations, activeId, draft) {
  clearHighlights(root)
  const ranges = new Map()
  const all = []
  let activeRange = null
  const native = !!(globalThis.CSS?.highlights && globalThis.Highlight)
  const entries = [...annotations, ...(draft ? [{ ...draft, id: 'draft' }] : [])]
  for (const entry of entries) {
    const element = regionElement(root, entry)
    if (!element) continue
    const active = entry.id === activeId || entry.id === 'draft'
    if (entry.region === 'question' && active) element.setAttribute('data-active-question-annotation', '')
    if (entry.region !== 'question' && !native && (!entry.resolved || active)) markFallback(element, entry, active)
  }
  for (const entry of entries) {
    const range = rangeForAnchor(regionElement(root, entry), entry)
    if (!range) continue
    ranges.set(entry.id, range)
    if (entry.id === activeId) activeRange = range
    if (!entry.resolved && entry.id !== 'draft') all.push(range)
  }
  if (native) {
    CSS.highlights.set(HIGHLIGHTS[0], new Highlight(...all))
    CSS.highlights.set(HIGHLIGHTS[1], new Highlight(...(activeRange ? [activeRange] : [])))
    CSS.highlights.set(HIGHLIGHTS[2], new Highlight(...(ranges.has('draft') ? [ranges.get('draft')] : [])))
  }
  return ranges
}
