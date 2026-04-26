export interface Proposal {
  id: string;
  name: string;
  description: string;
  capabilities: string[];
  kind: string;
  auth: string[];
  score: number;
  source: string;
}

export interface ChatResponse {
  response: string;
  thread_id: string;
  error: string | null;
  gap: { capability?: string; expected_output?: string; inputs?: string[] } | null;
  proposals: Proposal[];
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

export interface CatalogEntry {
  id: string;
  name: string;
  description: string;
  capabilities: string[];
  kind: string;
  auth: string[];
  active: boolean;
}

export interface ApproveResult {
  reload: { status: string; servers_loaded: string[]; tool_count: number };
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

export async function listCatalog(): Promise<CatalogEntry[]> {
  const r = await fetch(`${BASE}/catalog`);
  if (!r.ok) throw new Error(`catalog failed: ${r.status}`);
  return r.json();
}

export async function approveTool(catalogId: string): Promise<ApproveResult> {
  const r = await fetch(`${BASE}/tools/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ catalog_id: catalogId }),
  });
  if (!r.ok) {
    const detail = await r.text().catch(() => '');
    throw new Error(`approve failed: ${r.status} ${detail}`);
  }
  return r.json();
}

export async function denyTool(catalogId: string): Promise<{ status: string }> {
  const r = await fetch(`${BASE}/tools/deny`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ catalog_id: catalogId }),
  });
  if (!r.ok) throw new Error(`deny failed: ${r.status}`);
  return r.json();
}
