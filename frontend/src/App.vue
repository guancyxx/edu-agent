<template>
  <div class="app" :class="{ 'is-mobile': isMobile }">
    <ChatView />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import ChatView from './views/ChatView.vue'

const isMobile = computed(() => {
  return /Android|iPhone|iPad|iPod/i.test(navigator.userAgent)
})
</script>

<style>
:root {
  --bg-primary: #0f0f0f;
  --bg-secondary: #1a1a1a;
  --bg-tertiary: #242424;
  --text-primary: #e0e0e0;
  --text-secondary: #888;
  --accent: #4a9eff;
  --accent-hover: #6bb0ff;
  --border: #333;
  --radius: 12px;
  --font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: var(--font);
  background: var(--bg-primary);
  color: var(--text-primary);
  -webkit-font-smoothing: antialiased;
}

.app {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.app.is-mobile {
  font-size: 15px;
}

/* Responsive */
@media (min-width: 768px) {
  .app {
    max-width: 100%;
  }
}
</style>
