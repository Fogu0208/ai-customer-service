<script setup lang="ts">
import { computed } from 'vue'
import { AGENTS, agentMeta } from '../agents'
import type { ChatMessage } from '../types'

const props = defineProps<{
  message: ChatMessage
}>()

const isUser = computed(() => props.message.role === 'user')
const agent = computed(() => agentMeta(props.message.intent ?? ''))
const speaker = computed(() => (props.message.intent ? agent.value.role : '调度台'))
const knownAgent = computed(() =>
  AGENTS.some((item) => item.key === props.message.intent),
)
</script>

<template>
  <div class="msg-in flex w-full" :class="isUser ? 'justify-end' : 'justify-start'">
    <div class="max-w-[min(40rem,88%)]">
      <div
        class="mb-1.5 flex items-center gap-2 text-xs text-slate-400"
        :class="isUser ? 'justify-end' : ''"
      >
        <span v-if="!isUser" class="font-medium text-slate-600">{{ speaker }}</span>
        <span>{{ message.time }}</span>
        <span v-if="message.latencyMs" class="tabular-nums">{{ message.latencyMs }} ms</span>
      </div>

      <div
        class="rounded-xl px-3.5 py-2.5 text-left text-sm leading-relaxed whitespace-pre-wrap break-words"
        :class="
          isUser
            ? 'bg-brand-600 text-white'
            : 'border border-slate-200 bg-slate-50 text-slate-800'
        "
      >
        {{ message.content }}
      </div>

      <div
        v-if="!isUser && (message.compliancePassed !== undefined || (message.intent && !knownAgent))"
        class="mt-1.5 flex flex-wrap items-center gap-1.5"
      >
        <span
          v-if="message.intent && !knownAgent"
          class="rounded-md bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600"
        >
          {{ message.intent }}
        </span>
        <span
          v-if="message.compliancePassed !== undefined"
          class="rounded-md px-1.5 py-0.5 text-xs font-medium"
          :class="
            message.compliancePassed
              ? 'bg-emerald-50 text-emerald-700'
              : 'bg-rose-50 text-rose-700'
          "
        >
          {{ message.compliancePassed ? '合规通过' : '合规拦截' }}
        </span>
      </div>
    </div>
  </div>
</template>
