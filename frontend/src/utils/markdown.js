import MarkdownIt from 'markdown-it'
import mark from 'markdown-it-mark'
import taskLists from 'markdown-it-task-lists'
import { tex } from '@mdit/plugin-tex'
import katex from 'katex'

function tripleHighlight(md) {
  // A separate delimiter keeps ===…=== from consuming Typora's ==…== pairs.
  const marker = 0xE000
  md.inline.ruler.before('mark', 'triple_highlight', (state, silent) => {
    if (silent || state.src[state.pos] !== '=') return false
    const scanned = state.scanDelims(state.pos, true)
    if (scanned.length !== 3) return false
    state.push('text', '', 0).content = '==='
    state.delimiters.push({ marker, length: 0, jump: 0, token: state.tokens.length - 1,
      end: -1, open: scanned.can_open, close: scanned.can_close })
    state.pos += 3
    return true
  })
  md.inline.ruler2.before('mark', 'triple_highlight', state => {
    const groups = [state.delimiters, ...state.tokens_meta.filter(Boolean).map(meta => meta.delimiters).filter(Boolean)]
    for (const delimiters of groups) {
      for (const delimiter of delimiters) {
        if (delimiter.marker !== marker || delimiter.end < 0) continue
        const closing = delimiters[delimiter.end]
        for (const [index, nesting] of [[delimiter.token, 1], [closing.token, -1]]) {
          const token = state.tokens[index]
          Object.assign(token, { type: nesting === 1 ? 'mark_open' : 'mark_close', tag: 'mark', nesting, markup: '===', content: '' })
        }
      }
    }
  })
}

const markdown = new MarkdownIt({ html: false, breaks: true, linkify: true })
  .use(mark)
  .use(tripleHighlight)
  .use(taskLists)
  .use(tex, {
    delimiters: 'all', mathFence: true,
    render: (content, displayMode) => katex.renderToString(content, { displayMode, throwOnError: false, trust: false, strict: 'ignore' }),
  })

export function renderMarkdown(source = '') {
  return markdown.render(String(source || ''))
}
