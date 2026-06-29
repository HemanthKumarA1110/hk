/** Extract displayable available margin from broker funds API response. */
export function formatAvailableMargin(funds, brokerStatus) {
  if (!brokerStatus?.connected) {
    return { text: 'Connect broker', tone: 'muted' }
  }

  if (funds?.status === false && funds?.message) {
    const msg = funds.message.toLowerCase()
    if (msg.includes('rate limit') || msg.includes('reconnect')) {
      return { text: 'Reconnect broker', tone: 'muted' }
    }
    return { text: 'Unavailable', tone: 'muted' }
  }

  const cash = funds?.data?.availablecash
  if (cash !== undefined && cash !== null && cash !== '') {
    const amount = Number(cash)
    if (!Number.isNaN(amount)) {
      return { text: `₹${amount.toLocaleString('en-IN')}`, tone: 'good' }
    }
  }

  if (funds === null) {
    return { text: 'Loading…', tone: 'muted' }
  }

  return { text: 'Unavailable', tone: 'muted' }
}
