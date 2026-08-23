<template>
  <div class="chat-workspace">
    <!-- Top bar -->
    <header class="top-bar">
      <div class="top-left">
        <span class="logo">📚</span>
        <span class="title">EduAgent</span>
        <span class="badge" v-if="connected">● 在线</span>
        <span class="badge offline" v-else>○ 连接中</span>
      </div>
      <div class="top-right">
        <select v-model="subject" class="subject-select">
          <option value="math">数学</option>
          <option value="english">英语</option>
          <option value="chinese">语文</option>
          <option value="physics">物理</option>
        </select>
        <ThemeToggle />
        <button class="mistakes-btn" @click="$router.push('/mistakes')">📒 错题本</button>
        <span class="user-name" v-if="auth.user">{{ auth.user.display_name || auth.user.username }}</span>
        <button class="logout-btn" @click="handleLogout">退出</button>
      </div>
    </header>

    <!-- ── Three horizontal collapsible segments ── -->
    <div class="content-grid" :style="{ gridTemplateColumns: gridCols }">
      <!-- Segment 1: session list -->
      <div class="panel-wrapper" :class="{ collapsed: collapsed.sessions }">
        <div class="panel-header" v-show="!collapsed.sessions">
          <span class="panel-title">对话列表</span>
          <button class="panel-toggle-btn" title="折叠" @click="collapsed.sessions = true">◀</button>
        </div>
        <div class="panel-strip" v-show="collapsed.sessions">
          <button class="panel-toggle-btn" title="展开" @click="collapsed.sessions = false">▶</button>
          <span class="panel-title-v">对话列表</span>
        </div>
        <div class="panel-body" v-show="!collapsed.sessions">
          <SessionsPanel />
        </div>
      </div>

      <!-- Segment 2: chat window -->
      <div class="panel-wrapper" :class="{ collapsed: collapsed.chat }">
        <div class="panel-header" v-show="!collapsed.chat">
          <span class="panel-title">AI 对话</span>
          <button class="panel-toggle-btn" title="折叠" @click="collapsed.chat = true">◀</button>
        </div>
        <div class="panel-strip" v-show="collapsed.chat">
          <button class="panel-toggle-btn" title="展开" @click="collapsed.chat = false">▶</button>
          <span class="panel-title-v">AI 对话</span>
        </div>
        <div class="panel-body" v-show="!collapsed.chat">
          <div class="messages" ref="messagesContainer">
            <div v-for="(msg, i) in messages" :key="i" class="message" :class="msg.role">
              <div class="message-avatar">{{ msg.role === 'user' ? '🧑' : '🤖' }}</div>
              <div class="message-body">
                <div class="message-skill" v-if="msg.skill">
                  <span class="skill-tag">{{ msg.skill }}</span>
                </div>
                <div class="message-content" v-html="renderMarkdown(msg.content)"></div>
              </div>
            </div>
            <div class="message assistant" v-if="loading">
              <div class="message-avatar">🤖</div>
              <div class="message-body">
                <div class="typing"><span></span><span></span><span></span></div>
              </div>
            </div>
          </div>
          <div class="input-area">
            <textarea
              v-model="input"
              @keydown.enter.exact.prevent="send"
              placeholder="输入你的问题...（可粘贴或描述题目）"
              rows="1"
              ref="inputRef"
              @input="autoResize"
            ></textarea>
            <button @click="send" :disabled="!input.trim() || loading" class="send-btn">发送</button>
          </div>
        </div>
      </div>

      <!-- Segment 3: answer board -->
      <div class="panel-wrapper" :class="{ collapsed: collapsed.board }">
        <div class="panel-header" v-show="!collapsed.board">
          <span class="panel-title">答题板</span>
          <button class="panel-toggle-btn" title="折叠" @click="collapsed.board = true">◀</button>
        </div>
        <div class="panel-strip" v-show="collapsed.board">
          <button class="panel-toggle-btn" title="展开" @click="collapsed.board = false">▶</button>
          <span class="panel-title-v">答题板</span>
        </div>
        <div class="panel-body" v-show="!collapsed.board">
          <AnswerBoard ref="answerBoardRef" @ask-agent="handleAskFromBoard" @import-from-chat="importQuestionFromChat" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, nextTick, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useSessionsStore } from '../stores/sessions'
import ThemeToggle from '../components/ThemeToggle.vue'
import SessionsPanel from '../components/SessionsPanel.vue'
import AnswerBoard from '../components/AnswerBoard.vue'

