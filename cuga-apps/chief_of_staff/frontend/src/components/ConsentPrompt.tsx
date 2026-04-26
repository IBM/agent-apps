import { useState } from 'react';
import { approveTool, denyTool, Proposal } from '../api/client';

interface Props {
  proposals: Proposal[];
  gap: { capability?: string; expected_output?: string } | null;
  onResolved: (result: 'approved' | 'denied' | 'dismissed', proposalId?: string) => void;
}

export default function ConsentPrompt({ proposals, gap, onResolved }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (proposals.length === 0) return null;

  async function approve(p: Proposal) {
    setBusy(p.id);
    setError(null);
    try {
      await approveTool(p.id);
      onResolved('approved', p.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function deny(p: Proposal) {
    setBusy(p.id);
    setError(null);
    try {
      await denyTool(p.id);
      onResolved('denied', p.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="border border-amber-300 bg-amber-50 rounded-lg p-3 text-sm">
      <div className="font-semibold text-amber-900 mb-1">
        I'm missing a tool for this.
      </div>
      {gap?.capability && (
        <div className="text-amber-800 mb-2">
          Needed: <span className="font-mono">{gap.capability}</span>
          {gap.expected_output && <> — {gap.expected_output}</>}
        </div>
      )}
      <div className="text-amber-800 mb-2">Want me to install one of these?</div>
      <ul className="space-y-2">
        {proposals.map((p) => (
          <li key={p.id} className="bg-white border border-amber-200 rounded p-2">
            <div className="flex items-start justify-between gap-2">
              <div className="flex-1">
                <div className="font-semibold text-sm">{p.name}</div>
                <div className="text-xs text-gray-600 mt-0.5">{p.description}</div>
                <div className="text-xs text-gray-400 mt-1">
                  match score {p.score} · source {p.source}
                  {p.auth.length > 0 && <> · needs: {p.auth.join(', ')}</>}
                </div>
              </div>
              <div className="flex flex-col gap-1">
                <button
                  onClick={() => approve(p)}
                  disabled={busy !== null}
                  className="text-xs bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white rounded px-3 py-1"
                >
                  {busy === p.id ? '...' : 'Install'}
                </button>
                <button
                  onClick={() => deny(p)}
                  disabled={busy !== null}
                  className="text-xs bg-gray-200 hover:bg-gray-300 disabled:opacity-50 rounded px-3 py-1"
                >
                  Skip
                </button>
              </div>
            </div>
          </li>
        ))}
      </ul>
      {error && <div className="text-xs text-red-700 mt-2">error: {error}</div>}
      <div className="text-xs text-gray-500 mt-2">
        Installing rebuilds the agent with the new tool — takes ~30 seconds.
      </div>
    </div>
  );
}
