export interface Proposal {
  id: string;
  name: string;
  description: string;
  capabilities: string[];
  source: string;          // "catalog" | "openapi" | (future) "browser"
  score: number;
  auth: string[];
  spec: Record<string, unknown>;
  probe_result?: Record<string, unknown> | null;
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
  toolsmith_llm: boolean;
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
  success: boolean;
  reason: string;
  reload?: { status: string; servers_loaded?: string[]; tool_count: number; extra_tool_count?: number };
  probe?: Record<string, unknown> | null;
  realized?: Record<string, unknown> | null;
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

export async function approveTool(proposal: Proposal): Promise<ApproveResult> {
  const r = await fetch(`${BASE}/tools/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ proposal }),
  });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) {
    const detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body);
    throw new Error(`approve failed: ${r.status} ${detail}`);
  }
  return body as ApproveResult;
}

export async function denyTool(proposalId: string): Promise<{ status: string }> {
  const r = await fetch(`${BASE}/tools/deny`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ proposal_id: proposalId }),
  });
  if (!r.ok) throw new Error(`deny failed: ${r.status}`);
  return r.json();
}
