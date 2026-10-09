<script setup lang="ts">
import type { Session } from '../types'

defineProps<{
  sessions: Session[]
  activeId: string
  online: boolean | null
}>()

const emit = defineEmits<{
  (e: 'new'): void
  (e: 'switch', id: string): void
}>()
</script>

<template>
  <aside class="flex w-60 shrink-0 flex-col border-r border-slate-200 bg-slate-50">
    <div class="flex h-14 items-center gap-2.5 border-b border-slate-200 px-4">
      <div
        class="flex h-7 w-7 items-center justify-center rounded-md bg-brand-600 text-xs font-semibold text-white"
      >
        知
      </div>
      <div class="min-w-0 leading-tight">
        <p class="text-sm font-semibold text-slate-900">知客</p>
        <p class="text-xs text-slate-400">调度台</p>
      </div>
    </div>

    <div class="p-3">
      <button
        type="button"
        class="flex w-full items-center justify-center gap-1.5 rounded-lg bg-brand-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-brand-700"
        @click="emit('new')"
      >
        <svg
          class="h-3.5 w-3.5"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2.2"
          stroke-linecap="round"
        >
          <path d="M12 5v14M5 12h14" />
        </svg>
        新会话
      </button>
    </div>

    <div class="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
      <p class="px-2 pb-1.5 text-xs font-medium text-slate-400">会话</p>
      <p v-if="sessions.length === 0" class="px-2 py-3 text-xs text-slate-400">
        还没有会话
      </p>
      <button
        v-for="session in sessions"
        :key="session.id"
        type="button"
        class="mb-1 w-full rounded-lg px-2.5 py-2 text-left transition"
        :class="
          session.id === activeId
            ? 'bg-white text-slate-900 shadow-sm ring-1 ring-slate-200'
            : 'text-slate-600 hover:bg-white'
        "
        @click="emit('switch', session.id)"
      >
        <p class="truncate text-sm font-medium">{{ session.title }}</p>
        <p class="mt-0.5 text-xs text-slate-400">
          {{ session.createdAt }} · {{ session.messages.length }} 条
        </p>
      </button>
    </div>

    <div class="flex items-center gap-2 border-t border-slate-200 px-4 py-3 text-xs">
      <span
        class="h-1.5 w-1.5 rounded-full"
        :class="
          online === null ? 'bg-slate-300' : online ? 'bg-emerald-500' : 'bg-rose-500'
        "
      ></span>
      <span
        :class="
          online === null
            ? 'text-slate-400'
            : online
              ? 'text-slate-600'
              : 'font-medium text-rose-600'
        "
      >
        {{ online === null ? '正在连接后端' : online ? '后端在线' : '后端离线' }}
      </span>
    </div>
  </aside>
</template>
