import axios from 'axios'

const configuredBase = import.meta.env.VITE_API_BASE
// Same-origin /api/v1 in Docker (nginx proxy). localhost:8000 only when explicitly set.
const API_BASE =
  configuredBase && configuredBase !== 'undefined' ? String(configuredBase).replace(/\/$/, '') : ''

const api = axios.create({
  baseURL: API_BASE ? `${API_BASE}/api/v1` : '/api/v1',
  timeout: 60000,
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config
    if (error.response?.status === 401 && !original._retry) {
      original._retry = true
      const refreshToken = localStorage.getItem('refresh_token')
      if (refreshToken) {
        try {
          const { data } = await axios.post(
            API_BASE ? `${API_BASE}/api/v1/auth/refresh` : '/api/v1/auth/refresh',
            {
              refresh_token: refreshToken,
            }
          )
          localStorage.setItem('access_token', data.access_token)
          localStorage.setItem('refresh_token', data.refresh_token)
          original.headers.Authorization = `Bearer ${data.access_token}`
          return api(original)
        } catch {
          localStorage.removeItem('access_token')
          localStorage.removeItem('refresh_token')
        }
      }
    }
    return Promise.reject(error)
  }
)

export const login = (username, password) =>
  api.post('/auth/login', { username, password }).then((res) => res.data)

export const register = (payload) =>
  api.post('/auth/register', payload).then((res) => res.data)

export const fetchMe = () => api.get('/auth/me').then((res) => res.data)

export const changePassword = (payload) =>
  api.post('/auth/change-password', payload).then((res) => res.data)

export const listUsers = () => api.get('/users/').then((res) => res.data)

export const createUser = (payload) =>
  api.post('/users/', payload).then((res) => res.data)

export const updateUser = (userId, payload) =>
  api.patch(`/users/${userId}`, payload).then((res) => res.data)

export const resetUserPassword = (userId, newPassword) =>
  api.post(`/users/${userId}/reset-password`, { new_password: newPassword }).then((res) => res.data)

export const fetchUserBrokerStatus = (userId) =>
  api.get(`/users/${userId}/broker/status`).then((res) => res.data)

export const saveUserBrokerCredentials = (userId, payload) =>
  api.post(`/users/${userId}/broker/credentials`, payload).then((res) => res.data)

export const connectUserBroker = (userId) =>
  api.post(`/users/${userId}/broker/connect`).then((res) => res.data)

export const saveBrokerCredentials = (payload) =>
  api.post('/broker/credentials', payload).then((res) => res.data)

export const connectBroker = () => api.post('/broker/connect').then((res) => res.data)

export const fetchBrokerStatus = () => api.get('/broker/status').then((res) => res.data)

export const fetchBrokerFunds = () =>
  api.get('/broker/funds', { timeout: 45000 }).then((res) => res.data)

export const fetchBrokerAccount = () =>
  api.get('/broker/account', { timeout: 45000 }).then((res) => res.data)

export const cancelBrokerOrder = (orderId, variety = 'NORMAL') =>
  api.delete(`/broker/orders/${orderId}`, { params: { variety } }).then((res) => res.data)

export const fetchServices = () => {
  const servicesUrl = API_BASE ? `${API_BASE}/api/v1/services` : '/api/v1/services'
  return axios.get(servicesUrl).then((res) => res.data)
}

export const fetchStreamStatus = () => api.get('/market/stream/status').then((res) => res.data)

export const fetchIndexQuotes = () => api.get('/market/indices/live').then((res) => res.data)

export const fetchLatestScan = () => api.get('/market/scan/latest').then((res) => res.data)

export const searchSymbols = (query, exchange = 'NSE', limit = 15) =>
  api
    .get('/market/symbols/search', { params: { q: query, exchange, limit } })
    .then((res) => res.data)

export const fetchOptionChain = (underlying) =>
  api.get(`/market/option-chain/${underlying}`).then((res) => res.data)

export const startMarketStream = () => api.post('/market/stream/start').then((res) => res.data)

export const stopMarketStream = () => api.post('/market/stream/stop').then((res) => res.data)

export const fetchScalpingSignals = () => api.get('/strategies/scalping').then((res) => res.data)

export const fetchScalpingDesk = (instrument) =>
  api.get(`/strategies/scalping/desk/${instrument}`, { timeout: 90000 }).then((res) => res.data)
export const fetchScalpingStrategies = (instrument) =>
  api.get(`/strategies/scalping/desk/${instrument}/strategies`).then((res) => res.data)
export const evaluateScalpingDesk = (instrument) =>
  api.post(`/strategies/scalping/desk/${instrument}/evaluate`, null, { timeout: 90000 }).then((res) => res.data)
export const saveScalpingDeskConfig = (instrument, config) =>
  api.put(`/strategies/scalping/desk/${instrument}/config`, config).then((res) => res.data)
export const toggleScalpingAutoTrading = (instrument, enabled) =>
  api.post(`/strategies/scalping/desk/${instrument}/auto-trading`, { enabled }).then((res) => res.data)
export const closeActiveScalpingTrade = (instrument) =>
  api.post(`/strategies/scalping/desk/${instrument}/close-active`).then((res) => res.data)
export const runScalpingDeskBacktest = (instrument, payload) =>
  api.post(`/strategies/scalping/desk/${instrument}/backtest`, payload, { timeout: 300000 }).then((res) => res.data)
export const optimizeScalpingDesk = (instrument, summary) =>
  api.post(`/strategies/scalping/desk/${instrument}/optimize`, { backtest_summary: summary }).then((res) => res.data)
