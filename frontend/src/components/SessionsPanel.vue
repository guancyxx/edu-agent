<template>
  <div class="sessions-panel">
    <div class="sessions-toolbar">
      <span class="sessions-count">{{ sessions.length }} 会话</span>
      <button class="sessions-new-btn" @click="newSession" title="新建会话">＋ 新对话</button>
    </div>

    <div class="session-list">
      <div
        v-for="s in sessions"
        :key="s.id"
        class="session-item"
        :class="{ active: s.id === sessionsStore.currentSessionId }"
        role="button"
        tabindex="0"
        @click="sessionsStore.selectSession(s.id)"
        @keydown.enter.space.prevent="sessionsStore.selectSession(s.id)"
      >
        <div class="session-main">
          <span class="session-subject-tag">{{ subjectLabel(s.subject) }}</span>
          <div class="session-title">{{ s.title || '新对话' }}</div>
          <div class="session-meta">
            {{ s.message_count }} 条 · {{ formatTime(s.updated_at) }}
          </div>
        </div>
        <button
          class="session-delete-btn"
          title="删除此会话"
          @click.stop="sessionsStore.deleteSession(s.id)"
        >&times;</button>
      </div>
    </div>

    <div class="sessions-empty" v-if="sessionsStore.loaded && sessions.length === 0">
      <span class="big-icon">💬</span>
      <span>暂无会话<br />点击「新对话」开始学习</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useSessionsStore } from '../stores/sessions'

const sessionsStore = useSessionsStore()
const sessions = computed(() => sessionsStore.sessions)

const SUBJECT_LABELS: Record<string, string> = {
  math: '数学',
  english: '英语',
  chinese: '语文',
  physics: '物理',
}

function subjectLabel(s: string) {
  return SUBJECT_LABELS[s] || s
}

function formatTime(iso: string) {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

async function newSession() {
  // subject inherited from chat panel selection (default math)
  await sessionsStore.createSession(
    (window as any).__eduCurrentSubject || 'math'
  )
}
</script>
