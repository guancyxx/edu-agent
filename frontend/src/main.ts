import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './assets/layout.css'

// Apply persisted theme before first paint to avoid flash
const theme = localStorage.getItem('edu_theme') || 'dark'
document.documentElement.setAttribute('data-theme', theme)

createApp(App).use(createPinia()).use(router).mount('#app')
