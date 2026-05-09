import { useMemo, useState } from 'react'
import {
  getDemoLocationOverride,
  setDemoLocationOverride,
  type LocationContext,
} from '../../lib/location'

type DemoPreset = {
  key: string
  label: string
  location: LocationContext | null
  note: string
}

const PRESETS: DemoPreset[] = [
  {
    key: 'auto',
    label: 'Auto',
    location: null,
    note: 'Uses browser locale and timezone',
  },
  {
    key: 'safe',
    label: 'Safe GB',
    location: { country: 'GB', city: 'London' },
    note: 'Expected normal behavior',
  },
  {
    key: 'restricted',
    label: 'Restricted NG',
    location: { country: 'NG', city: 'Lagos' },
    note: 'Use when NG is in FRAUD_RESTRICTED_COUNTRIES',
  },
  {
    key: 'anomaly',
    label: 'Anomaly DE',
    location: { country: 'DE', city: 'Berlin' },
    note: 'Good for geolocation baseline anomaly demos',
  },
]

interface DemoControlPanelProps {
  compact?: boolean
}

export function DemoControlPanel({ compact = false }: DemoControlPanelProps) {
  const [expanded, setExpanded] = useState(false)
  const [active, setActive] = useState<LocationContext | null>(() => getDemoLocationOverride())

  const activeLabel = useMemo(() => {
    if (!active) return 'Auto'
    const match = PRESETS.find(
      p => p.location?.country === active.country && p.location?.city === active.city
    )
    return match ? match.label : `${active.country ?? '??'} ${active.city ?? ''}`.trim()
  }, [active])

  function applyPreset(preset: DemoPreset) {
    setDemoLocationOverride(preset.location)
    setActive(preset.location)
  }

  return (
    <div className={`fixed z-50 ${compact ? 'bottom-3 left-3' : 'bottom-4 right-4'}`}>
      <div className="bg-[#0A0F0A] text-white border border-white/10 rounded-lg shadow-xl w-[320px]">
        <button
          type="button"
          onClick={() => setExpanded(v => !v)}
          className="w-full px-3 py-2.5 flex items-center justify-between text-left hover:bg-white/5 transition-colors rounded-t-lg"
        >
          <span className="text-[11px] font-semibold tracking-widest uppercase">
            Demo Mode
          </span>
          <span className="text-[10px] text-emerald-300 tracking-wider uppercase">
            {activeLabel}
          </span>
        </button>

        {expanded && (
          <div className="px-3 pb-3 space-y-3 border-t border-white/10">
            <div className="pt-2 text-[10px] text-white/60 leading-relaxed">
              Controls request location headers for localhost presentation scenarios.
            </div>

            <div className="grid grid-cols-2 gap-2">
              {PRESETS.map(preset => {
                const selected =
                  (!active && preset.location === null) ||
                  (active?.country === preset.location?.country &&
                    active?.city === preset.location?.city)
                return (
                  <button
                    key={preset.key}
                    type="button"
                    onClick={() => applyPreset(preset)}
                    className={`px-2 py-2 text-[10px] rounded border transition-colors ${
                      selected
                        ? 'border-emerald-400 bg-emerald-500/10 text-emerald-300'
                        : 'border-white/15 text-white/75 hover:bg-white/5'
                    }`}
                    title={preset.note}
                  >
                    {preset.label}
                  </button>
                )
              })}
            </div>

            <div className="text-[10px] text-white/60 space-y-1">
              <p>Presentation Checklist:</p>
              <p>1. Secure login + role session</p>
              <p>2. MFA verify flow</p>
              <p>3. Fraud scoring via location switch</p>
              <p>4. Audit logs via Audit Trail page</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

