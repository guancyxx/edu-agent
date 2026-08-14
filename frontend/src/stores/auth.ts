import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

interface User {
  id: string
  username: string
  email: string | null
  role: string
  grade: number
  display_name: string | null
}

const API_BASE = 'http://localhost:8000/api'
const TOKEN_KEY = 'edu_token'
const USER_KEY = 'edu_user'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem(TOKEN_KEY))
  const user = ref<User | null>(
    localStorage.getItem(USER_KEY) ? JSON.parse(localStorage.getItem(USER_KEY)!) : null
  )

  const isAuthenticated = computed(() => !!token.value)

  function setAuth(t: string, u: User) {
    token.value = t
    user.value = u
    localStorage.setItem(TOKEN_KEY, t)
    localStorage.setItem(USER_KEY, JSON.stringify(u))
  }

  function logout() {
    token.value = null
    user.value = null
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
  }

  async function login(username: string, password: string) {
    const resp = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    })
    if (!resp.ok) {
      const err = await resp.json()
      throw new Error(err.detail || 'Login failed')
    }
    const data = await resp.json()
    setAuth(data.access_token, data.user)
    return data
  }

  async function register(username: string, password: string, opts?: {
    email?: string; role?: string; grade?: number; display_name?: string
  }) {
    const resp = await fetch(`${API_BASE}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password, ...opts }),
    })
    if (!resp.ok) {
      const err = await resp.json()
      throw new Error(err.detail || 'Registration failed')
    }
    const data = await resp.json()
    setAuth(data.access_token, data.user)
    return data
  }

  return { token, user, isAuthenticated, login, register, logout, setAuth }
})
