const DESK_PREFIX = {
  scalping: 'SCALP-',
  intraday: 'INTRA-',
  swing: 'SWING-',
}

/** Keep only strategies that belong to this desk (scalping / intraday / swing). */
export function filterStrategiesForDesk(engine, strategies = []) {
  const prefix = DESK_PREFIX[engine]
  if (!prefix) return []
  return (strategies || []).filter((s) => {
    const code = String(s?.code || '')
    const family = String(s?.family || s?.desk || '')
    return code.startsWith(prefix) || family === engine
  })
}

export function defaultStrategyCode(engine) {
  if (engine === 'swing') return 'SWING-EMA'
  if (engine === 'intraday') return 'INTRA-ORB'
  return 'SCALP-BT-001'
}
