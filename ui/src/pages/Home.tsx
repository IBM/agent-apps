import { useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  USE_CASES,
  CATEGORIES,
  STATUS_LABELS,
  type Status,
  type UseCaseType,
  type Category,
} from '../data/usecases'

const STARRED_IDS = new Set(['deck-forge', 'drop-summarizer', 'smart-todo', 'video-qa'])

const TYPE_CONFIG: Record<UseCaseType, { label: string; icon: string; activeCls: string }> = {
  'event-driven': { label: 'Event-driven', icon: '⚡', activeCls: 'bg-amber-500 text-white border-amber-500' },
  'documents':    { label: 'Documents',    icon: '📄', activeCls: 'bg-cyan-500 text-white border-cyan-500' },
  'ppt':          { label: 'PPT',          icon: '📊', activeCls: 'bg-orange-500 text-white border-orange-500' },
  'audio':        { label: 'Audio',        icon: '🎙', activeCls: 'bg-pink-500 text-white border-pink-500' },
  'video':        { label: 'Video',        icon: '🎬', activeCls: 'bg-violet-500 text-white border-violet-500' },
  'images':       { label: 'Images',       icon: '🖼', activeCls: 'bg-teal-500 text-white border-teal-500' },
  'other':        { label: 'Other',        icon: '✦',  activeCls: 'bg-t2 text-tsurf border-t2' },
}

// Inline type badge (always displayed with its accent color)
const TYPE_BADGE_CLS: Record<UseCaseType, string> = {
  'event-driven': 'bg-amber-500/10 text-amber-600 border-amber-500/30',
  'documents':    'bg-cyan-500/10 text-cyan-600 border-cyan-500/30',
  'ppt':          'bg-orange-500/10 text-orange-600 border-orange-500/30',
  'audio':        'bg-pink-500/10 text-pink-600 border-pink-500/30',
  'video':        'bg-violet-500/10 text-violet-600 border-violet-500/30',
  'images':       'bg-teal-500/10 text-teal-600 border-teal-500/30',
  'other':        'bg-tsurf2 text-t3 border-tborder',
}

function TypeBadge({ type }: { type: UseCaseType }) {
  const { label, icon } = TYPE_CONFIG[type]
  return (
    <span className={`text-sm px-2 py-0.5 rounded font-medium border ${TYPE_BADGE_CLS[type]}`}>
      {icon} {label}
    </span>
  )
}

const ALL_TYPES = Object.keys(TYPE_CONFIG) as UseCaseType[]
const ALL_CATEGORIES = Object.keys(CATEGORIES) as Category[]

function TypeFilterChips({
  value,
  onChange,
}: {
  value: UseCaseType | 'all'
  onChange: (v: UseCaseType | 'all') => void
}) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="text-xs text-t4 font-medium uppercase tracking-wider w-16 shrink-0">Type</span>
      {ALL_TYPES.map((t) => {
        const { label, icon, activeCls } = TYPE_CONFIG[t]
        const active = value === t
        return (
          <button
            key={t}
            onClick={() => onChange(active ? 'all' : t)}
            className={`text-xs px-2.5 py-1 rounded-full font-medium border transition-all ${
              active ? activeCls : 'bg-tsurf border-tborder text-t3 hover:text-t2 hover:border-t3'
            }`}
          >
            {icon} {label}
          </button>
        )
      })}
    </div>
  )
}

