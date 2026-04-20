import { NavLink, useLocation } from 'react-router-dom'
import { useTheme } from '../hooks/useTheme'

const NAV_ITEMS = [
  { to: '/', label: 'Apps', icon: '⚡' },
  { to: '/coverage', label: 'OpenClaw / Manus', icon: '📊' },
  { to: '/use-case-ideas', label: 'Use Case Ideas', icon: '🗂️' },
]

export default function Layout({ children }: { children: React.ReactNode }) {
  const location = useLocation()
  const { theme, toggle } = useTheme()

  const pageTitle = (() => {
    if (location.pathname === '/') return 'Apps'
    if (location.pathname.startsWith('/use-case') && !location.pathname.includes('ideas')) return 'Use Case Detail'
    if (location.pathname === '/coverage') return 'OpenClaw / Manus'
    if (location.pathname === '/use-case-ideas') return 'Use Case Ideas'
    if (location.pathname === '/features') return 'Feature Overview'
    if (location.pathname === '/vs-openclaw') return 'CUGA vs OpenClaw'
    if (location.pathname === '/manus') return 'Manus Use Case Mapping'
    if (location.pathname === '/roadmap') return 'Early Thoughts'
    if (location.pathname === '/vision') return 'Strategic Vision'
    if (location.pathname === '/moat') return 'Positioning'
    if (location.pathname === '/proposal') return 'Proposal'
    if (location.pathname === '/deliverables') return 'Deliverables'
    if (location.pathname === '/ideas') return 'Ideas & Open Questions'
    if (location.pathname === '/architectures') return 'App Architectures'
    if (location.pathname === '/building-blocks') return 'Building Blocks'
    if (location.pathname === '/examples') return 'Examples'
    return 'CUGA'
  })()

  return (
    <div className="flex h-screen overflow-hidden bg-tbg">
      {/* Sidebar */}
      <aside className="w-60 flex-shrink-0 bg-tsurf border-r-2 border-tborder flex flex-col shadow-sm">
        {/* Logo */}
        <div className="px-5 py-5 border-b-2 border-tborder">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center text-sm font-bold text-white shadow-sm">
              C
            </div>
            <div>
              <div className="text-t1 font-semibold text-sm tracking-wide">CUGA Apps</div>
              <div className="text-t3 text-xs">Dashboard</div>
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                  isActive
                    ? 'bg-indigo-600/10 text-indigo-500 font-medium border border-indigo-500/30'
                    : 'text-t3 hover:text-t1 hover:bg-tsurf2'
                }`
              }
            >
              <span className="text-base">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>

        {/* Theme toggle */}
        <div className="px-4 py-3 border-t-2 border-tborder">
          <button
            onClick={toggle}
            className="w-full flex items-center justify-between px-3 py-2 rounded-lg bg-tsurf2 border border-tborder text-xs text-t2 hover:text-t1 hover:border-t3 transition-colors"
          >
            <span>{theme === 'warm' ? '☀️ Warm' : '🌙 Dark'}</span>
            <span className="text-t4">switch</span>
          </button>
        </div>

        {/* Footer */}
        <div className="px-4 py-3 border-t-2 border-tborder">
          <div className="text-xs text-t4 font-mono">53/82 use cases</div>
          <div className="text-xs text-t4 mt-0.5">Sprint 3 complete</div>
        </div>
      </aside>

      {/* Main */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top bar */}
        <header className="h-12 flex-shrink-0 bg-tsurf border-b-2 border-tborder flex items-center px-6 shadow-sm">
          <h1 className="text-sm font-medium text-t2">{pageTitle}</h1>
        </header>

        {/* Content */}
        <main className="flex-1 overflow-y-auto">
          {children}
        </main>
      </div>
    </div>
  )
}
