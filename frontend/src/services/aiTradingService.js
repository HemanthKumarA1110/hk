/**
 * AI trading helpers for scalping desk.
 * Backend runs DecisionEngine; frontend displays results from desk payload.
 */

/** @param {object} signal */
export function aiActionLabel(signal) {
  const ai = signal?.ai
  if (!ai) return 'Pending'
  if (ai.action === 'ENTER') return `Enter (${ai.confidence}%)`
  if (ai.action === 'EXIT') return 'Exit'
  return `Skip (${ai.confidence}%)`
}

/** @param {object} signal */
export function isAiApproved(signal) {
  return signal?.ai?.action === 'ENTER' && Number(signal?.ai?.confidence) >= 70
}
