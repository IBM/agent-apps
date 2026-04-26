export interface ChatResponse {
  response: string;
  thread_id: string;
  error: string | null;
}

export interface ToolRecord {
  id: string;
  name: string;
  source: string;
  description: string;
  health: string;
}

export interface HealthResponse {
  status: string;
  agent_reachable: boolean;
  tools_registered: number;
}

const BASE = '/api';

export async function sendChat(message: string, threadId = 'default'): Promise<ChatResponse> {
  const r = await fetch(`${BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, thread_id: threadId }),
  });
  if (!r.ok) throw new Error(`chat failed: ${r.status}`);
  return r.json();
}

export async function health(): Promise<HealthResponse> {
  const r = await fetch(`${BASE}/health`);
  if (!r.ok) throw new Error(`health failed: ${r.status}`);
  return r.json();
}

export async function listTools(): Promise<ToolRecord[]> {
  const r = await fetch(`${BASE}/tools`);
  if (!r.ok) throw new Error(`tools failed: ${r.status}`);
  return r.json();
}

export async function refreshTools(): Promise<{ synced: number }> {
  const r = await fetch(`${BASE}/tools/refresh`, { method: 'POST' });
  if (!r.ok) throw new Error(`refresh failed: ${r.status}`);
  return r.json();
}