interface Message {
  role: 'user' | 'assistant'
  content: string
  skill?: string
}

const router = useRouter()
const auth = useAuthStore()
const sessionsStore = useSessionsStore()

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
const answerBoardRef = ref<InstanceType<typeof AnswerBoard>>()

// Keep the global subject for the sessions panel's new-session button
;(window as any).__eduCurrentSubject = subject.value
watch(subject, (v) => { (window as any).__eduCurrentSubject = v })

// ── Collapsible layout state ──
const collapsed = reactive({ sessions: false, chat: false, board: false })

const gridCols = computed(() => {
  const w = (key: keyof typeof collapsed) => (collapsed[key] ? '40px' : '1fr')
  return `minmax(200px, 240px) ${w('chat')} ${w('board')}`
})

// ── Markdown rendering (minimal, safe) ──────────────────────

// Extract self-contained <svg>...</svg> blocks before escaping, so diagrams render raw.
// Security: only pure-shape SVG allowed — any block containing <script>, on* handlers,
// script-scheme / external / data: URLs, animate-based attribute mutation, or CSS url()
// loaders is dropped entirely (fail-closed). See AUDIT note in PR #3.
// NOTE (audit N3, restored): this scrub passed a Critical XSS audit — the probe tests
// the raw block AND its entity-decoded form (browser decodes &#106; at parse time);
// url(#fragment) refs to in-svg defs are whitelisted; do not weaken without re-audit.
const SVG_OPEN_RE = /<svg\b[^>]*>/

