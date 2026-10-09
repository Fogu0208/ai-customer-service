import type {
  ChatRequest,
  ChatResponse,
  HistoryMessage,
  MetricsSummary,
  ToolDefinition,
} from '../types'

const BASE = '' // vite proxy -> http://localhost:8000

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status}: ${detail || res.statusText}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  chat(body: ChatRequest): Promise<ChatResponse> {
    return request<ChatResponse>('/api/chat', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  },

  async listTools(): Promise<ToolDefinition[]> {
    const data = await request<{ tools: ToolDefinition[] }>('/api/tools')
    return data.tools
  },

  metrics(): Promise<MetricsSummary> {
    return request<MetricsSummary>('/api/metrics')
  },

  async history(sessionId: string): Promise<HistoryMessage[]> {
    const data = await request<{ messages: HistoryMessage[] }>(
      `/api/history/${encodeURIComponent(sessionId)}`,
    )
    return data.messages
  },

  async health(): Promise<boolean> {
    try {
      const data = await request<{ status: string }>('/health')
      return data.status === 'healthy'
    } catch {
      return false
    }
  },
}
