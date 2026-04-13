import { useState, useMemo } from 'react'
import {
  OPENCLAW_USE_CASES, OPENCLAW_CATEGORIES,
  MANUS_USE_CASES_COVERAGE,
  type CoverageStatus,
  type UseCaseType,
} from '../data/coverage'

// ── Helpers ───────────────────────────────────────────────────────────────────

const STATUS_ICON: Record<CoverageStatus, string> = {
  yes: '✅',
  partial: '🔧',
  no: '❌',
}

const STATUS_LABEL: Record<CoverageStatus, string> = {
  yes: 'Yes',
  partial: 'Partial',
  no: 'No',
}

const STATUS_COLOR: Record<CoverageStatus, string> = {
  yes: 'text-green-400',
  partial: 'text-yellow-400',
  no: 'text-gray-500',
}

function StatusCell({ s }: { s: CoverageStatus }) {
  return (
    <span className={`text-sm font-medium ${STATUS_COLOR[s]}`}>
      {STATUS_ICON[s]} {STATUS_LABEL[s]}
    </span>
  )
}

function ScoreBadge({ yes, partial, no, total }: { yes: number; partial: number; no: number; total: number }) {
  const pct = Math.round(((yes + partial * 0.5) / total) * 100)
  return (
    <div className="flex items-center gap-4 text-sm">
      <span className="text-green-400 font-mono">{yes} yes</span>
      <span className="text-yellow-400 font-mono">{partial} partial</span>
      <span className="text-gray-500 font-mono">{no} gap</span>
      <div className="flex items-center gap-1.5">
        <div className="w-28 h-1.5 bg-gray-800 rounded-full overflow-hidden">
          <div className="h-full bg-green-600 rounded-full" style={{ width: `${pct}%` }} />
        </div>
        <span className="text-gray-400 text-xs font-mono">{pct}% coverage</span>
      </div>
    </div>
  )
}

// ── Explanation banner ────────────────────────────────────────────────────────

// ── Type badge ────────────────────────────────────────────────────────────────

const TYPE_CONFIG: Record<UseCaseType, { label: string; icon: string; activeCls: string; inactiveCls: string }> = {
  'event-driven':  { label: 'Event-driven',  icon: '⚡', activeCls: 'bg-amber-900/60 text-amber-200 border-amber-500',   inactiveCls: 'bg-amber-900/20 text-amber-500 border-amber-800/50 hover:border-amber-600 hover:text-amber-300' },
  'multimodal':    { label: 'Multimodal',    icon: '🎨', activeCls: 'bg-purple-900/60 text-purple-200 border-purple-500', inactiveCls: 'bg-purple-900/20 text-purple-500 border-purple-800/50 hover:border-purple-600 hover:text-purple-300' },
  'both':          { label: 'Both',          icon: '✨', activeCls: 'bg-teal-900/60 text-teal-200 border-teal-500',       inactiveCls: 'bg-teal-900/20 text-teal-500 border-teal-800/50 hover:border-teal-600 hover:text-teal-300' },
  'conversational':{ label: 'Conversational',icon: '💬', activeCls: 'bg-blue-900/60 text-blue-200 border-blue-500',      inactiveCls: 'bg-blue-900/20 text-blue-500 border-blue-800/50 hover:border-blue-600 hover:text-blue-300' },
}

const ALL_TYPES = Object.keys(TYPE_CONFIG) as UseCaseType[]

