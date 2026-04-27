import { FormEvent, useState } from 'react';
import { AcquisitionResult, ChatResponse, sendChat } from '../api/client';
import CredentialPrompt from './CredentialPrompt';

type Turn = {
  role: 'user' | 'agent';
  text: string;
  gap?: ChatResponse['gap'];
  acquisition?: AcquisitionResult | null;
};

interface Props {
  onToolsChanged?: () => void;
}

export default function Chat({ onToolsChanged }: Props) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState('');
  const [pending, setPending] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const msg = input.trim();
    if (!msg || pending) return;
    setInput('');
    setTurns((t) => [...t, { role: 'user', text: msg }]);
    setPending(true);
    try {
      const r = await sendChat(msg);
      setTurns((t) => [
        ...t,
        {
          role: 'agent',
          text: r.error ? `error: ${r.error}` : r.response || '(no answer)',
          gap: r.gap,
          acquisition: r.acquisition,
        },
      ]);
      if (r.acquisition?.success) {
        onToolsChanged?.();
      }
    } catch (err) {
      setTurns((t) => [...t, { role: 'agent', text: `error: ${(err as Error).message}` }]);
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex flex-col h-full max-w-3xl mx-auto p-4">
      <div className="flex-1 overflow-y-auto space-y-3 pb-4">
        {turns.length === 0 && (
          <div className="text-gray-400 text-sm">
            Ask anything. If I'm missing a tool, Toolsmith will build one and tell you.
          </div>
        )}
        {turns.map((t, i) => (
          <div key={i} className={t.role === 'user' ? 'text-right' : 'text-left space-y-2'}>
            <div
              className={
                'inline-block rounded-lg px-3 py-2 text-sm whitespace-pre-wrap ' +
                (t.role === 'user'
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-100 text-gray-900')
              }
            >
              {t.text}
            </div>
            {t.role === 'agent' && t.acquisition && (
              <>
                <AcquisitionNotice acquisition={t.acquisition} />
                {t.acquisition.needs_secrets && (
                  <CredentialPrompt
                    needs={t.acquisition.needs_secrets}
                    onSubmitted={() => onToolsChanged?.()}
                  />
                )}
              </>
            )}
          </div>
        ))}
      </div>
      <form onSubmit={onSubmit} className="flex gap-2 border-t pt-3">
        <input
          className="flex-1 border rounded px-3 py-2 text-sm focus:outline-none focus:ring"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask anything..."
          disabled={pending}
        />
        <button
          type="submit"
          disabled={pending || !input.trim()}
          className="bg-blue-600 text-white rounded px-4 py-2 text-sm disabled:opacity-50"
        >
          {pending ? '...' : 'Send'}
        </button>
      </form>
    </div>
  );
}

function AcquisitionNotice({ acquisition }: { acquisition: AcquisitionResult }) {
  const ok = acquisition.success;
  return (
    <div
      className={
        'border rounded-lg p-2 text-xs ' +
        (ok ? 'border-green-300 bg-green-50' : 'border-amber-300 bg-amber-50')
      }
    >
      <div className={'font-semibold ' + (ok ? 'text-green-900' : 'text-amber-900')}>
        {ok ? 'Toolsmith built a tool' : 'Toolsmith couldn\'t build a tool'}
      </div>
      <div className={ok ? 'text-green-800' : 'text-amber-800'}>{acquisition.summary}</div>
      {acquisition.artifact_id && (
        <div className="text-gray-500 mt-0.5 font-mono">{acquisition.artifact_id}</div>
      )}
      {ok && (
        <div className="text-gray-600 mt-1">
          Try asking again — the new tool is now available.
        </div>
      )}
    </div>
  );
}
