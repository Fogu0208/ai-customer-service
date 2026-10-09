/** 与 FastAPI 后端对齐的类型定义 */

export interface ChatRequest {
  message: string
  user_id?: string
  session_id?: string | null
}

export interface ChatResponse {
  response: string
  session_id: string
  intent: string
  compliance_passed: boolean
}

export interface ToolDefinition {
  name: string
  description: string
  category?: string
  parameters?: Record<string, unknown>
}

export interface ToolCallLogEntry {
  name: string
  arguments: Record<string, unknown>
  success: boolean
  duration_ms: number
  error?: string | null
  timestamp?: string
}

export interface MetricsSummary {
  agent_metrics: Record<string, {
    total_calls?: number
    calls?: number
    avg_duration_ms?: number
    avg_latency_ms?: number
    error_rate?: number
    [key: string]: unknown
  }>
  tool_call_log: ToolCallLogEntry[]
}

export interface HistoryMessage {
  role: 'user' | 'assistant' | string
  content: string
}

/** 前端本地消息模型 */
export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  time: string
  intent?: string
  compliancePassed?: boolean
  latencyMs?: number
}

export interface Session {
  id: string
  title: string
  createdAt: string
  messages: ChatMessage[]
}
