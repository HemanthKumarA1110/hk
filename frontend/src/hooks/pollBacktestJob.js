const POLL_MS = 2500
const MAX_POLLS = 480

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

async function requestWithRetry(fn, retries = 3) {
  let lastErr
  for (let i = 0; i < retries; i += 1) {
    try {
      return await fn()
    } catch (err) {
      lastErr = err
      if (err.message !== 'Network Error' && err.code !== 'ECONNABORTED') throw err
      await sleep(1500 * (i + 1))
    }
  }
  throw lastErr
}

/** Poll a desk backtest job until completed, failed, or timeout. */
export async function pollBacktestJob(startJob, pollJob, onProgress) {
  const queued = await requestWithRetry(() => startJob())

  if (queued?.total_trades != null || queued?.ranking_table) {
    return queued
  }

  const jobId = queued?.job_id
  if (!jobId) {
    throw new Error('Backtest did not return a job id')
  }

  for (let i = 0; i < MAX_POLLS; i += 1) {
    await sleep(POLL_MS)
    const poll = await requestWithRetry(() => pollJob(jobId))
    const pct = Number(poll?.progress) || Math.min(95, 10 + i * 2)
    onProgress?.(pct)

    if (poll?.status === 'completed' || poll?.total_trades != null || poll?.ranking_table) {
      onProgress?.(100)
      return poll
    }
    if (poll?.status === 'failed') {
      throw new Error(poll.message || 'Backtest failed')
    }
    if (poll?.status === 'not_found') {
      throw new Error('Backtest job not found — it may have expired')
    }
  }

  throw new Error('Backtest still running — wait a minute and try polling again')
}
