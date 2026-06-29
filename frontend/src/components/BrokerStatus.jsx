export default function BrokerStatus({ status: externalStatus }) {
  const status = externalStatus

  if (!status) {
    return (
      <section className="p-4 rounded-xl border border-slate-800 bg-slate-900/60">
        <h2 className="text-xl font-semibold mb-3">Angel One Broker</h2>
        <p className="text-slate-400 text-sm">Loading broker status...</p>
      </section>
    )
  }

  return (
    <section className="p-4 rounded-xl border border-slate-800 bg-slate-900/60">
      <h2 className="text-xl font-semibold mb-3">Angel One Broker</h2>
      <div className="space-y-3 text-sm text-slate-300">
        <Row
          label="Connected"
          value={status.connected ? 'Yes' : 'No'}
          tone={status.connected ? 'good' : undefined}
        />
        <Row
          label="Session Valid"
          value={
            status.needs_reconnect
              ? 'No — reconnect required'
              : status.session_valid
                ? 'Yes'
                : status.connected
                  ? 'Unknown'
                  : 'N/A'
          }
          tone={status.session_valid ? 'good' : status.needs_reconnect ? 'warn' : undefined}
        />
        <Row label="Client Code" value={status.client_code || 'N/A'} />
        <Row label="Credentials Configured" value={status.credentials_configured ? 'Yes' : 'No'} />
        <Row label="Feed Token" value={status.feed_token_available ? 'Available' : 'Missing'} />
        <Row label="Session Expires" value={status.expires_at || 'N/A'} />
        <Row label="Redis Cache" value={status.cached_in_redis ? 'Active' : 'Inactive'} />
      </div>
    </section>
  )
}

function Row({ label, value, tone }) {
  const valueClass =
    tone === 'good' ? 'text-emerald-400' : tone === 'warn' ? 'text-amber-300' : undefined
  return (
    <div className="flex justify-between border-b border-slate-800 pb-2">
      <span className="text-slate-500">{label}</span>
      <span className={valueClass}>{value}</span>
    </div>
  )
}