export const runWeeklyParameterTune = (instrument, payload = {}) =>
  api.post(`/strategies/scalping/desk/${instrument}/weekly-tune`, payload).then((res) => res.data)

export const fetchIntradaySignals = () => api.get('/strategies/intraday').then((res) => res.data)
export const fetchIntradayStrategies = () => api.get('/strategies/intraday/strategies').then((res) => res.data)

export const scanIntradayPicks = () =>
  api.post('/strategies/intraday/scan', null, { timeout: 300000 }).then((res) => res.data)
export const fetchIntradayDesk = () =>
  api.get('/strategies/intraday/desk', { timeout: 90000 }).then((res) => res.data)
export const saveIntradayDeskConfig = (config) =>
  api.put('/strategies/intraday/desk/config', config).then((res) => res.data)
export const toggleIntradayAutoTrading = (enabled) =>
  api.post('/strategies/intraday/desk/auto-trading', { enabled }).then((res) => res.data)
export const evaluateIntradayDesk = () =>
  api.post('/strategies/intraday/desk/evaluate', null, { timeout: 120000 }).then((res) => res.data)
export const fetchSwingSignals = () => api.get('/strategies/swing').then((res) => res.data)
export const fetchSwingStrategies = () => api.get('/strategies/swing/strategies').then((res) => res.data)

export const scanSwingPicks = () =>
  api.post('/strategies/swing/scan', null, { timeout: 180000 }).then((res) => res.data)
export const fetchSwingDesk = () =>
  api.get('/strategies/swing/desk', { timeout: 90000 }).then((res) => res.data)
export const saveSwingDeskConfig = (config) =>
  api.put('/strategies/swing/desk/config', config).then((res) => res.data)
export const toggleSwingAutoTrading = (enabled) =>
  api.post('/strategies/swing/desk/auto-trading', { enabled }).then((res) => res.data)
export const evaluateSwingDesk = () =>
  api.post('/strategies/swing/desk/evaluate', null, { timeout: 120000 }).then((res) => res.data)
export const fetchStrategyStatus = () => api.get('/strategies/status').then((res) => res.data)
export const runStrategies = () => api.post('/strategies/run').then((res) => res.data)

export const fetchAIDecisions = () => api.get('/ai/decisions').then((res) => res.data)
export const fetchJournalInsights = () => api.get('/ai/journal/insights').then((res) => res.data)
export const runAIEvaluation = () => api.post('/ai/evaluate').then((res) => res.data)
export const fetchAIWeights = () => api.get('/ai/weights').then((res) => res.data)

export const fetchRiskStatus = () => api.get('/risk/status').then((res) => res.data)
export const fetchRiskLimits = () => api.get('/risk/limits').then((res) => res.data)
export const updateRiskLimits = (payload) => api.patch('/risk/limits', payload).then((res) => res.data)
export const evaluateRiskTrade = (payload) => api.post('/risk/evaluate', payload).then((res) => res.data)
export const resetRiskHalt = () => api.post('/risk/reset-halt').then((res) => res.data)

export const fetchAdminOverview = () => api.get('/admin/overview').then((res) => res.data)
export const fetchEquityCurve = () => api.get('/admin/equity-curve').then((res) => res.data)
export const fetchAdminJournal = (params) =>
  api.get('/admin/journal', { params }).then((res) => res.data)

export const exportAdminJournal = (params) =>
  api.get('/admin/journal/export', { params, responseType: 'blob' }).then((res) => res.data)
export const fetchBacktestPreview = () => api.get('/admin/backtest/preview').then((res) => res.data)

export const fetchPortfolioSummary = () => api.get('/portfolio/summary').then((res) => res.data)
export const fetchAlertsStatus = () => api.get('/alerts/status').then((res) => res.data)

export const fetchBacktestStatus = () => api.get('/backtest/status').then((res) => res.data)
export const runBacktest = (payload) => api.post('/backtest/run', payload).then((res) => res.data)
export const fetchBacktestRun = (runId) => api.get(`/backtest/runs/${runId}`).then((res) => res.data)
export const fetchBacktestRuns = () => api.get('/backtest/runs').then((res) => res.data)

export const fetchBacktestResults = (params) =>
  api.get('/backtest/results', { params }).then((res) => res.data)

export const exportBacktestResults = (params) =>
  api.get('/backtest/results/export', { params, responseType: 'blob' }).then((res) => res.data)

export const clearBacktestResults = (params) =>
  api.delete('/backtest/results', { params }).then((res) => res.data)

export const fetchOrderStatus = () => api.get('/orders/status').then((res) => res.data)
export const fetchAutoTrading = () => api.get('/orders/auto').then((res) => res.data)
export const updateAutoTrading = (payload) => api.put('/orders/auto', payload).then((res) => res.data)
export const runAutoTradingNow = (engine) =>
  api.post('/orders/auto/run', null, { params: engine ? { engine } : {} }).then((res) => res.data)
export const placeOrder = (payload) => api.post('/orders', payload).then((res) => res.data)
export const fetchOrders = () => api.get('/orders').then((res) => res.data)
export const fetchOrderBook = () => api.get('/orders/book').then((res) => res.data)
export const fetchOrderTrades = () => api.get('/orders/trades').then((res) => res.data)
export const cancelOrder = (orderId, variety = 'NORMAL') =>
  api.delete(`/orders/${orderId}`, { params: { variety } }).then((res) => res.data)

export default api
