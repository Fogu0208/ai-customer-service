<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { AGENTS, INTENT_LABELS } from '../agents'
import type { MetricsSummary, ToolDefinition } from '../types'

const props = defineProps<{
  lastIntent: string
  lastCompliance: boolean | null
  lastLatency: number
  tools: ToolDefinition[]
  metrics: MetricsSummary | null
  sending: boolean
}>()

const emit = defineEmits<{
  (e: 'refresh'): void
}>()

let timer: number | undefined

onMounted(() => {
  timer = window.setInterval(() => emit('refresh'), 10000)
})

onUnmounted(() => window.clearInterval(timer))

const hasTurn = computed(
  () => Boolean(props.lastIntent) || props.lastCompliance !== null || props.lastLatency > 0,
)

const intentLabel = computed(
  () => INTENT_LABELS[props.lastIntent] ?? props.lastIntent,
)

const agentMetricEntries = computed(() =>
  Object.entries(props.metrics?.agent_metrics ?? {}),
)

const toolLogs = computed(() =>
  (props.metrics?.tool_call_log ?? []).slice(-8).reverse(),
)

function agentLabel(name: string): string {
  return AGENTS.some((agent) => agent.key === name) ? INTENT_LABELS[name] ?? name : name
}

function callCount(metric: { total_calls?: number; calls?: number }): number {
  return metric.total_calls ?? metric.calls ?? 0
}

function avgMs(metric: { avg_duration_ms?: number; avg_latency_ms?: number }): number {
  return Math.round(Number(metric.avg_duration_ms ?? metric.avg_latency_ms ?? 0))
}
</script>

<template>
  <aside class="flex w-72 shrink-0 flex-col border-l border-slate-200 bg-slate-50">
    <header class="flex h-14 shrink-0 items-center justify-between border-b border-slate-200 px-4">
      <h2 class="text-sm font-semibold text-slate-900">运行情况</h2>
      <button
        type="button"
        class="text-xs text-slate-400 transition hover:text-slate-700"
        @click="emit('refresh')"
      >
        刷新
      </button>
    </header>

    <div class="min-h-0 flex-1 overflow-y-auto px-4 py-4">
      <section>
        <h3 class="text-xs font-medium text-slate-400">本轮</h3>
        <p v-if="sending" class="mt-2 text-sm leading-relaxed text-slate-600">
          正在调度。完成后更新意图、合规和耗时。
        </p>
        <p v-else-if="!hasTurn" class="mt-2 text-sm leading-relaxed text-slate-400">
          发出消息后，这里显示本轮的路由结果。
        </p>
        <dl v-else class="mt-2 space-y-2.5 text-sm">
          <div class="flex items-center justify-between gap-3">
            <dt class="text-slate-500">意图</dt>
            <dd class="text-slate-800">{{ intentLabel || '—' }}</dd>
          </div>
          <div class="flex items-center justify-between gap-3">
            <dt class="text-slate-500">合规</dt>
            <dd
              v-if="lastCompliance !== null"
              class="font-medium"
              :class="lastCompliance ? 'text-emerald-700' : 'text-rose-700'"
            >
              {{ lastCompliance ? '通过' : '拦截' }}
            </dd>
            <dd v-else class="text-slate-300">—</dd>
          </div>
          <div class="flex items-center justify-between gap-3">
            <dt class="text-slate-500">耗时</dt>
            <dd v-if="lastLatency" class="tabular-nums text-slate-800">{{ lastLatency }} ms</dd>
            <dd v-else class="text-slate-300">—</dd>
          </div>
        </dl>
      </section>

      <section class="mt-6 border-t border-slate-200 pt-5">
        <div class="flex items-center justify-between">
          <h3 class="text-xs font-medium text-slate-400">工具</h3>
          <span class="text-xs tabular-nums text-slate-400">{{ tools.length }}</span>
        </div>
        <p v-if="tools.length === 0" class="mt-2 text-sm text-slate-400">
          连接后端后会列出可用工具。
        </p>
        <ul v-else class="mt-2 space-y-3">
          <li v-for="tool in tools" :key="tool.name">
            <p class="font-mono text-xs font-medium text-slate-700">{{ tool.name }}</p>
            <p class="mt-0.5 line-clamp-2 text-xs leading-relaxed text-slate-400">
              {{ tool.description }}
            </p>
          </li>
        </ul>
      </section>

      <section class="mt-6 border-t border-slate-200 pt-5">
        <h3 class="text-xs font-medium text-slate-400">调用</h3>
        <p v-if="agentMetricEntries.length === 0" class="mt-2 text-sm text-slate-400">
          还没有调用数据。
        </p>
        <ul v-else class="mt-2 space-y-2">
          <li
            v-for="[name, metric] in agentMetricEntries"
            :key="name"
            class="flex items-baseline justify-between gap-3 text-sm"
          >
            <span class="min-w-0 truncate text-slate-700">{{ agentLabel(name) }}</span>
            <span class="shrink-0 text-xs tabular-nums text-slate-400">
              {{ callCount(metric) }} 次 · {{ avgMs(metric) }} ms
            </span>
          </li>
        </ul>
      </section>

      <section class="mt-6 border-t border-slate-200 pt-5">
        <h3 class="text-xs font-medium text-slate-400">最近工具调用</h3>
        <p v-if="toolLogs.length === 0" class="mt-2 text-sm text-slate-400">
          还没有调用记录。
        </p>
        <ul v-else class="mt-2 space-y-2">
          <li
            v-for="(log, index) in toolLogs"
            :key="`${log.name}-${index}`"
            class="flex items-center gap-2 text-xs"
          >
            <span
              class="h-1.5 w-1.5 shrink-0 rounded-full"
              :class="log.success ? 'bg-emerald-500' : 'bg-rose-500'"
            ></span>
            <span class="min-w-0 flex-1 truncate font-mono text-slate-600">{{ log.name }}</span>
            <span class="shrink-0 tabular-nums text-slate-400">
              {{ Math.round(log.duration_ms) }} ms
            </span>
          </li>
        </ul>
      </section>
    </div>
  </aside>
</template>