function extractSvgs(text: string): { text: string, svgs: string[] } {
  const svgs: string[] = []
  let out = ''
  let rest = text
  while (true) {
    const open = rest.match(SVG_OPEN_RE)
    if (!open || open.index === undefined) { out += rest; break }
    const start = open.index
    const close = rest.indexOf('</svg>', start)
    if (close === -1) { out += rest; break }
    let svg = rest.slice(start, close + 6)
    const probe = svg + '\n' + decodeEntities(svg)
    if (
      /<script[\s>]/i.test(probe) ||
      /\son\w+\s*=/i.test(probe) ||
      /(href|src)\s*=\s*["']?\s*(https?:|data:|javascript:|vbscript:)/i.test(probe) ||
      /to\s*=\s*["']?\s*(?:javascript|vbscript):/i.test(probe) ||
      /attributeName\s*=\s*["']?\s*(on\w+|href|xlink:href)/i.test(probe) ||
      /url\(\s*(?!#)/i.test(probe)
    ) {
      svg = ''
    }
    out += rest.slice(0, start) + `\x00SVG${svgs.length}\x00`
    svgs.push(svg)
    rest = rest.slice(close + 6)
  }
  return { text: out, svgs }
}

function decodeEntities(s: string): string {
  return s
    .replace(/&#x([0-9a-f]+);/gi, (_, h: string) => safeCodePoint(parseInt(h, 16)))
    .replace(/&#(\d+);/g, (_, d: string) => safeCodePoint(parseInt(d, 10)))
    .replace(/&quot;/gi, '"')
    .replace(/&apos;/gi, "'")
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&amp;/gi, '&')
}

function safeCodePoint(cp: number): string {
  try { return String.fromCodePoint(cp) } catch { return '' }
}

function renderMarkdown(text: string): string {
  const { text: escaped, svgs } = extractSvgs(text)
  let html = escaped
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\$\$(.+?)\$\$/g, '<div class="math-block">$$ $1 $$</div>')
    .replace(/\$(.+?)\$/g, '<span class="math-inline">$ $1 $</span>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
    .replace(/\n/g, '<br>')
  svgs.forEach((svg, i) => {
    html = html.replace(`\x00SVG${i}\x00`, () => svg)
  })
  return html
}

// ── Answer board integration ──

function handleAskFromBoard(payload: { message: string }) {
  input.value = payload.message
  send()
}

function importQuestionFromChat() {
  // Grab the latest recognized/typed question text from the conversation:
  // prefer the last user message; fall back to vision-extracted block.
  const lastUser = [...messages.value].reverse().find((m) => m.role === 'user')
  if (!lastUser) return
  let q = lastUser.content
  const vision = q.match(/\[图片识别出的题目\]\n?([\s\S]*)/)
  if (vision) q = vision[1].trim()
  answerBoardRef.value?.setQuestion(q)
}

// ── WebSocket ──

let ws: WebSocket | null = null

function connect() {
  const token = auth.token
  if (!token) {
    router.push('/login')
    return
  }

  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsUrl = `${protocol}//${location.hostname}:8000/api/chat/ws?token=${token}`
  ws = new WebSocket(wsUrl)

  ws.onopen = () => {
    connected.value = true
  }

  ws.onclose = () => {
    connected.value = false
    if (auth.isAuthenticated) {
      setTimeout(connect, 3000)
    }
  }

  ws.onerror = () => {
    connected.value = false
  }

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data)

    switch (data.type) {
      case 'auth_error':
        loading.value = false
        auth.logout()
        router.push('/login')
        break

      case 'trace':
        break

      case 'skill':
        if (messages.value.length > 0) {
          const last = messages.value[messages.value.length - 1]
          if (last.role === 'assistant') {
            last.skill = data.skill
          }
        }
        break

      case 'chunk':
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

function handleLogout() {
  auth.logout()
  ws?.close()
  router.push('/login')
}

// ── Send ──

function send() {
  const text = input.value.trim()
  if (!text || loading.value) return

  messages.value.push({ role: 'user', content: text })
  input.value = ''
  loading.value = true

  messages.value.push({ role: 'assistant', content: '' })

  // Ensure we have a session to attribute this message to
  if (!sessionsStore.currentSessionId) {
    sessionsStore.createSession(subject.value).then(() => {
      sessionsStore.touchSession(sessionsStore.currentSessionId, text)
    })
  } else {
    sessionsStore.touchSession(sessionsStore.currentSessionId, text)
  }

  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      message: text,
      subject: subject.value,
      session_id: sessionsStore.currentSessionId || undefined,
    }))
  } else {
    fetch('http://localhost:8000/api/chat/send', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${auth.token}`,
      },
      body: JSON.stringify({
        message: text,
        subject: subject.value,
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

// ── Utilities ──

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
  sessionsStore.loadSessions()
})

onUnmounted(() => {
  ws?.close()
})
</script>

<style scoped>
.chat-workspace {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--bg-primary);
}

.top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  background: var(--bg-tertiary);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.top-left,
.top-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.user-name {
  font-size: 13px;
  color: var(--text-secondary);
}

.logout-btn {
  background: transparent;
  color: var(--text-secondary);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 4px 10px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.mistakes-btn {
  background: transparent;
  color: var(--accent);
  border: 1px solid var(--accent);
  border-radius: 6px;
  padding: 4px 10px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.mistakes-btn:hover {
  background: rgba(74, 158, 255, 0.1);
}

.logout-btn:hover {
  color: #ff6b6b;
  border-color: #ff6b6b;
}

.logo { font-size: 22px; }
.title { font-weight: 700; font-size: 17px; }

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

/* Messages (inside middle panel-body) */
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
  font-size: 24px;
  flex-shrink: 0;
  width: 36px;
  height: 36px;
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

.skill-tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 6px;
  background: rgba(74, 158, 255, 0.15);
  color: var(--accent);
}

.message-content {
  padding: 12px 16px;
  border-radius: 12px;
  font-size: 15px;
  line-height: 1.6;
}

.message.user .message-content {
  background: var(--accent);
  color: white;
}

.message.assistant .message-content {
  background: var(--bg-secondary);
}

.typing {
  display: flex;
  gap: 4px;
  padding: 12px 16px;
  background: var(--bg-secondary);
  border-radius: 12px;
}

.typing span {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--text-secondary);
  animation: typing-blink 1.2s infinite;
}

.typing span:nth-child(2) { animation-delay: 0.2s; }
.typing span:nth-child(3) { animation-delay: 0.4s; }

@keyframes typing-blink {
  0%, 60%, 100% { opacity: 0.3; }
  30% { opacity: 1; }
}

/* Input */
.input-area {
  display: flex;
  gap: 8px;
  padding: 12px;
  border-top: 1px solid var(--border);
  flex-shrink: 0;
}

.input-area textarea {
  flex: 1;
  background: var(--bg-secondary);
  color: var(--text-primary);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 10px 14px;
  font-size: 14px;
  font-family: inherit;
  resize: none;
  outline: none;
}

.input-area textarea:focus {
  border-color: var(--accent);
}

.send-btn {
  padding: 0 22px;
  border: none;
  border-radius: 10px;
  background: var(--accent);
  color: white;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

.send-btn:hover { background: var(--accent-hover); }
.send-btn:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
