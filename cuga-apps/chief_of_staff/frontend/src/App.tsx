import { useEffect, useState, useCallback } from 'react';
import Chat from './components/Chat';
import ToolsPanel from './components/ToolsPanel';
import { health, HealthResponse } from './api/client';

export default function App() {
  const [status, setStatus] = useState<'unknown' | 'backend-up' | 'backend-down'>('unknown');
  const [info, setInfo] = useState<HealthResponse | null>(null);
  const [toolsRev, setToolsRev] = useState(0);

  const refreshHealth = useCallback(() => {
    health()
      .then((h) => {
        setStatus('backend-up');
        setInfo(h);
      })
      .catch(() => setStatus('backend-down'));
  }, []);

  useEffect(() => {
    refreshHealth();
  }, [refreshHealth]);

  // Bump on tool changes so ToolsPanel + header re-fetch.
  const onToolsChanged = useCallback(() => {
    setToolsRev((n) => n + 1);
    refreshHealth();
  }, [refreshHealth]);

  return (
    <div className="h-full flex flex-col bg-white">
      <header className="border-b px-4 py-3 flex items-center justify-between">
        <h1 className="text-lg font-semibold">Chief of Staff</h1>
        <div className="text-xs text-gray-500">
          backend: {status} · agent: {info?.agent_reachable ? 'reachable' : 'stub'} ·
          tools: {info?.tools_registered ?? 0}
        </div>
      </header>
      <main className="flex-1 flex overflow-hidden">
        <div className="flex-1 overflow-hidden">
          <Chat onToolsChanged={onToolsChanged} />
        </div>
        <ToolsPanel rev={toolsRev} />
      </main>
    </div>
  );
}