function TypeBadge({ type }: { type: UseCaseType }) {
  const { label, icon, activeCls } = TYPE_CONFIG[type]
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded font-medium border ${activeCls}`}>
      {icon} {label}
    </span>
  )
}

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

function Legend() {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 mb-6 flex flex-col sm:flex-row gap-4 text-sm">
      <div className="flex-1">
        <div className="font-semibold text-white mb-1">cuga <span className="text-gray-500 font-normal text-xs">(agent only)</span></div>
        <div className="text-gray-400 text-xs leading-relaxed">
          The reasoning layer — <code className="text-gray-300 bg-gray-800 px-1 rounded">CugaAgent</code> with tools.
          Works conversationally, on-demand. You invoke it; it responds. No automation, no channels, no scheduled triggers.
        </div>
      </div>
      <div className="w-px bg-gray-800 hidden sm:block" />
      <div className="flex-1">
        <div className="font-semibold text-indigo-300 mb-1">cuga++ <span className="text-gray-500 font-normal text-xs">(full pipeline)</span></div>
        <div className="text-gray-400 text-xs leading-relaxed">
          The I/O runtime — channels, triggers, output routing, production daemon.
          Fully automated. Fires on schedule, on event, on threshold. Runs while you sleep.
        </div>
      </div>
      <div className="w-px bg-gray-800 hidden sm:block" />
      <div className="flex-1 text-xs text-gray-500 space-y-1 self-center">
        <div>{STATUS_ICON.yes} <span className="text-gray-400">Working today</span></div>
        <div>{STATUS_ICON.partial} <span className="text-gray-400">Partial / needs one more piece</span></div>
        <div>{STATUS_ICON.no} <span className="text-gray-400">Gap / architectural limit</span></div>
      </div>
    </div>
  )
}

// ── OpenClaw table ────────────────────────────────────────────────────────────

function OpenClawTable() {
  const [search, setSearch] = useState('')
  const [filterCategory, setFilterCategory] = useState<string>('all')
  const [filterStatus, setFilterStatus] = useState<CoverageStatus | 'all'>('all')
  const [filterType, setFilterType] = useState<UseCaseType | 'all'>('all')

  const filtered = useMemo(() => {
    return OPENCLAW_USE_CASES.filter((uc) => {
      const q = search.toLowerCase()
      const matchSearch = !q || uc.name.toLowerCase().includes(q) || uc.note.toLowerCase().includes(q)
      const matchCat = filterCategory === 'all' || uc.category === filterCategory
      const matchStatus = filterStatus === 'all' || uc.cugaPlusPlus === filterStatus
      const matchType = filterType === 'all' || uc.type === filterType
      return matchSearch && matchCat && matchStatus && matchType
    })
  }, [search, filterCategory, filterStatus, filterType])

  const yes = OPENCLAW_USE_CASES.filter(u => u.cugaPlusPlus === 'yes').length
  const partial = OPENCLAW_USE_CASES.filter(u => u.cugaPlusPlus === 'partial').length
  const no = OPENCLAW_USE_CASES.filter(u => u.cugaPlusPlus === 'no').length

  return (
    <div>
      <div className="flex items-center justify-between mb-3 flex-wrap gap-3">
        <div>
          <h3 className="text-base font-semibold text-white">OpenClaw — 82 Use Cases</h3>
          <p className="text-xs text-gray-500 mt-0.5">
            OpenClaw's 82 documented use cases mapped against what cuga (agent only) and cuga++ (full pipeline) can do today.
          </p>
        </div>
        <ScoreBadge yes={yes} partial={partial} no={no} total={82} />
      </div>

      {/* Filters */}
      <div className="flex flex-col gap-2 mb-4">
        <div className="flex flex-wrap gap-2">
          <input
            type="text"
            placeholder="Search use cases..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="px-3 py-1.5 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-indigo-500 w-52"
          />
          <select
            value={filterCategory}
            onChange={e => setFilterCategory(e.target.value)}
            className="px-3 py-1.5 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-300 focus:outline-none focus:border-indigo-500"
          >
            <option value="all">All categories</option>
            {OPENCLAW_CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
          <select
            value={filterStatus}
            onChange={e => setFilterStatus(e.target.value as CoverageStatus | 'all')}
            className="px-3 py-1.5 bg-gray-900 border border-gray-700 rounded-lg text-sm text-gray-300 focus:outline-none focus:border-indigo-500"
          >
            <option value="all">All cuga++ statuses</option>
            <option value="yes">✅ Working</option>
            <option value="partial">🔧 Partial</option>
            <option value="no">❌ Gap</option>
          </select>
          {(search || filterCategory !== 'all' || filterStatus !== 'all' || filterType !== 'all') && (
            <button
              onClick={() => { setSearch(''); setFilterCategory('all'); setFilterStatus('all'); setFilterType('all') }}
              className="px-3 py-1.5 text-xs text-gray-500 hover:text-gray-300"
            >
              Clear all
            </button>
          )}
        </div>
        <TypeFilterChips value={filterType} onChange={setFilterType} />
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-gray-800 bg-gray-900/80">
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-2.5 w-8">#</th>
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-3 py-2.5">Use Case</th>
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-3 py-2.5 hidden lg:table-cell">Category</th>
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-3 py-2.5 hidden md:table-cell">Type</th>
              <th className="text-center text-xs font-semibold text-gray-500 uppercase tracking-wider px-3 py-2.5 w-24">cuga</th>
              <th className="text-center text-xs font-semibold text-indigo-600 uppercase tracking-wider px-3 py-2.5 w-24">cuga++</th>
              <th className="text-left text-xs font-semibold text-gray-600 uppercase tracking-wider px-3 py-2.5 hidden xl:table-cell">Note</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800/40">
            {filtered.map(uc => (
              <tr key={uc.id} className="hover:bg-gray-800/30">
                <td className="px-4 py-2.5 text-xs font-mono text-gray-600">{uc.id}</td>
                <td className="px-3 py-2.5 text-sm text-gray-300">{uc.name}</td>
                <td className="px-3 py-2.5 hidden lg:table-cell">
                  <span className="text-xs text-gray-600">{uc.category}</span>
                </td>
                <td className="px-3 py-2.5 hidden md:table-cell">
                  <TypeBadge type={uc.type} />
                </td>
                <td className="px-3 py-2.5 text-center">
                  <StatusCell s={uc.cuga} />
                </td>
                <td className="px-3 py-2.5 text-center">
                  <StatusCell s={uc.cugaPlusPlus} />
                </td>
                <td className="px-3 py-2.5 text-xs text-gray-600 hidden xl:table-cell max-w-xs">
                  {uc.note}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length === 0 && (
          <div className="py-10 text-center text-gray-600 text-sm">No matching use cases.</div>
        )}
      </div>

      {/* Category breakdown */}
      <div className="mt-4 grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-2">
        {OPENCLAW_CATEGORIES.map(cat => {
          const inCat = OPENCLAW_USE_CASES.filter(u => u.category === cat)
          const y = inCat.filter(u => u.cugaPlusPlus === 'yes').length
          const p = inCat.filter(u => u.cugaPlusPlus === 'partial').length
          return (
            <button
              key={cat}
              onClick={() => setFilterCategory(filterCategory === cat ? 'all' : cat)}
              className={`text-left p-2.5 rounded-lg border text-xs transition-colors ${
                filterCategory === cat
                  ? 'border-indigo-600 bg-indigo-900/20'
                  : 'border-gray-800 bg-gray-900 hover:border-gray-700'
              }`}
            >
              <div className="text-gray-300 font-medium mb-1 leading-tight">{cat}</div>
              <div className="font-mono text-gray-500">
                <span className="text-green-600">{y}✅</span>{' '}
                <span className="text-yellow-700">{p}🔧</span>{' '}
                <span className="text-gray-700">{inCat.length - y - p}❌</span>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ── Manus table ───────────────────────────────────────────────────────────────

function ManusTable() {
  const yes = MANUS_USE_CASES_COVERAGE.filter(u => u.cugaPlusPlus === 'yes').length
  const partial = MANUS_USE_CASES_COVERAGE.filter(u => u.cugaPlusPlus === 'partial').length
  const no = MANUS_USE_CASES_COVERAGE.filter(u => u.cugaPlusPlus === 'no').length

  return (
    <div>
      <div className="flex items-center justify-between mb-3 flex-wrap gap-3">
        <div>
          <h3 className="text-base font-semibold text-white">Manus AI — 20 Use Cases</h3>
          <p className="text-xs text-gray-500 mt-0.5">
            Manus's publicly demonstrated use cases. Where Manus runs a task once, cuga++ runs it on a schedule for a team.
          </p>
        </div>
        <ScoreBadge yes={yes} partial={partial} no={no} total={20} />
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-gray-800 bg-gray-900/80">
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-2.5 w-8">#</th>
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-3 py-2.5">Use Case</th>
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-3 py-2.5 hidden md:table-cell">Type</th>
              <th className="text-center text-xs font-semibold text-gray-500 uppercase tracking-wider px-3 py-2.5 w-24">cuga</th>
              <th className="text-center text-xs font-semibold text-indigo-600 uppercase tracking-wider px-3 py-2.5 w-24">cuga++</th>
              <th className="text-left text-xs font-semibold text-gray-600 uppercase tracking-wider px-3 py-2.5 hidden lg:table-cell">Note</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800/40">
            {MANUS_USE_CASES_COVERAGE.map(uc => (
              <tr key={uc.id} className="hover:bg-gray-800/30">
                <td className="px-4 py-2.5 text-xs font-mono text-gray-600">{uc.id}</td>
                <td className="px-3 py-2.5 text-sm text-gray-300">{uc.name}</td>
                <td className="px-3 py-2.5 hidden md:table-cell"><TypeBadge type={uc.type} /></td>
                <td className="px-3 py-2.5 text-center"><StatusCell s={uc.cuga} /></td>
                <td className="px-3 py-2.5 text-center"><StatusCell s={uc.cugaPlusPlus} /></td>
                <td className="px-3 py-2.5 text-xs text-gray-600 hidden lg:table-cell">{uc.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Gaps callout */}
      <div className="mt-4 grid grid-cols-3 gap-3">
        {[
          { title: 'HTML / web app generation', desc: 'Use cases #2, #9, #10. Agent writes HTML but no deployment channel.', route: 'WebAppOutputChannel' },
          { title: 'Data visualisation / charts', desc: 'Use case #12. Agent writes analysis but no chart generation tool.', route: 'make_chart_tool()' },
          { title: 'Browser automation', desc: 'Manus uses browser for form-filling, screenshots. CUGA++ has no CDP layer yet.', route: 'PlaywrightChannel' },
        ].map(item => (
          <div key={item.title} className="bg-gray-900 border border-gray-800 rounded-lg p-3.5">
            <div className="text-xs font-semibold text-gray-400 mb-1">{item.title}</div>
            <div className="text-xs text-gray-600 mb-2">{item.desc}</div>
            <div className="text-xs font-mono text-yellow-700">→ {item.route}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

type Tab = 'openclaw' | 'manus'

export default function CoveragePage() {
  const [tab, setTab] = useState<Tab>('openclaw')

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="mb-6">
        <h2 className="text-2xl font-semibold text-white mb-1">Use Case Coverage</h2>
        <p className="text-gray-400 text-sm">
          What's possible with <strong className="text-white">cuga</strong> (the agent, on-demand) vs <strong className="text-indigo-300">cuga++</strong> (the full automated pipeline), across OpenClaw's 82 use cases and Manus's 20.
        </p>
      </div>

      <Legend />

      {/* Tabs */}
      <div className="flex gap-1 mb-6 bg-gray-900 border border-gray-800 rounded-lg p-1 w-fit">
        <button
          onClick={() => setTab('openclaw')}
          className={`px-4 py-1.5 rounded text-sm font-medium transition-colors ${
            tab === 'openclaw'
              ? 'bg-indigo-600 text-white'
              : 'text-gray-400 hover:text-gray-200'
          }`}
        >
          OpenClaw (82)
        </button>
        <button
          onClick={() => setTab('manus')}
          className={`px-4 py-1.5 rounded text-sm font-medium transition-colors ${
            tab === 'manus'
              ? 'bg-indigo-600 text-white'
              : 'text-gray-400 hover:text-gray-200'
          }`}
        >
          Manus (20)
        </button>
      </div>

      {tab === 'openclaw' ? <OpenClawTable /> : <ManusTable />}
    </div>
  )
}
