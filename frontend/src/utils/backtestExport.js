/** Export backtest result rows to UTF-8 CSV (opens in Excel). */
export function exportBacktestResultsExcel(rows, filenamePrefix = 'backtest-results') {
  const headers = [
    'Run ID',
    'Run Date',
    'Engine',
    'Strategy',
    'Symbol',
    'Period From',
    'Period To',
    'Interval',
    'Trades',
    'Win Rate %',
    'Total P&L',
    'Max Drawdown',
    'Profit Factor',
    'AI Entry',
    'AI Exit',
    'Status',
    'Data Source',
  ]

  const escape = (value) => {
    const text = value == null ? '' : String(value)
    return `"${text.replace(/"/g, '""')}"`
  }

  const lines = [
    headers.join(','),
    ...rows.map((row) =>
      [
        row.run_id,
        row.created_at,
        row.engine,
        row.strategy_code,
        row.symbol,
        row.from_date,
        row.to_date,
        row.interval,
        row.total_trades,
        row.win_rate,
        row.total_pnl,
        row.max_drawdown,
        row.profit_factor,
        row.ai_entry,
        row.ai_exit,
        row.status,
        row.data_source,
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

export function formatRunDate(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('en-IN', {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    })
  } catch {
    return iso
  }
}

export function todayIsoDate() {
  return new Date().toISOString().slice(0, 10)
}
