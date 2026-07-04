/**
 * @typedef {'nifty50' | 'banknifty'} ScalpingInstrument
 */

/**
 * @typedef {Object} ScalpingConfig
 * @property {number} capital
 * @property {number} max_loss_per_day
 * @property {number} max_trades_per_day
 * @property {'1m' | '3m'} timeframe
 * @property {boolean} auto_trading_enabled
 * @property {number} lot_size
 * @property {number} strategy_version
 */

/**
 * @typedef {Object} ScalpingSignal
 * @property {string} signal_type
 * @property {number} strike
 * @property {string} option_symbol
 * @property {number} entry
 * @property {number} target
 * @property {number} stoploss
 * @property {string} timeframe
 * @property {Object} indicators
 * @property {Object} [ai]
 * @property {string} status
 */

export const INSTRUMENT_META = {
  nifty50: { label: 'Nifty 50 Scalping', underlying: 'NIFTY', lotSize: 25, tvSymbol: 'NSE:NIFTY' },
  banknifty: { label: 'Bank Nifty Scalping', underlying: 'BANKNIFTY', lotSize: 15, tvSymbol: 'NSE:BANKNIFTY' },
}
