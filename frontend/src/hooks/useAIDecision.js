/**
 * AI decisions are computed server-side and attached to each signal.
 * This hook extracts AI fields for UI display.
 * @param {object|null} desk
 */
export function useAIDecision(desk) {
  const latest = desk?.signal || desk?.signals?.[0] || null
  return {
    latest,
    ai: latest?.ai || null,
    approved: latest?.status === 'approved',
    reasoning: latest?.ai?.reasoning || '',
    confidence: latest?.ai?.confidence ?? 0,
    action: latest?.ai?.action || 'SKIP',
  }
}
