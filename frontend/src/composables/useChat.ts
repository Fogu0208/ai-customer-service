import { computed, reactive, ref } from 'vue'
import { api } from '../api/client'
import type { ChatMessage, MetricsSummary, Session, ToolDefinition } from '../types'

function now(): string {
  return new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function uid(): string {
  return Math.random().toString(36).slice(2, 10)
}

const USER_ID = 'web_user_001'

const state = reactive({
  sessions: [] as Session[],
  activeSessionId: '' as string,
  sending: false,
  backendOnline: null as boolean | null,
  tools: [] as ToolDefinition[],
  metrics: null as MetricsSummary | null,
  lastIntent: '' as string,
  lastCompliance: null as boolean | null,
  lastLatency: 0,
})

export function useChat() {
  const activeSession = computed<Session | undefined>(() =>
    state.sessions.find((s) => s.id === state.activeSessionId),
  )

  function newSession(): void {
    const session: Session = {
      id: crypto.randomUUID(),
      title: '新会话',
      createdAt: now(),
      messages: [],
    }
    state.sessions.unshift(session)
    state.activeSessionId = session.id
    state.lastIntent = ''
    state.lastCompliance = null
  }

  function switchSession(id: string): void {
    state.activeSessionId = id
  }

  async function send(text: string): Promise<void> {
    const msg = text.trim()
    if (!msg || state.sending) return
    if (!activeSession.value) newSession()
    const session = activeSession.value!

    const userMsg: ChatMessage = { id: uid(), role: 'user', content: msg, time: now() }
    session.messages.push(userMsg)
    if (session.title === '新会话') {
      session.title = msg.length > 18 ? msg.slice(0, 18) + '…' : msg
    }

    state.sending = true
    const started = performance.now()
    try {
      const res = await api.chat({
        message: msg,
        user_id: USER_ID,
        session_id: session.id,
      })
      const latency = Math.round(performance.now() - started)
      state.lastIntent = res.intent
      state.lastCompliance = res.compliance_passed
      state.lastLatency = latency
      state.backendOnline = true
      session.messages.push({
        id: uid(),
        role: 'assistant',
        content: res.response,
        time: now(),
        intent: res.intent,
        compliancePassed: res.compliance_passed,
        latencyMs: latency,
      })
    } catch (e) {
      if (e instanceof TypeError) state.backendOnline = false
      session.messages.push({
        id: uid(),
        role: 'assistant',
        content: `请求失败：${e instanceof Error ? e.message : String(e)}\n\n请确认后端已在 8000 端口启动。`,
        time: now(),
      })
    } finally {
      state.sending = false
    }
  }

  async function refreshTools(): Promise<void> {
    try {
      state.tools = await api.listTools()
    } catch {
      state.tools = []
    }
  }

  async function refreshMetrics(): Promise<void> {
    try {
      state.metrics = await api.metrics()
    } catch {
      state.metrics = null
    }
  }

  async function checkHealth(): Promise<void> {
    state.backendOnline = await api.health()
  }

  const loading = ref(false)

  return {
    state,
    activeSession,
    loading,
    newSession,
    switchSession,
    send,
    refreshTools,
    refreshMetrics,
    checkHealth,
  }
}
