import { useCallback, useEffect, useRef, useState } from 'react'
import { useAuth } from '../context/AuthContext'

const STORAGE_PREFIX = 'trading-notepad:'

function storageKey(userId) {
  return `${STORAGE_PREFIX}${userId ?? 'guest'}`
}

function formatSavedAt(iso) {
  if (!iso) return null
  try {
    return new Date(iso).toLocaleString('en-IN', {
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    })
  } catch {
    return iso
  }
}

export default function NotepadPage() {
  const { user } = useAuth()
  const [text, setText] = useState('')
  const [savedAt, setSavedAt] = useState(null)
  const [dirty, setDirty] = useState(false)
  const saveTimer = useRef(null)

  useEffect(() => {
    const key = storageKey(user?.id)
    try {
      const raw = localStorage.getItem(key)
      if (raw) {
        const parsed = JSON.parse(raw)
        setText(parsed.content ?? '')
        setSavedAt(parsed.savedAt ?? null)
      } else {
        setText('')
        setSavedAt(null)
      }
    } catch {
      setText(localStorage.getItem(key) || '')
    }
    setDirty(false)
  }, [user?.id])

  const persist = useCallback(
    (content) => {
      const key = storageKey(user?.id)
      const saved = new Date().toISOString()
      localStorage.setItem(key, JSON.stringify({ content, savedAt: saved }))
      setSavedAt(saved)
      setDirty(false)
    },
    [user?.id]
  )

  const handleChange = (value) => {
    setText(value)
    setDirty(true)
    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => persist(value), 600)
  }

  useEffect(() => {
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current)
    }
  }, [])

  const handleSaveNow = () => {
    if (saveTimer.current) clearTimeout(saveTimer.current)
    persist(text)
  }

  const handleClear = () => {
    if (!text.trim()) return
    if (!window.confirm('Clear all notes? This cannot be undone.')) return
    const key = storageKey(user?.id)
    localStorage.removeItem(key)
    setText('')
    setSavedAt(null)
    setDirty(false)
  }

  return (
    <div className="flex flex-col h-[calc(100vh-8rem)] min-h-[420px]">
      <header className="mb-4 flex flex-wrap items-start justify-between gap-4 shrink-0">
        <div>
          <p className="text-amber-400 text-xs uppercase tracking-widest">Personal</p>
          <h2 className="text-3xl font-bold mt-1">Notepad</h2>
          <p className="text-slate-400 mt-1 text-sm">
            Jot down reminders, levels, and trade ideas — auto-saved in this browser
            {user?.username ? ` for ${user.username}` : ''}.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-slate-500">
            {dirty ? 'Unsaved changes…' : savedAt ? `Saved ${formatSavedAt(savedAt)}` : 'Empty'}
          </span>
          <button
            type="button"
            onClick={handleSaveNow}
            disabled={!dirty}
            className="rounded-lg border border-slate-700 px-3 py-2 text-sm hover:bg-slate-800 disabled:opacity-40"
          >
            Save now
          </button>
          <button
            type="button"
            onClick={handleClear}
            disabled={!text.trim()}
            className="rounded-lg border border-rose-500/40 text-rose-300 hover:bg-rose-500/10 px-3 py-2 text-sm disabled:opacity-40"
          >
            Clear
          </button>
        </div>
      </header>

      <section className="flex-1 flex flex-col rounded-xl border border-amber-500/20 bg-gradient-to-b from-amber-500/5 to-slate-900/60 overflow-hidden min-h-0">
        <div className="px-4 py-2 border-b border-amber-500/10 flex justify-between text-xs text-slate-500">
          <span>{text.length.toLocaleString()} characters</span>
          <span>{text.split(/\n/).length} lines</span>
        </div>
        <textarea
          value={text}
          onChange={(e) => handleChange(e.target.value)}
          placeholder={`Trade reminders, key levels, rules to follow…\n\nExample:\n• Max 3 scalps per session\n• No trades first 15 min\n• Bank Nifty SL: 40 pts`}
          className="flex-1 w-full resize-none bg-transparent px-4 py-3 text-slate-100 placeholder:text-slate-600 focus:outline-none text-sm leading-relaxed font-mono min-h-0"
          spellCheck
        />
      </section>
    </div>
  )
}
