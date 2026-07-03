import { describe, expect, it } from 'vitest'
import { renderMarkdown } from './md'

describe('renderMarkdown', () => {
  it('escapes HTML so player input cannot inject markup', () => {
    expect(renderMarkdown('<script>alert(1)</script>')).toBe(
      '&lt;script&gt;alert(1)&lt;/script&gt;',
    )
    expect(renderMarkdown('a & b < c > d')).toBe('a &amp; b &lt; c &gt; d')
  })

  it('renders bold, italics, and inline code', () => {
    expect(renderMarkdown('**bold**')).toBe('<strong>bold</strong>')
    expect(renderMarkdown('*sneaky*')).toBe('<em>sneaky</em>')
    expect(renderMarkdown('roll `2d6+3` now')).toBe('roll <code>2d6+3</code> now')
  })

  it('handles bold and italics in the same string', () => {
    expect(renderMarkdown('**Mira** swings *wildly*')).toBe(
      '<strong>Mira</strong> swings <em>wildly</em>',
    )
  })

  it('converts newlines to <br/>', () => {
    expect(renderMarkdown('line one\nline two')).toBe('line one<br/>line two')
  })

  it('escapes before formatting (no tag smuggling through markdown)', () => {
    expect(renderMarkdown('**<img src=x onerror=alert(1)>**')).toBe(
      '<strong>&lt;img src=x onerror=alert(1)&gt;</strong>',
    )
  })

  it('passes plain text through unchanged', () => {
    expect(renderMarkdown('The goblin misses.')).toBe('The goblin misses.')
  })
})
