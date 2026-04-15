/**
 * Abbreviate a numeric value to K / M / B notation for executive-facing UI.
 * Rounds to 2-3 significant digits for a clean, uncluttered look.
 *
 * Examples: 453000 → "~450K", 1200000 → "~1.2M", 42 → "42", null → "—"
 *
 * Set `exact: true` to skip the tilde prefix (useful for axis ticks).
 */
export function formatAbbrevNumber(value, { dash = '—', exact = false } = {}) {
  if (value == null) return dash

  const abs = Math.abs(value)
  const sign = value < 0 ? '-' : ''
  const tilde = exact ? '' : '~'

  if (abs >= 1_000_000_000) {
    const v = abs / 1_000_000_000
    const s = v < 10 ? v.toFixed(1) : Math.round(v).toString()
    return sign + tilde + s + 'B'
  }
  if (abs >= 1_000_000) {
    const v = abs / 1_000_000
    const s = v < 10 ? v.toFixed(1) : Math.round(v).toString()
    return sign + tilde + s + 'M'
  }
  if (abs >= 1_000) {
    const v = abs / 1_000
    const rounded = v < 10 ? Math.round(v * 10) / 10 : Math.round(v / 5) * 5
    const s = rounded < 10 ? rounded.toFixed(1) : rounded.toString()
    return sign + tilde + s + 'K'
  }

  if (abs === 0) return '0'
  return sign + (abs === Math.floor(abs) ? String(abs) : abs.toFixed(1))
}

/**
 * Axis-tick formatter — abbreviated but without tilde prefix.
 */
export function formatAxisTick(value) {
  return formatAbbrevNumber(value, { exact: true })
}