function CategoryFilterChips({
  value,
  onChange,
}: {
  value: Category | 'all'
  onChange: (v: Category | 'all') => void
}) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="text-xs text-t4 font-medium uppercase tracking-wider w-16 shrink-0">Category</span>
      {ALL_CATEGORIES.map((cat) => {
        const active = value === cat
        return (
          <button
            key={cat}
            onClick={() => onChange(active ? 'all' : cat)}
            className={`text-xs px-2.5 py-1 rounded-full font-medium border transition-all ${
              active
                ? 'bg-indigo-600 text-white border-indigo-600'
                : 'bg-tsurf border-tborder text-t3 hover:text-t2 hover:border-t3'
            }`}
          >
            {CATEGORIES[cat].label}
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
  filterCategory: Category | 'all'
}

function UseCaseTable({ useCases, search, filterStatus, filterType, filterCategory }: TableProps) {
  const navigate = useNavigate()

  const filtered = useCases.filter((uc) => {
    const matchesSearch =
      !search ||
      uc.name.toLowerCase().includes(search.toLowerCase()) ||
      uc.tagline.toLowerCase().includes(search.toLowerCase())
    const matchesStatus = filterStatus === 'all' || uc.status === filterStatus
    const matchesType = filterType === 'all' || uc.type === filterType
    const matchesCategory = filterCategory === 'all' || uc.category === filterCategory
    return matchesSearch && matchesStatus && matchesType && matchesCategory
  })

  if (filtered.length === 0) {
    return <div className="py-8 text-center text-t3 text-sm">No use cases match your filters.</div>
  }

  return (
    <div className="bg-tsurf border border-tborder rounded-xl overflow-hidden">
      <table className="w-full">
        <thead>
          <tr className="border-b border-tborder bg-tsurf2">
            <th className="text-left text-xs font-semibold text-t4 uppercase tracking-wider px-5 py-3.5 w-6">#</th>
            <th className="text-left text-xs font-semibold text-t4 uppercase tracking-wider px-3 py-3.5">Use Case</th>
            <th className="text-left text-xs font-semibold text-t4 uppercase tracking-wider px-3 py-3.5 hidden md:table-cell">Type</th>
            <th className="text-left text-xs font-semibold text-t4 uppercase tracking-wider px-3 py-3.5 hidden lg:table-cell">Category</th>
            <th className="text-left text-xs font-semibold text-t4 uppercase tracking-wider px-3 py-3.5 hidden xl:table-cell">Tools</th>
            <th className="text-left text-xs font-semibold text-t4 uppercase tracking-wider px-3 py-3.5 hidden xl:table-cell">ENV Vars</th>
            <th className="text-left text-xs font-semibold text-t4 uppercase tracking-wider px-3 py-3.5">Status</th>
            <th className="px-3 py-3.5 w-10"></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-tb2">
          {filtered.map((uc, i) => {
            const statusInfo = STATUS_LABELS[uc.status]
            const catInfo = CATEGORIES[uc.category]
            const visibleTools = uc.tools.slice(0, 3)
            const extraTools = uc.tools.length - visibleTools.length
            const UNIVERSAL_VARS = ['LLM_PROVIDER', 'LLM_MODEL', 'RITS_API_KEY', 'ANTHROPIC_API_KEY', 'OPENAI_API_KEY']
            const appEnvs = uc.howToRun.envVars.filter(v => !UNIVERSAL_VARS.includes(v))
            const visibleEnvs = appEnvs.slice(0, 3)
            const extraEnvs = appEnvs.length - visibleEnvs.length
            return (
              <tr
                key={uc.id}
                onClick={() => navigate(`/use-case/${uc.id}`)}
                className="hover:bg-tsurf2 cursor-pointer transition-colors group"
              >
                <td className="px-5 py-4 text-t4 text-sm font-mono">{i + 1}</td>
                <td className="px-3 py-4">
                  <div className="font-semibold text-t1 text-base group-hover:text-indigo-500 transition-colors">
                    {uc.name}{STARRED_IDS.has(uc.id) && <span className="text-amber-500 ml-1 font-bold">*</span>}
                  </div>
                  <div className="text-sm text-t3 mt-0.5">{uc.tagline}</div>
                </td>
                <td className="px-3 py-4 hidden md:table-cell">
                  <TypeBadge type={uc.type} />
                </td>
                <td className="px-3 py-4 hidden lg:table-cell">
                  <span className="text-sm px-2 py-0.5 rounded-full font-medium bg-tsurf2 text-t3 border border-tborder">
                    {catInfo.label}
                  </span>
                </td>
                <td className="px-3 py-4 hidden xl:table-cell">
                  {uc.tools.length === 0 ? (
                    <span className="text-sm text-t4">—</span>
                  ) : (
                    <div className="flex flex-wrap gap-1">
                      {visibleTools.map((t) => (
                        <span key={t} className="text-xs px-1.5 py-0.5 rounded font-mono bg-tsurf2 text-t3 border border-tborder whitespace-nowrap">
                          {t}
                        </span>
                      ))}
                      {extraTools > 0 && (
                        <span className="text-xs px-1.5 py-0.5 rounded bg-tsurf2 text-t4 border border-tborder">
                          +{extraTools}
                        </span>
                      )}
                    </div>
                  )}
                </td>
                <td className="px-3 py-4 hidden xl:table-cell">
                  {uc.howToRun.envVars.length === 0 ? (
                    <span className="text-sm text-t4">—</span>
                  ) : (
                    <div className="flex flex-wrap gap-1">
                      {visibleEnvs.map((v) => (
                        <span key={v} className="text-xs px-1.5 py-0.5 rounded font-mono bg-amber-500/10 text-amber-600 border border-amber-500/20 whitespace-nowrap">
                          {v}
                        </span>
                      ))}
                      {extraEnvs > 0 && (
                        <span className="text-xs px-1.5 py-0.5 rounded bg-tsurf2 text-t4 border border-tborder">
                          +{extraEnvs}
                        </span>
                      )}
                    </div>
                  )}
                </td>
                <td className="px-3 py-4">
                  <span className="text-sm">
                    {STATUS_ICON[uc.status]} <span className={`text-${statusInfo.color}-500`}>{statusInfo.label}</span>
                  </span>
                </td>
                <td className="px-3 py-4 text-right" onClick={(e) => e.stopPropagation()}>
                  {uc.comingSoon ? (
                    <span className="inline-block px-2.5 py-1 text-xs font-medium bg-tsurf2 text-t4 border border-tborder rounded-md whitespace-nowrap">
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
                    <span className="text-t4 text-sm">→</span>
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
  const [filterCategory, setFilterCategory] = useState<Category | 'all'>('all')

  const counts = useMemo(() => ({
    working: USE_CASES.filter((u) => u.status === 'working').length,
    partial: USE_CASES.filter((u) => u.status === 'partial').length,
    gap:     USE_CASES.filter((u) => u.status === 'gap').length,
  }), [])

  const tableProps = { search, filterStatus, filterType, filterCategory }

  return (
    <div className="p-4">

      {/* ── Hero ── */}
      <div className="mb-8">
        <h2 className="text-2xl font-semibold text-t1 mb-2">CUGA Apps</h2>
        {/* Stats */}
        <div className="grid grid-cols-3 gap-3 max-w-lg mb-6">
          <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-lg p-3">
            <div className="text-2xl font-bold text-emerald-500">{counts.working}</div>
            <div className="text-xs text-emerald-500/70 mt-0.5">Working demos</div>
          </div>
          <div className="bg-amber-500/10 border border-amber-500/20 rounded-lg p-3">
            <div className="text-2xl font-bold text-amber-500">{counts.partial}</div>
            <div className="text-xs text-amber-500/70 mt-0.5">Partial / setup required</div>
          </div>
          <div className="bg-tsurf2 border border-tborder rounded-lg p-3">
            <div className="text-2xl font-bold text-t4">{counts.gap}</div>
            <div className="text-xs text-t4 mt-0.5">On roadmap</div>
          </div>
        </div>
      </div>

      {/* ── Filters ── */}
      <div className="flex flex-col gap-3 mb-6">
        <div className="flex flex-wrap gap-3">
          <input
            type="text"
            placeholder="Search use cases..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="px-3 py-1.5 bg-tsurf border border-tborder rounded-lg text-sm text-t1 placeholder-t4 focus:outline-none focus:border-indigo-500 w-64"
          />
          <select
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value as Status | 'all')}
            className="px-3 py-1.5 bg-tsurf border border-tborder rounded-lg text-sm text-t2 focus:outline-none focus:border-indigo-500"
          >
            <option value="all">All statuses</option>
            <option value="working">Working</option>
            <option value="partial">Partial</option>
            <option value="gap">Gap</option>
          </select>
          {(search || filterStatus !== 'all' || filterType !== 'all' || filterCategory !== 'all') && (
            <button
              onClick={() => { setSearch(''); setFilterStatus('all'); setFilterType('all'); setFilterCategory('all') }}
              className="px-3 py-1.5 text-sm text-t3 hover:text-t2 transition-colors"
            >
              Clear all
            </button>
          )}
        </div>
        <TypeFilterChips value={filterType} onChange={setFilterType} />
        <CategoryFilterChips value={filterCategory} onChange={setFilterCategory} />
      </div>

      {/* ── Universal env vars note ── */}
      <div className="mb-4 px-4 py-3 bg-tsurf border border-tborder rounded-xl">
        <div className="text-sm font-semibold text-t2 mb-2.5">Required for all apps</div>
        <div className="flex flex-col gap-2">
          {[
            { key: 'AGENT_SETTING_CONFIG', value: 'settings.rits.toml' },
            { key: 'LLM_MODEL', value: 'gpt-oss-120b' },
            { key: 'LLM_PROVIDER', value: 'rits' },
          ].map(({ key, value }) => (
            <div key={key} className="flex items-center gap-2">
              <span className="font-mono text-sm px-2 py-0.5 rounded bg-amber-500/10 text-amber-600 border border-amber-500/20 whitespace-nowrap">{key}</span>
              <span className="text-t4 text-sm">=</span>
              <span className="font-mono text-sm text-t2">{value}</span>
            </div>
          ))}
          <div className="flex items-start gap-2">
            <span className="font-mono text-sm px-2 py-0.5 rounded bg-amber-500/10 text-amber-600 border border-amber-500/20 whitespace-nowrap">RITS_API_KEY</span>
            <span className="text-t4 text-sm">=</span>
            <span className="text-sm text-t3 italic">connect to TunnelAll VPN and get a key from <a href="http://rits.fmaas.res.ibm.com/" target="_blank" rel="noopener noreferrer" className="text-indigo-500 hover:underline not-italic">rits.fmaas.res.ibm.com</a></span>
          </div>
        </div>
      </div>

      {/* ── Use cases table ── */}
      <UseCaseTable useCases={USE_CASES} {...tableProps} />

      <p className="mt-4 text-sm text-t4">
        Click any row to see architecture, run instructions, and how CUGA powers it.
        {' '}<span className="text-amber-500 font-bold">*</span> highlighted demos
      </p>
    </div>
  )
}
