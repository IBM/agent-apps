import { FormEvent, useState } from 'react';
import { ChatResponse, Proposal, sendChat } from '../api/client';
import ConsentPrompt from './ConsentPrompt';

type Turn = {
  role: 'user' | 'agent';
  text: string;
  proposals?: Proposal[];
  gap?: ChatResponse['gap'];
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
          proposals: r.proposals,
          gap: r.gap,
        },
      ]);
    } catch (err) {
      setTurns((t) => [...t, { role: 'agent', text: `error: ${(err as Error).message}` }]);
    } finally {
      setPending(false);
    }
  }

  function resolveProposal(turnIndex: number) {
    return (result: 'approved' | 'denied' | 'failed', proposalId?: string) => {
      setTurns((t) =>
        t.map((turn, i) => {
          if (i !== turnIndex) return turn;
          // Only remove the card on success or denial; on failure leave it
          // so the user sees the error and can retry / pick another.
          if (result === 'failed') return turn;
          const remaining = (turn.proposals ?? []).filter((p) => p.id !== proposalId);
          return { ...turn, proposals: remaining };
        }),
      );
      if (result === 'approved') {
        onToolsChanged?.();
      }
    };
  }

  return (
    <div className="flex flex-col h-full max-w-3xl mx-auto p-4">
      <div className="flex-1 overflow-y-auto space-y-3 pb-4">
        {turns.length === 0 && (
          <div className="text-gray-400 text-sm">
            Ask anything. If I'm missing a tool, I'll offer to install one.
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
            {t.role === 'agent' && t.proposals && t.proposals.length > 0 && (
              <ConsentPrompt
                proposals={t.proposals}
                gap={t.gap ?? null}
                onResolved={resolveProposal(i)}
              />
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
