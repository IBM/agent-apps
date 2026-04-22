import { useTheme } from '../hooks/useTheme'

export default function Layout({ children }: { children: React.ReactNode }) {
  const { theme, toggle } = useTheme()

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-tbg">
      {/* Top bar */}
      <header className="h-12 flex-shrink-0 bg-tsurf border-b-2 border-tborder flex items-center px-6 shadow-sm gap-3">
        <div className="w-7 h-7 rounded-lg bg-indigo-600 flex items-center justify-center text-sm font-bold text-white shadow-sm">
          C
        </div>
        <span className="text-t1 font-semibold text-sm tracking-wide">CUGA Apps</span>
        <div className="flex-1" />
        <button
          onClick={toggle}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-tsurf2 border border-tborder text-xs text-t2 hover:text-t1 hover:border-t3 transition-colors"
        >
          <span>{theme === 'warm' ? '☀️ Warm' : '🌙 Dark'}</span>
        </button>
      </header>

      {/* Content */}
      <main className="flex-1 overflow-y-auto">
        {children}
      </main>
    </div>
  )
}
