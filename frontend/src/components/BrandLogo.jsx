import { APP_NAME, APP_TAGLINE } from '../config/brand'

const SIZES = {
  sm: {
    mark: 'w-8 h-8 text-[10px] rounded-lg',
    name: 'text-base',
    tagline: 'text-[9px]',
    gap: 'gap-2',
  },
  md: {
    mark: 'w-10 h-10 text-xs rounded-xl',
    name: 'text-lg',
    tagline: 'text-[10px]',
    gap: 'gap-3',
  },
  lg: {
    mark: 'w-16 h-16 text-sm rounded-2xl',
    name: 'text-4xl',
    tagline: 'text-xs',
    gap: 'gap-4',
  },
}

/** HK Quant wordmark + monogram mark */
export default function BrandLogo({ size = 'md', showTagline = false, className = '' }) {
  const s = SIZES[size] || SIZES.md
  const [first, ...rest] = APP_NAME.split(' ')
  const suffix = rest.join(' ') || ''

  return (
    <div className={`flex items-center ${s.gap} ${className}`}>
      <div
        className={`${s.mark} shrink-0 flex items-center justify-center font-bold tracking-tight bg-gradient-to-br from-emerald-500/25 to-cyan-500/10 border border-emerald-500/35 text-emerald-300 shadow-lg shadow-emerald-500/5`}
        aria-hidden
      >
        {first}
      </div>
      <div className="min-w-0">
        <p className={`${s.name} font-bold tracking-tight leading-none`}>
          <span className="text-emerald-400">{first}</span>
          {suffix ? ` ${suffix}` : ''}
        </p>
        {showTagline && (
          <p className={`${s.tagline} text-slate-500 uppercase tracking-widest mt-1`}>{APP_TAGLINE}</p>
        )}
      </div>
    </div>
  )
}
