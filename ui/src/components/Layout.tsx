import { NavLink, useLocation } from 'react-router-dom'

const NAV_ITEMS = [
  { to: '/', label: 'Use Cases', icon: '⚡' },
  { to: '/coverage', label: 'Coverage', icon: '📊' },
  { to: '/features', label: 'Features', icon: '🧩' },
  { to: '/vs-openclaw', label: 'vs OpenClaw', icon: '⚖️' },
  { to: '/manus', label: 'Manus Mapping', icon: '🗺️' },
  { to: '/vision', label: 'Vision', icon: '🔭' },
  { to: '/moat', label: 'Positioning', icon: '🎯' },
  { to: '/proposal', label: 'Proposal', icon: '📋' },
  { to: '/deliverables', label: 'Deliverables', icon: '📦' },
  { to: '/ideas', label: 'Ideas', icon: '💡' },
  { to: '/roadmap', label: 'Early Thoughts', icon: '📝' },
  { to: '/architectures', label: 'Architectures', icon: '🏛️' },
  { to: '/building-blocks', label: 'Building Blocks', icon: '🧱' },
  { to: '/examples', label: 'Examples', icon: '▶️' },
]

export default function Layout({ children }: { children: React.ReactNode }) {
  const location = useLocation()

  const pageTitle = (() => {
    if (location.pathname === '/') return 'Use Cases'
    if (location.pathname.startsWith('/use-case')) return 'Use Case Detail'
    if (location.pathname === '/features') return 'Feature Overview'
    if (location.pathname === '/vs-openclaw') return 'CUGA++ vs OpenClaw'
    if (location.pathname === '/manus') return 'Manus Use Case Mapping'
    if (location.pathname === '/coverage') return 'Use Case Coverage'
    if (location.pathname === '/roadmap') return 'Early Thoughts'
    if (location.pathname === '/vision') return 'Strategic Vision'
    if (location.pathname === '/moat') return 'Positioning'
    if (location.pathname === '/proposal') return 'Proposal'
    if (location.pathname === '/deliverables') return 'Deliverables'
    if (location.pathname === '/ideas') return 'Ideas & Open Questions'
    if (location.pathname === '/architectures') return 'App Architectures'
    if (location.pathname === '/building-blocks') return 'Building Blocks'
    if (location.pathname === '/examples') return 'Examples'
    return 'CUGA++'
  })()

  return (
    <div className="flex h-screen overflow-hidden bg-gray-950">
      {/* Sidebar */}
      <aside className="w-60 flex-shrink-0 bg-gray-900 border-r border-gray-800 flex flex-col">
        {/* Logo */}
        <div className="px-5 py-5 border-b border-gray-800">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center text-sm font-bold text-white">
              C
            </div>
            <div>
              <div className="text-white font-semibold text-sm tracking-wide">CUGA++</div>
              <div className="text-gray-500 text-xs">Event-Driven Agent I/O</div>
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
                    ? 'bg-indigo-600/20 text-indigo-300 font-medium'
                    : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800'
                }`
              }
            >
              <span className="text-base">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>

        {/* Footer */}
        <div className="px-4 py-4 border-t border-gray-800">
          <div className="text-xs text-gray-600">
            <div className="font-mono">53/82 use cases</div>
            <div className="mt-0.5">Sprint 3 complete</div>
          </div>
        </div>
      </aside>

      {/* Main */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top bar */}
        <header className="h-12 flex-shrink-0 bg-gray-900/50 border-b border-gray-800 flex items-center px-6">
          <h1 className="text-sm font-medium text-gray-300">{pageTitle}</h1>
        </header>

        {/* Content */}
        <main className="flex-1 overflow-y-auto">
          {children}
        </main>
      </div>
    </div>
  )
}
