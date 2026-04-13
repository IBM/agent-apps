import { useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  USE_CASES,
  STATUS_LABELS,
  type Status,
  type UseCaseType,
} from '../data/usecases'

const TYPE_CONFIG: Record<UseCaseType, { label: string; icon: string; activeCls: string; inactiveCls: string }> = {
  'event-driven': { label: 'Event-driven', icon: '⚡', activeCls: 'bg-amber-900/60 text-amber-200 border-amber-500',    inactiveCls: 'bg-amber-900/20 text-amber-500 border-amber-800/50 hover:border-amber-600 hover:text-amber-300' },
  'documents':    { label: 'Documents',    icon: '📄', activeCls: 'bg-cyan-900/60 text-cyan-200 border-cyan-500',       inactiveCls: 'bg-cyan-900/20 text-cyan-500 border-cyan-800/50 hover:border-cyan-600 hover:text-cyan-300' },
  'ppt':          { label: 'PPT',          icon: '📊', activeCls: 'bg-orange-900/60 text-orange-200 border-orange-500', inactiveCls: 'bg-orange-900/20 text-orange-500 border-orange-800/50 hover:border-orange-600 hover:text-orange-300' },
  'audio':        { label: 'Audio',        icon: '🎙', activeCls: 'bg-pink-900/60 text-pink-200 border-pink-500',       inactiveCls: 'bg-pink-900/20 text-pink-500 border-pink-800/50 hover:border-pink-600 hover:text-pink-300' },
  'video':        { label: 'Video',        icon: '🎬', activeCls: 'bg-violet-900/60 text-violet-200 border-violet-500', inactiveCls: 'bg-violet-900/20 text-violet-500 border-violet-800/50 hover:border-violet-600 hover:text-violet-300' },
  'images':       { label: 'Images',       icon: '🖼', activeCls: 'bg-teal-900/60 text-teal-200 border-teal-500',       inactiveCls: 'bg-teal-900/20 text-teal-500 border-teal-800/50 hover:border-teal-600 hover:text-teal-300' },
  'other':        { label: 'Other',        icon: '✦',  activeCls: 'bg-gray-700/60 text-gray-200 border-gray-500',       inactiveCls: 'bg-gray-800/20 text-gray-500 border-gray-700/50 hover:border-gray-500 hover:text-gray-300' },
}

