import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuthStore } from './auth'

export interface SessionMeta {
  id: string
  title: string
  subject: string
  message_count: number
  created_at: string
  updated_at: string
}

export interface HistoryMessage {
  role: 'user' | 'assistant' | 'summary' // summary = compaction digest (PR#10)
  content: string
}

export const API_BASE = 'http://localhost:8000'

export const useSessionsStore = defineStore('sessions', () => {
  const auth = useAuthStore()
  const sessions = ref<SessionMeta[]>([])
  const currentSessionId = ref<string>('')
  const loaded = ref(false)

  function authHeaders(): Record<string, string> {
    const h: Record<string, string> = { 'Content-Type': 'application/json' }
    if (auth.token) h['Authorization'] = `Bearer ${auth.token}`
    return h
  }

  async function loadSessions() {
    try {
      const r = await fetch(`${API_BASE}/api/chat/sessions`, {
        headers: authHeaders(),
      })
      if (!r.ok) return
      sessions.value = await r.json()
    } catch {
      // backend offline — keep local list
    }
    loaded.value = true
  }

  async function createSession(subject: string, title?: string): Promise<SessionMeta | null> {
    try {
      const r = await fetch(`${API_BASE}/api/chat/sessions`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ subject, title }),
      })
      if (!r.ok) return null
      const s: SessionMeta = await r.json()
      sessions.value.unshift(s)
      currentSessionId.value = s.id
      return s
    } catch {
      return null
    }
  }

  async function deleteSession(id: string) {
    sessions.value = sessions.value.filter((s) => s.id !== id)
    if (currentSessionId.value === id) currentSessionId.value = ''
    try {
      await fetch(`${API_BASE}/api/chat/sessions/${id}`, {
        method: 'DELETE',
        headers: authHeaders(),
      })
    } catch {
      // ignore
    }
  }

  function selectSession(id: string) {
    currentSessionId.value = id
  }

  // Fetch a session's message history from the backend checkpointer.
  // Returns null on any failure (offline backend etc.) so callers can
  // keep their current view instead of blanking it.
  async function loadHistory(id: string): Promise<HistoryMessage[] | null> {
    try {
      const r = await fetch(`${API_BASE}/api/chat/sessions/${id}/messages`, {
        headers: authHeaders(),
      })
      if (!r.ok) return null
      return await r.json()
    } catch {
      return null
    }
  }

  async function touchSession(id: string, message: string) {
    // Bump title/count server-side; called after first user message.
    try {
      const r = await fetch(`${API_BASE}/api/chat/sessions/${id}/touch`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ message }),
      })
      if (r.ok) {
        const s: SessionMeta = await r.json()
        const i = sessions.value.findIndex((x) => x.id === id)
        if (i >= 0) sessions.value[i] = s
        else sessions.value.unshift(s)
      }
    } catch {
      // ignore
    }
  }

  return {
    sessions,
    currentSessionId,
    loaded,
    loadSessions,
    createSession,
    deleteSession,
    selectSession,
    loadHistory,
    touchSession,
  }
})
