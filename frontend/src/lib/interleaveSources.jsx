import { Fragment } from 'react'
import SourceChip from '../components/ui/SourceChip'

const SRC_RE = /\[src:(\d+)\]/g

/**
 * Split text on [src:N] markers; render plain segments with renderPlain, SourceChip for citations.
 */
export function interleaveSources(text, catalog, renderPlain) {
  if (text == null || text === '') return null
  if (!catalog?.length) return renderPlain(text)

  const nodes = []
  let last = 0
  let m
  const re = new RegExp(SRC_RE.source, 'g')
  let k = 0
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) {
      nodes.push(<Fragment key={`t-${k++}`}>{renderPlain(text.slice(last, m.index))}</Fragment>)
    }
    const n = parseInt(m[1], 10)
    const art = catalog.find((a) => a.index === n)
    nodes.push(<SourceChip key={`s-${k++}`} n={n} article={art} catalog={catalog} />)
    last = m.index + m[0].length
  }
  if (last < text.length) {
    nodes.push(<Fragment key={`t-${k++}`}>{renderPlain(text.slice(last))}</Fragment>)
  }
  return nodes
}
