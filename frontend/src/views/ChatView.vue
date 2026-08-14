<template>
  <div class="chat-view">
    <!-- Header -->
    <header class="chat-header">
      <div class="header-left">
        <span class="logo">📚</span>
        <span class="title">EduAgent</span>
        <span class="badge" v-if="connected">● 在线</span>
        <span class="badge offline" v-else>○ 连接中</span>
      </div>
      <div class="header-right">
        <select v-model="subject" class="subject-select">
          <option value="math">数学</option>
          <option value="english">英语</option>
          <option value="chinese">语文</option>
          <option value="physics">物理</option>
        </select>
      </div>
    </header>

    <!-- Messages -->
    <div class="messages" ref="messagesContainer">
      <div
        v-for="(msg, i) in messages"
        :key="i"
        class="message"
        :class="msg.role"
      >
        <div class="message-avatar">
          {{ msg.role === 'user' ? '🧑' : '🤖' }}
        </div>
        <div class="message-body">
          <div class="message-skill" v-if="msg.skill">
            <span class="skill-tag">{{ msg.skill }}</span>
          </div>
          <div class="message-content" v-html="renderMarkdown(msg.content)"></div>
        </div>
      </div>

      <!-- Typing indicator -->
      <div class="message assistant" v-if="loading">
        <div class="message-avatar">🤖</div>
        <div class="message-body">
          <div class="typing">
            <span></span><span></span><span></span>
          </div>
        </div>
      </div>
    </div>

    <!-- Input -->
    <div class="input-area">
      <textarea
        v-model="input"
        @keydown.enter.exact.prevent="send"
        placeholder="输入你的问题..."
        rows="1"
        ref="inputRef"
        @input="autoResize"
      ></textarea>
      <button @click="send" :disabled="!input.trim() || loading" class="send-btn">
        发送
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, onMounted, onUnmounted } from 'vue'

interface Message {
  role: 'user' | 'assistant'
  content: string
  skill?: string
}

const messages = ref<Message[]>([
  {
    role: 'assistant',
    content: '你好！我是你的 AI 学习助手。有什么不会的题目或者概念，随时问我吧！',
  },
])

const input = ref('')
const loading = ref(false)
const connected = ref(false)
const subject = ref('math')
const messagesContainer = ref<HTMLElement>()
const inputRef = ref<HTMLElement>()

let ws: WebSocket | null = null

// ── Markdown rendering (minimal, safe) ──────────────────────

function renderMarkdown(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\$\$(.+?)\$\$/g, '<div class="math-block">$$ $1 $$</div>')
    .replace(/\$(.+?)\$/g, '<span class="math-inline">$ $1 $</span>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
    .replace(/\n/g, '<br>')
}

// ── WebSocket ───────────────────────────────────────────────

function connect() {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsUrl = `${protocol}//${location.hostname}:8000/api/chat/ws`
  ws = new WebSocket(wsUrl)

  ws.onopen = () => {
    connected.value = true
  }

  ws.onclose = () => {
    connected.value = false
    setTimeout(connect, 3000)
  }

  ws.onerror = () => {
    connected.value = false
  }

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data)

    switch (data.type) {
      case 'trace':
        // Could show "正在分析..." etc.
        break

      case 'skill':
        // Attach skill info to the latest assistant message
        if (messages.value.length > 0) {
          const last = messages.value[messages.value.length - 1]
          if (last.role === 'assistant') {
            last.skill = data.skill
          }
        }
        break

      case 'chunk':
        // Append token to streaming message
        loading.value = false
        const lastMsg = messages.value[messages.value.length - 1]
        if (lastMsg && lastMsg.role === 'assistant') {
          lastMsg.content += data.content
        } else {
          messages.value.push({ role: 'assistant', content: data.content })
        }
        scrollToBottom()
        break

      case 'done':
        loading.value = false
        if (data.skill_used) {
          const last = messages.value[messages.value.length - 1]
          if (last && last.role === 'assistant') {
            last.skill = data.skill_used
          }
        }
        scrollToBottom()
        break

      case 'error':
        loading.value = false
        messages.value.push({
          role: 'assistant',
          content: `⚠️ ${data.message}`,
        })
        scrollToBottom()
        break
    }
  }
}

// ── Send ────────────────────────────────────────────────────

