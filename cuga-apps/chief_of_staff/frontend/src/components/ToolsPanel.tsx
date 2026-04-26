import { useEffect, useState } from 'react';
import { listTools, refreshTools, ToolRecord } from '../api/client';

export default function ToolsPanel() {
  const [tools, setTools] = useState<ToolRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setTools(await listTools());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function refresh() {
    setLoading(true);
    try {
      await refreshTools();
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const bySource: Record<string, ToolRecord[]> = {};
  for (const t of tools) {
    (bySource[t.source] ??= []).push(t);
  }

  return (
    <aside className="border-l w-72 flex flex-col bg-gray-50">
      <div className="px-3 py-2 border-b flex items-center justify-between">
        <h2 className="text-sm font-semibold">Tools ({tools.length})</h2>
        <button
          onClick={refresh}
          disabled={loading}
          className="text-xs text-blue-600 hover:underline disabled:opacity-50"
        >
          {loading ? '...' : 'refresh'}
        </button>
      </div>
      {error && <div className="px-3 py-2 text-xs text-red-600">error: {error}</div>}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-3 text-xs">
        {tools.length === 0 && !loading && (
          <div className="text-gray-500">
            No tools registered. Start the cuga adapter and click refresh.
          </div>
        )}
        {Object.entries(bySource).map(([source, items]) => (
          <div key={source}>
            <div className="text-gray-400 uppercase tracking-wide text-[10px] mb-1">
              {source}
            </div>
            <ul className="space-y-1">
              {items.map((t) => (
                <li key={t.id} className="bg-white border rounded px-2 py-1">
                  <div className="font-mono text-[11px]">{t.name}</div>
                  {t.description && (
                    <div className="text-gray-500 text-[11px] line-clamp-2">{t.description}</div>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </aside>
  );
}
