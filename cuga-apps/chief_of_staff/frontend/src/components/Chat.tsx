import { FormEvent, useState } from 'react';
import { sendChat } from '../api/client';

type Turn = { role: 'user' | 'agent'; text: string };

export default function Chat() {
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
      setTurns((t) => [...t, { role: 'agent', text: r.error ? `error: ${r.error}` : r.response }]);
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
            Phase 0 skeleton. Type a message — it round-trips through the
            orchestrator and the cuga stub. Real planning lands in phase 1.
          </div>
        )}
        {turns.map((t, i) => (
          <div
            key={i}
            className={
              t.role === 'user'
                ? 'text-right'
                : 'text-left'
            }
          >
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
