import api, { fetchStreamStatus, startMarketStream } from '../api'

const DESK_TIMEOUT_MS = 90000

/** @param {string} instrument */
export function fetchScalpingDesk(instrument) {
  return api.get(`/strategies/scalping/desk/${instrument}`, { timeout: DESK_TIMEOUT_MS }).then((res) => res.data)
}

/** @param {string} instrument */
export function evaluateScalpingDesk(instrument) {
  return api.post(`/strategies/scalping/desk/${instrument}/evaluate`, null, { timeout: DESK_TIMEOUT_MS }).then((res) => res.data)
}

/** @param {string} instrument @param {object} config */
export function saveScalpingDeskConfig(instrument, config) {
  return api.put(`/strategies/scalping/desk/${instrument}/config`, config).then((res) => res.data)
}

/** @param {string} instrument @param {boolean} enabled */
export function toggleScalpingAutoTrading(instrument, enabled) {
  return api.post(`/strategies/scalping/desk/${instrument}/auto-trading`, { enabled }).then((res) => res.data)
}

/** @param {string} instrument @param {object} payload */
export function runScalpingBacktest(instrument, payload) {
  return api.post(`/strategies/scalping/desk/${instrument}/backtest`, payload, { timeout: 60000 }).then((res) => res.data)
}

/** @param {string} instrument @param {string} jobId */
export function pollDeskBacktest(instrument, jobId) {
  return api.get(`/strategies/scalping/desk/${instrument}/backtest/${jobId}`, { timeout: 30000 }).then((res) => res.data)
}

/** @param {string} instrument @param {object} payload */
export function runSMCBacktest(instrument, payload) {
  return api.post(`/strategies/scalping/desk/${instrument}/smc/backtest`, payload, { timeout: 60000 }).then((res) => res.data)
}

/** @param {string} instrument @param {string} jobId */
export function pollSMCBacktest(instrument, jobId) {
  return api.get(`/strategies/scalping/desk/${instrument}/smc/backtest/${jobId}`, { timeout: 30000 }).then((res) => res.data)
}

/** @param {string} instrument @param {object} report */
export function applySMCStrategy(instrument, report) {
  return api.post(`/strategies/scalping/desk/${instrument}/smc/apply`, report).then((res) => res.data)
}

/** @param {string} instrument @param {object} summary */
export function optimizeScalpingStrategy(instrument, summary) {
  return api.post(`/strategies/scalping/desk/${instrument}/optimize`, { backtest_summary: summary }).then((res) => res.data)
}

/** @param {string} instrument @param {{ apply?: boolean, days?: number }} [payload] */
export function runWeeklyParameterTune(instrument, payload = {}) {
  return api.post(`/strategies/scalping/desk/${instrument}/weekly-tune`, payload).then((res) => res.data)
}

export async function ensureMarketStream() {
  const status = await fetchStreamStatus().catch(() => null)
  if (status?.connected) return status
  return startMarketStream().catch(() => null)
}

export function wsMarketUrl() {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${protocol}://${window.location.host}/api/v1/market/ws`
}
