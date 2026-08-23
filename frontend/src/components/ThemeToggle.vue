<script setup>
import { ref, onMounted, onUnmounted } from 'vue'

const theme = ref(localStorage.getItem('edu_theme') || 'dark')

function apply() {
  document.documentElement.setAttribute('data-theme', theme.value)
  localStorage.setItem('edu_theme', theme.value)
}

function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
  apply()
}

onMounted(apply)
onUnmounted(() => {})
</script>

<template>
  <button
    class="theme-toggle-btn"
    :aria-label="theme === 'dark' ? '切换到浅色主题' : '切换到深色主题'"
    :title="theme === 'dark' ? '切换到浅色主题' : '切换到深色主题'"
    @click="toggleTheme"
  >
    <svg
      v-if="theme === 'dark'"
      class="theme-icon"
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="2.4"
      stroke-linecap="round"
      stroke-linejoin="round"
    >
      <circle cx="12" cy="12" r="4.8" />
      <line x1="12" y1="1" x2="12" y2="3" />
      <line x1="12" y1="21" x2="12" y2="23" />
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
      <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
      <line x1="1" y1="12" x2="3" y2="12" />
      <line x1="21" y1="12" x2="23" y2="12" />
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
      <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
    </svg>
    <svg
      v-else
      class="theme-icon"
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="2.4"
      stroke-linecap="round"
      stroke-linejoin="round"
    >
      <path d="M20.2 14.1A8.4 8.4 0 1 1 9.9 3.8a7 7 0 1 0 10.3 10.3z" />
    </svg>
  </button>
</template>

<style scoped>
.theme-toggle-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg-tertiary);
  color: var(--text-secondary);
  cursor: pointer;
  transition: background 0.16s ease, border-color 0.16s ease, color 0.16s ease;
  flex-shrink: 0;
}

.theme-toggle-btn:hover {
  color: var(--accent);
  border-color: var(--accent);
}

.theme-icon {
  width: 18px;
  height: 18px;
}
</style>
