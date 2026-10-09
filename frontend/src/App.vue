<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import SessionSidebar from './components/SessionSidebar.vue'
import ChatMessage from './components/ChatMessage.vue'
import ChatInput from './components/ChatInput.vue'
import InspectorPanel from './components/InspectorPanel.vue'
import { useChat } from './composables/useChat'

const EXAMPLES = [
  '理财产品A的年化收益率是多少？',
  '怎么申请退款？',
  '帮我查一下订单 ORD-2024-001',
  '开户需要什么材料？',
]

const {
  state,
  activeSession,
  newSession,
  switchSession,
  send,
  refreshTools,
  refreshMetrics,
  checkHealth,
} = useChat()

const msgListRef = ref<HTMLElement>()
const inspectorOpen = ref(true)

const sessionTitle = computed(() => activeSession.value?.title ?? '新会话')
const messageCount = computed(() => activeSession.value?.messages.length ?? 0)
const showEmpty = computed(() => messageCount.value === 0)

async function scrollToBottom(): Promise<void> {
  await nextTick()
  const el = msgListRef.value
  if (el) el.scrollTop = el.scrollHeight
}

watch(
  () => activeSession.value?.messages.length,
  () => scrollToBottom(),
)

watch(
  () => state.sending,
  (sending) => {
    if (sending) scrollToBottom()
    else refreshMetrics()
  },
)

function onSend(text: string): void {
  send(text).then(() => scrollToBottom())
}

onMounted(() => {
  checkHealth()
  refreshTools()
  refreshMetrics()
  newSession()
})
</script>

<template>
  <div class="flex h-full bg-white">
    <SessionSidebar
      :sessions="state.sessions"
      :active-id="state.activeSessionId"
      :online="state.backendOnline"
      @new="newSession"
      @switch="switchSession"
    />

    <main class="flex min-w-0 flex-1 flex-col">
      <header
        class="flex h-14 shrink-0 items-center justify-between gap-4 border-b border-slate-200 px-5"
      >
        <div class="min-w-0">
          <h1 class="truncate text-sm font-semibold text-slate-900">
            {{ sessionTitle }}
          </h1>
          <p class="text-xs text-slate-400">
            {{ showEmpty ? '等待第一条消息' : `${messageCount} 条消息` }}
          </p>
        </div>
        <button
          type="button"
          class="shrink-0 rounded-lg px-2.5 py-1.5 text-xs font-medium transition"
          :class="
            inspectorOpen
              ? 'bg-slate-100 text-slate-700 hover:bg-slate-200'
              : 'text-slate-500 hover:bg-slate-100 hover:text-slate-800'
          "
          @click="inspectorOpen = !inspectorOpen"
        >
          {{ inspectorOpen ? '收起' : '运行情况' }}
        </button>
      </header>

      <div ref="msgListRef" class="min-h-0 flex-1 overflow-y-auto">
        <div
          v-if="showEmpty"
          class="mx-auto flex h-full max-w-lg flex-col justify-center px-6 py-10"
        >
          <p class="text-xs font-medium text-brand-700">调度台</p>
          <h2 class="mt-2 text-xl font-semibold tracking-tight text-slate-900">
            有什么需要处理的？
          </h2>
          <p class="mt-2 text-sm leading-relaxed text-slate-500">
            消息会先识别意图，再进入知识问答或工单，最后做合规检查。
          </p>
          <div class="mt-6 flex flex-col gap-2">
            <button
              v-for="prompt in EXAMPLES"
              :key="prompt"
              type="button"
              class="rounded-xl border border-slate-200 bg-white px-4 py-3 text-left text-sm text-slate-700 transition hover:border-brand-300 hover:bg-brand-50 disabled:cursor-not-allowed disabled:opacity-40"
              :disabled="state.sending"
              @click="onSend(prompt)"
            >
              {{ prompt }}
            </button>
          </div>
        </div>

        <div v-else class="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-6">
          <ChatMessage
            v-for="message in activeSession?.messages ?? []"
            :key="message.id"
            :message="message"
          />

          <div
            v-if="state.sending"
            class="msg-in flex items-center gap-2.5 text-sm text-slate-500"
          >
            <span class="flex items-center gap-1">
              <span class="typing-dot h-1.5 w-1.5 rounded-full bg-brand-500"></span>
              <span class="typing-dot h-1.5 w-1.5 rounded-full bg-brand-500"></span>
              <span class="typing-dot h-1.5 w-1.5 rounded-full bg-brand-500"></span>
            </span>
            正在调度
          </div>
        </div>
      </div>

      <ChatInput :sending="state.sending" @send="onSend" />
    </main>

    <InspectorPanel
      v-show="inspectorOpen"
      :last-intent="state.lastIntent"
      :last-compliance="state.lastCompliance"
      :last-latency="state.lastLatency"
      :tools="state.tools"
      :metrics="state.metrics"
      :sending="state.sending"
      @refresh="refreshMetrics"
    />
  </div>
</template>
