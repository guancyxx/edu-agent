import { defineStore } from 'pinia'
import { ref } from 'vue'

interface Mistake {
  id: number
  subject: string
  question: string
  student_answer: string | null
  correct_answer: string | null
  explanation: string | null
  knowledge_point_id: string | null
  review_count: number
  ease_factor: number
  interval_days: number
  next_review_at: string
  last_reviewed_at: string | null
  status: string
  created_at: string
}

interface Stats {
  total: number
  learning: number
  reviewing: number
  mastered: number
  due_today: number
}

const API_BASE = 'http://localhost:8000/api'

export const useMistakesStore = defineStore('mistakes', () => {
  const mistakes = ref<Mistake[]>([])
  const due = ref<Mistake[]>([])
  const stats = ref<Stats | null>(null)
  const loading = ref(false)

  function authHeaders(): Record<string, string> {
    const token = localStorage.getItem('edu_token')
    return {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
    }
  }

  async function fetchAll() {
    loading.value = true
    try {
      const resp = await fetch(`${API_BASE}/mistakes`, { headers: authHeaders() })
      if (!resp.ok) throw new Error('加载失败')
      mistakes.value = await resp.json()
    } finally {
      loading.value = false
    }
  }

  async function fetchDue() {
    const resp = await fetch(`${API_BASE}/mistakes/due`, { headers: authHeaders() })
    if (resp.ok) due.value = await resp.json()
  }

  async function fetchStats() {
    const resp = await fetch(`${API_BASE}/mistakes/stats`, { headers: authHeaders() })
    if (resp.ok) stats.value = await resp.json()
  }

  async function review(id: number, quality: number) {
    const resp = await fetch(`${API_BASE}/mistakes/${id}/review`, {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ quality }),
    })
    if (!resp.ok) throw new Error('提交失败')
    return await resp.json()
  }

  async function remove(id: number) {
    const resp = await fetch(`${API_BASE}/mistakes/${id}`, {
      method: 'DELETE',
      headers: authHeaders(),
    })
    if (!resp.ok) throw new Error('删除失败')
    mistakes.value = mistakes.value.filter(m => m.id !== id)
    due.value = due.value.filter(m => m.id !== id)
  }

  return { mistakes, due, stats, loading, fetchAll, fetchDue, fetchStats, review, remove }
})
