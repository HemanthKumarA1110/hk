export default function EquityChart({ points = [] }) {
  const width = 600
  const height = 240
  const padding = 24

  if (!points.length) {
    return (
      <div className="p-4 bg-white rounded-xl shadow-sm border border-slate-200">
        <h2 className="text-xl font-semibold mb-3">Equity Curve</h2>
        <p className="text-sm text-slate-500">No chart data available yet.</p>
      </div>
    )
  }

  const max = Math.max(...points)
  const min = Math.min(...points)
  const range = max - min || 1

  const path = points
    .map((point, index) => {
      const x = padding + (index / (points.length - 1)) * (width - padding * 2)
      const y = height - padding - ((point - min) / range) * (height - padding * 2)
      return `${index === 0 ? 'M' : 'L'} ${x} ${y}`
    })
    .join(' ')

  return (
    <div className="p-4 bg-white rounded-xl shadow-sm border border-slate-200">
      <h2 className="text-xl font-semibold mb-3">Equity Curve</h2>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-60">
        <path d={path} fill="none" stroke="#2563eb" strokeWidth="3" />
        <line x1={padding} y1={padding} x2={padding} y2={height - padding} stroke="#cbd5e1" />
        <line x1={padding} y1={height - padding} x2={width - padding} y2={height - padding} stroke="#cbd5e1" />
        <text x={padding} y={padding - 6} className="text-xs fill-slate-500">{max.toFixed(2)}</text>
        <text x={padding} y={height - 6} className="text-xs fill-slate-500">{min.toFixed(2)}</text>
      </svg>
    </div>
  )
}