function TypeBadge({ type }: { type: UseCaseType }) {
  const { label, icon, activeCls } = TYPE_CONFIG[type]
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded font-medium border ${activeCls}`}>
      {icon} {label}
    </span>
  )
}

const ALL_TYPES = Object.keys(TYPE_CONFIG) as UseCaseType[]

function TypeFilterChips({
  value,
  onChange,
}: {
  value: UseCaseType | 'all'
  onChange: (v: UseCaseType | 'all') => void
}) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="text-xs text-gray-600 font-medium uppercase tracking-wider">Type:</span>
      {ALL_TYPES.map((t) => {
        const { label, icon, activeCls, inactiveCls } = TYPE_CONFIG[t]
        const active = value === t
        return (
          <button
            key={t}
            onClick={() => onChange(active ? 'all' : t)}
            className={`text-xs px-2.5 py-1 rounded-full font-medium border transition-all ${active ? activeCls : inactiveCls}`}
          >
            {icon} {label}
          </button>
        )
      })}
    </div>
  )
}

const STATUS_ICON: Record<Status, string> = {
  working: '✅',
  partial: '🔧',
  gap: '❌',
}

// ── Use case table ────────────────────────────────────────────────────────────

interface TableProps {
  useCases: typeof USE_CASES
  search: string
  filterStatus: Status | 'all'
  filterType: UseCaseType | 'all'
}

function UseCaseTable({ useCases, search, filterStatus, filterType }: TableProps) {
  const navigate = useNavigate()

  const filtered = useCases.filter((uc) => {
    const matchesSearch =
      !search ||
      uc.name.toLowerCase().includes(search.toLowerCase()) ||
      uc.tagline.toLowerCase().includes(search.toLowerCase()) ||
      uc.channels.some((c) => c.toLowerCase().includes(search.toLowerCase()))
    const matchesStatus = filterStatus === 'all' || uc.status === filterStatus
    const matchesType = filterType === 'all' || uc.type === filterType
    return matchesSearch && matchesStatus && matchesType
  })

  if (filtered.length === 0) {
    return <div className="py-8 text-center text-gray-600 text-sm">No use cases match your filters.</div>
  }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
      <table className="w-full">
        <thead>
          <tr className="border-b border-gray-800 bg-gray-900/80">
            <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3 w-6">#</th>
            <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-3 py-3">Use Case</th>
            <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-3 py-3 hidden md:table-cell">Type</th>
            <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-3 py-3 hidden lg:table-cell">Channels</th>
            <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-3 py-3">Status</th>
            <th className="px-3 py-3 w-10"></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-800/50">
          {filtered.map((uc, i) => {
            const statusInfo = STATUS_LABELS[uc.status]
            return (
              <tr
                key={uc.id}
                onClick={() => navigate(`/use-case/${uc.id}`)}
                className="hover:bg-gray-800/40 cursor-pointer transition-colors group"
              >
                <td className="px-5 py-3.5 text-gray-600 text-sm font-mono">{i + 1}</td>
                <td className="px-3 py-3.5">
                  <div className="font-medium text-gray-200 text-sm group-hover:text-indigo-300 transition-colors">
                    {uc.name}
                  </div>
                  <div className="text-xs text-gray-500 mt-0.5">{uc.tagline}</div>
                </td>
                <td className="px-3 py-3.5 hidden md:table-cell">
                  <TypeBadge type={uc.type} />
                </td>
                <td className="px-3 py-3.5 hidden lg:table-cell">
                  <div className="flex flex-wrap gap-1">
                    {uc.channels.slice(0, 3).map((c) => (
                      <span key={c} className="text-xs font-mono text-gray-500 bg-gray-800 px-1.5 py-0.5 rounded">
                        {c}
                      </span>
                    ))}
                    {uc.channels.length > 3 && (
                      <span className="text-xs text-gray-600">+{uc.channels.length - 3}</span>
                    )}
                  </div>
                </td>
                <td className="px-3 py-3.5">
                  <span className="text-xs">
                    {STATUS_ICON[uc.status]} <span className={`text-${statusInfo.color}-400`}>{statusInfo.label}</span>
                  </span>
                </td>
                <td className="px-3 py-3.5 text-right" onClick={(e) => e.stopPropagation()}>
                  {uc.comingSoon ? (
                    <span className="inline-block px-2.5 py-1 text-xs font-medium bg-gray-800 text-gray-500 border border-gray-700 rounded-md whitespace-nowrap">
                      Coming soon
                    </span>
                  ) : uc.appUrl ? (
                    <a
                      href={uc.appUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-block px-2.5 py-1 text-xs font-medium bg-indigo-600 hover:bg-indigo-500 text-white rounded-md transition-colors whitespace-nowrap"
                    >
                      Try it now →
                    </a>
                  ) : (
                    <span className="text-gray-700 text-sm">→</span>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function Home() {
  const [search, setSearch] = useState('')
  const [filterStatus, setFilterStatus] = useState<Status | 'all'>('all')
  const [filterType, setFilterType] = useState<UseCaseType | 'all'>('all')

  const counts = useMemo(() => ({
    working: USE_CASES.filter((u) => u.status === 'working').length,
    partial: USE_CASES.filter((u) => u.status === 'partial').length,
    gap:     USE_CASES.filter((u) => u.status === 'gap').length,
  }), [])

  const tableProps = { search, filterStatus, filterType }

  return (
    <div className="p-6 max-w-7xl mx-auto">

      {/* ── Hero ── */}
      <div className="mb-8">
        <h2 className="text-2xl font-semibold text-white mb-2">CUGA++ Use Cases</h2>
        <p className="text-gray-400 text-sm max-w-2xl mb-5">
          <span className="text-emerald-400 font-medium">Automated Pipelines</span> — agents that run on
          schedules and react to system events. One I/O runtime, zero boilerplate.
        </p>

        {/* Stats */}
        <div className="grid grid-cols-3 gap-3 max-w-lg mb-6">
          <div className="bg-green-900/20 border border-green-800/30 rounded-lg p-3">
            <div className="text-2xl font-bold text-green-400">{counts.working}</div>
            <div className="text-xs text-green-600 mt-0.5">Working demos</div>
          </div>
          <div className="bg-yellow-900/20 border border-yellow-800/30 rounded-lg p-3">
            <div className="text-2xl font-bold text-yellow-400">{counts.partial}</div>
            <div className="text-xs text-yellow-600 mt-0.5">Partial / setup required</div>
          </div>
          <div className="bg-gray-800/50 border border-gray-700/30 rounded-lg p-3">
            <div className="text-2xl font-bold text-gray-500">{counts.gap}</div>
            <div className="text-xs text-gray-600 mt-0.5">On roadmap</div>
          </div>
        </div>
      </div>

      {/* ── Filters ── */}
      <div className="flex flex-col gap-3 mb-6">
        <div className="flex flex-wrap gap-3">
          <input
            type="text"
            placeholder="Search use cases, channels..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="px-3 py-1.5 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-indigo-500 w-64"
          />
          <select
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value as Status | 'all')}
            className="px-3 py-1.5 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 focus:outline-none focus:border-indigo-500"
          >
            <option value="all">All statuses</option>
            <option value="working">Working</option>
            <option value="partial">Partial</option>
            <option value="gap">Gap</option>
          </select>
          {(search || filterStatus !== 'all' || filterType !== 'all') && (
            <button
              onClick={() => { setSearch(''); setFilterStatus('all'); setFilterType('all') }}
              className="px-3 py-1.5 text-sm text-gray-500 hover:text-gray-300 transition-colors"
            >
              Clear all
            </button>
          )}
        </div>
        <TypeFilterChips value={filterType} onChange={setFilterType} />
      </div>

      {/* ── Use cases table ── */}
      <UseCaseTable useCases={USE_CASES} {...tableProps} />

      <p className="mt-4 text-xs text-gray-600">
        Click any row to see architecture, run instructions, and how CUGA++ powers it.
      </p>
    </div>
  )
}
