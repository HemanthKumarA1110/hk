import AIReasoningPanel from '../components/AIReasoningPanel'

export default function AIPage() {
  return (
    <div>
      <header className="mb-6">
        <p className="text-violet-400 text-xs uppercase tracking-widest">AI Engine</p>
        <h2 className="text-3xl font-bold mt-1">Decision Reasoning</h2>
        <p className="text-slate-400 mt-1">ENTER / AVOID / EXIT with adaptive learning from journal</p>
      </header>
      <AIReasoningPanel />
    </div>
  )
}