function send() {
  const text = input.value.trim()
  if (!text || loading.value) return

  messages.value.push({ role: 'user', content: text })
  input.value = ''
  loading.value = true

  // Reserve a placeholder for the streaming response
  messages.value.push({ role: 'assistant', content: '' })

  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      message: text,
      student_id: 'web-user',
      subject: subject.value,
      grade: 7,
    }))
  } else {
    // Fallback to HTTP
    fetch('http://localhost:8000/api/chat/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: text,
        student_id: 'web-user',
        subject: subject.value,
        grade: 7,
      }),
    })
      .then(r => r.json())
      .then(data => {
        loading.value = false
        const last = messages.value[messages.value.length - 1]
        if (last && last.role === 'assistant') {
          last.content = data.reply
          last.skill = data.skill_used
        }
        scrollToBottom()
      })
      .catch(err => {
        loading.value = false
        const last = messages.value[messages.value.length - 1]
        if (last && last.role === 'assistant') {
          last.content = `⚠️ 连接失败: ${err.message}`
        }
      })
  }

  scrollToBottom()
}

// ── Utilities ───────────────────────────────────────────────

function autoResize() {
  const el = inputRef.value as HTMLTextAreaElement
  if (el) {
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 120) + 'px'
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
}

onMounted(() => {
  connect()
})

onUnmounted(() => {
  ws?.close()
})
</script>

<style scoped>
.chat-view {
  display: flex;
  flex-direction: column;
  height: 100vh;
  max-width: 720px;
  margin: 0 auto;
  background: var(--bg-secondary);
}

/* Header */
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background: var(--bg-tertiary);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.logo { font-size: 24px; }
.title { font-weight: 700; font-size: 18px; }

.badge {
  font-size: 11px;
  color: #4ade80;
  margin-left: 4px;
}
.badge.offline { color: var(--text-secondary); }

.subject-select {
  background: var(--bg-primary);
  color: var(--text-primary);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px 10px;
  font-size: 13px;
  cursor: pointer;
}

/* Messages */
.messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.message {
  display: flex;
  gap: 10px;
  max-width: 85%;
}

.message.user {
  align-self: flex-end;
  flex-direction: row-reverse;
}

.message-avatar {
  font-size: 28px;
  flex-shrink: 0;
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-tertiary);
  border-radius: 50%;
}

.message-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.message.user .message-body {
  align-items: flex-end;
}

.message-skill {
  display: flex;
  gap: 4px;
}

.skill-tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 6px;
  background: rgba(74, 158, 255, 0.15);
  color: var(--accent);
}

.message-content {
  padding: 12px 16px;
  border-radius: var(--radius);
  font-size: 15px;
  line-height: 1.6;
}

.message.user .message-content {
  background: var(--accent);
  color: white;
}

.message.assistant .message-content {
  background: var(--bg-tertiary);
}

.message-content :deep(strong) { font-weight: 600; }
.message-content :deep(code) {
  background: rgba(255,255,255,0.1);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 13px;
}
.message-content :deep(.math-block) {
  margin: 8px 0;
  padding: 8px;
  text-align: center;
  color: #e8d5ff;
}

/* Typing indicator */
.typing {
  display: flex;
  gap: 4px;
  padding: 12px 16px;
  background: var(--bg-tertiary);
  border-radius: var(--radius);
}

.typing span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--text-secondary);
  animation: bounce 1.4s infinite;
}

.typing span:nth-child(2) { animation-delay: 0.2s; }
.typing span:nth-child(3) { animation-delay: 0.4s; }

@keyframes bounce {
  0%, 60%, 100% { transform: translateY(0); }
  30% { transform: translateY(-8px); }
}

/* Input */
.input-area {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  background: var(--bg-tertiary);
  border-top: 1px solid var(--border);
  flex-shrink: 0;
}

.input-area textarea {
  flex: 1;
  background: var(--bg-primary);
  color: var(--text-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 10px 14px;
  font-size: 15px;
  font-family: var(--font);
  resize: none;
  outline: none;
  transition: border-color 0.2s;
}

.input-area textarea:focus {
  border-color: var(--accent);
}

.send-btn {
  background: var(--accent);
  color: white;
  border: none;
  border-radius: var(--radius);
  padding: 0 20px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s;
}

.send-btn:hover:not(:disabled) {
  background: var(--accent-hover);
}

.send-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>
