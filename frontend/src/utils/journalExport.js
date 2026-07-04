/** Download rows as UTF-8 CSV (opens in Excel). */
export function exportJournalExcel(rows, filenamePrefix = 'trade-journal') {
  const headers = [
    'Symbol',
    'Engine',
    'Side',
    'Quantity',
    'Lots',
    'P&L',
    'AI Score',
    'Status',
    'Entry DateTime',
    'Exit DateTime',
    'Source',
  ]

  const escape = (value) => {
    const text = value == null ? '' : String(value)
    return `"${text.replace(/"/g, '""')}"`
  }

  const lines = [
    headers.join(','),
    ...rows.map((row) =>
      [
        row.symbol,
        row.engine,
        row.side,
        row.qty,
        row.lots ?? '',
        row.pnl ?? '',
        row.ai_score ?? '',
        row.status,
        row.entry_datetime ?? '',
        row.exit_datetime ?? '',
        row.source ?? '',
      ]
        .map(escape)
        .join(',')
    ),
  ]

  const blob = new Blob(['\ufeff', lines.join('\n')], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${filenamePrefix}-${new Date().toISOString().slice(0, 10)}.csv`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

export function formatJournalDateTime(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('en-IN', {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    })
  } catch {
    return iso
  }
}

export function formatQtyLots(entry) {
  if (entry.engine === 'scalping') {
    const lots = entry.lots ?? entry.qty
    if (lots == null) return '—'
    return `${lots} lot${Number(lots) === 1 ? '' : 's'}`
  }
  if (entry.qty == null) return '—'
  return String(entry.qty)
}

export function todayIsoDate() {
  return new Date().toISOString().slice(0, 10)
}
