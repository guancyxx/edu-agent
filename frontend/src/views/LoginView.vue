<template>
  <div class="login-view">
    <div class="login-card">
      <div class="logo-area">
        <span class="logo-icon">📚</span>
        <h1 class="logo-text">EduAgent</h1>
        <p class="tagline">AI 自适应学习助手</p>
      </div>

      <div class="tabs">
        <button
          :class="{ active: mode === 'login' }"
          @click="mode = 'login'"
        >登录</button>
        <button
          :class="{ active: mode === 'register' }"
          @click="mode = 'register'"
        >注册</button>
      </div>

      <form @submit.prevent="submit" class="form">
        <div class="field">
          <label>用户名</label>
          <input
            v-model="username"
            type="text"
            placeholder="3-32 个字符"
            autocomplete="username"
            required
          />
        </div>

        <div class="field">
          <label>密码</label>
          <input
            v-model="password"
            type="password"
            placeholder="至少 6 位"
            autocomplete="current-password"
            required
          />
        </div>

        <template v-if="mode === 'register'">
          <div class="field">
            <label>昵称（可选）</label>
            <input v-model="displayName" type="text" placeholder="你的昵称" />
          </div>
          <div class="field-row">
            <div class="field">
              <label>年级</label>
              <select v-model="grade">
                <option v-for="g in 12" :key="g" :value="g">{{ g }} 年级</option>
              </select>
            </div>
            <div class="field">
              <label>身份</label>
              <select v-model="role">
                <option value="student">学生</option>
                <option value="parent">家长</option>
                <option value="teacher">教师</option>
              </select>
            </div>
          </div>
        </template>

        <div class="error-msg" v-if="error">{{ error }}</div>

        <button type="submit" class="submit-btn" :disabled="loading">
          {{ loading ? '请稍候...' : (mode === 'login' ? '登录' : '注册') }}
        </button>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()

const mode = ref<'login' | 'register'>('login')
const username = ref('')
const password = ref('')
const displayName = ref('')
const grade = ref(7)
const role = ref('student')
const error = ref('')
const loading = ref(false)

async function submit() {
  error.value = ''
  loading.value = true
  try {
    if (mode.value === 'login') {
      await auth.login(username.value, password.value)
    } else {
      await auth.register(username.value, password.value, {
        grade: grade.value,
        role: role.value,
        display_name: displayName.value || undefined,
      })
    }
    router.push('/')
  } catch (e: any) {
    error.value = e.message || '操作失败'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-view {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-primary);
  padding: 20px;
}

.login-card {
  width: 100%;
  max-width: 400px;
  background: var(--bg-secondary);
  border-radius: 16px;
  padding: 32px;
  border: 1px solid var(--border);
}

.logo-area {
  text-align: center;
  margin-bottom: 24px;
}

.logo-icon { font-size: 40px; }

.logo-text {
  font-size: 24px;
  font-weight: 700;
  margin-top: 8px;
}

.tagline {
  color: var(--text-secondary);
  font-size: 14px;
  margin-top: 4px;
}

.tabs {
  display: flex;
  gap: 0;
  margin-bottom: 20px;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid var(--border);
}

.tabs button {
  flex: 1;
  padding: 10px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.tabs button.active {
  background: var(--accent);
  color: white;
}

.form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
}

.field label {
  font-size: 13px;
  color: var(--text-secondary);
}

.field input, .field select {
  background: var(--bg-primary);
  color: var(--text-primary);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 15px;
  outline: none;
  font-family: var(--font);
}

.field input:focus, .field select:focus {
  border-color: var(--accent);
}

.field-row {
  display: flex;
  gap: 12px;
}

.error-msg {
  color: #ff6b6b;
  font-size: 13px;
  padding: 6px 0;
}

.submit-btn {
  background: var(--accent);
  color: white;
  border: none;
  border-radius: 10px;
  padding: 12px;
  font-size: 16px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s;
  margin-top: 4px;
}

.submit-btn:hover:not(:disabled) {
  background: var(--accent-hover);
}

.submit-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
