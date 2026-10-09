<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'

const props = defineProps<{
  sending: boolean
}>()

const emit = defineEmits<{
  (e: 'send', text: string): void
}>()

const text = ref('')
const inputRef = ref<HTMLTextAreaElement>()

function resize(): void {
  const el = inputRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 128)}px`
}

watch(text, () => nextTick(resize))

function submit(): void {
  const value = text.value.trim()
  if (!value || props.sending) return
  emit('send', value)
  text.value = ''
  nextTick(resize)
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    submit()
  }
}
</script>

<template>
  <div class="shrink-0 border-t border-slate-200 px-4 py-3">
    <div class="mx-auto max-w-3xl">
      <div
        class="flex items-end gap-2 rounded-xl border border-slate-200 bg-slate-50 p-2 transition focus-within:border-brand-400 focus-within:bg-white focus-within:ring-2 focus-within:ring-brand-100"
      >
        <textarea
          ref="inputRef"
          v-model="text"
          rows="1"
          placeholder="输入问题"
          class="max-h-32 min-h-9 flex-1 resize-none bg-transparent px-2 py-1.5 text-sm leading-5 outline-none placeholder:text-slate-400"
          :disabled="sending"
          @keydown="onKeydown"
        ></textarea>
        <button
          type="button"
          class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-600 text-white transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:bg-slate-300"
          aria-label="发送"
          :disabled="sending || !text.trim()"
          @click="submit"
        >
          <svg
            v-if="!sending"
            class="h-4 w-4"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2.2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M22 2 11 13" />
            <path d="M22 2 15 22l-4-9-9-4 20-7z" />
          </svg>
          <svg v-else class="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
            <circle
              class="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              stroke-width="4"
            />
            <path
              class="opacity-90"
              fill="currentColor"
              d="M4 12a8 8 0 0 1 8-8v4a4 4 0 0 0-4 4H4z"
            />
          </svg>
        </button>
      </div>
      <p class="mt-1.5 px-1 text-xs text-slate-400">Enter 发送，Shift + Enter 换行</p>
    </div>
  </div>
</template>
