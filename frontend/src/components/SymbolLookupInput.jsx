import { useEffect, useRef, useState } from 'react'
import { searchSymbols } from '../api'

function normalizeSymbol(value) {
  const trimmed = (value || '').trim().toUpperCase()
  if (!trimmed) return ''
  if (trimmed.includes('-')) return trimmed
  return `${trimmed}-EQ`
}

export default function SymbolLookupInput({
  value,
  onChange,
  onSelect,
  exchange = 'NSE',
  placeholder = 'e.g. SBIN or RELIANCE',
}) {
  const [input, setInput] = useState(value || '')
  const [suggestions, setSuggestions] = useState([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const containerRef = useRef(null)
  const debounceRef = useRef(null)

  useEffect(() => {
    setInput((value || '').replace('-EQ', ''))
  }, [value])

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (containerRef.current && !containerRef.current.contains(event.target)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)

    const query = input.trim()
    if (query.length < 1) {
      setSuggestions([])
      setLoading(false)
      return undefined
    }

    debounceRef.current = setTimeout(async () => {
      setLoading(true)
      try {
        const data = await searchSymbols(query, exchange)
        setSuggestions(data.results || [])
        setOpen(true)
      } catch {
        setSuggestions([])
      } finally {
        setLoading(false)
      }
    }, 300)

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [input, exchange])

  const handleInputChange = (event) => {
    setInput(event.target.value)
    setOpen(true)
  }

  const handleSelect = (hit) => {
    const display = hit.symbol.replace('-EQ', '')
    setInput(display)
    onChange?.(hit.symbol)
    onSelect?.(hit)
    setOpen(false)
    setSuggestions([])
  }

  const handleBlur = () => {
    window.setTimeout(() => {
      if (input.trim()) {
        onChange?.(normalizeSymbol(input))
      }
    }, 150)
  }

  return (
    <div ref={containerRef} className="relative">
      <input
        value={input}
        onChange={handleInputChange}
        onFocus={() => suggestions.length > 0 && setOpen(true)}
        onBlur={handleBlur}
        placeholder={placeholder}
        autoComplete="off"
        className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
      />
      {loading && (
        <span className="absolute right-3 top-2.5 text-[10px] text-slate-500">Searching…</span>
      )}
      {open && suggestions.length > 0 && (
        <ul className="absolute z-20 mt-1 max-h-56 w-full overflow-auto rounded-lg border border-slate-700 bg-slate-950 shadow-xl">
          {suggestions.map((hit) => (
            <li key={`${hit.symbol}-${hit.token}`}>
              <button
                type="button"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => handleSelect(hit)}
                className="w-full text-left px-3 py-2 hover:bg-slate-800 border-b border-slate-800/80 last:border-0"
              >
                <div className="flex justify-between gap-2">
                  <span className="font-medium text-sm">{hit.symbol.replace('-EQ', '')}</span>
                  <span className="text-[10px] text-slate-500 shrink-0">{hit.exchange}</span>
                </div>
                <p className="text-xs text-slate-500 truncate">{hit.name}</p>
              </button>
            </li>
          ))}
        </ul>
      )}
      {open && !loading && input.trim().length >= 1 && suggestions.length === 0 && (
        <div className="absolute z-20 mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-500">
          No NSE equity matches. Connect Angel One for live search.
        </div>
      )}
    </div>
  )
}
