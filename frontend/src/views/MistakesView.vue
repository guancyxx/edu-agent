<template>
  <div class="mistakes-view">
    <header class="page-header">
      <button class="back-btn" @click="$router.push('/')">← 返回</button>
      <h1 class="page-title">📒 错题本</h1>
      <div class="header-spacer"></div>
    </header>

    <!-- Stats bar -->
    <div class="stats-bar" v-if="store.stats">
      <div class="stat">
        <span class="stat-value">{{ store.stats.due_today }}</span>
        <span class="stat-label">今日待复习</span>
      </div>
      <div class="stat">
        <span class="stat-value">{{ store.stats.learning }}</span>
        <span class="stat-label">学习中</span>
      </div>
      <div class="stat">
        <span class="stat-value">{{ store.stats.reviewing }}</span>
        <span class="stat-label">复习中</span>
      </div>
      <div class="stat">
        <span class="stat-value">{{ store.stats.mastered }}</span>
        <span class="stat-label">已掌握</span>
      </div>
      <div class="stat total">
        <span class="stat-value">{{ store.stats.total }}</span>
        <span class="stat-label">总计</span>
      </div>
    </div>

    <!-- Tabs -->
    <div class="tabs">
      <button :class="{ active: tab === 'due' }" @click="switchTab('due')">
        待复习 ({{ store.due.length }})
      </button>
      <button :class="{ active: tab === 'all' }" @click="switchTab('all')">
        全部 ({{ store.mistakes.length }})
      </button>
    </div>

    <!-- Review mode: flashcard -->
    <div class="review-card" v-if="tab === 'due' && currentReview">
      <div class="review-subject">{{ subjectName(currentReview.subject) }} · 第 {{ currentReview.review_count + 1 }} 次复习</div>
      <div class="review-question">{{ currentReview.question }}</div>

      <div class="review-answer" v-if="revealed">
        <div v-if="currentReview.correct_answer" class="answer-section">
          <span class="answer-label">正确答案</span>
          <div class="answer-content">{{ currentReview.correct_answer }}</div>
        </div>
        <div v-if="currentReview.explanation" class="answer-section">
          <span class="answer-label">解析</span>
          <div class="answer-content">{{ currentReview.explanation }}</div>
        </div>
        <div v-if="currentReview.student_answer" class="answer-section wrong">
          <span class="answer-label">你的答案</span>
          <div class="answer-content">{{ currentReview.student_answer }}</div>
        </div>
      </div>

      <div v-if="!revealed" class="reveal-btn" @click="revealed = true">
        显示答案
      </div>

      <div class="review-buttons" v-else>
        <button class="q-btn q0" @click="submitReview(0)">完全忘了</button>
        <button class="q-btn q3" @click="submitReview(3)">想起来了</button>
        <button class="q-btn q4" @click="submitReview(4)">基本会</button>
        <button class="q-btn q5" @click="submitReview(5)">完全掌握</button>
      </div>
    </div>

    <!-- Empty due state -->
    <div class="empty-state" v-else-if="tab === 'due'">
      <span class="empty-icon">🎉</span>
      <p>没有待复习的错题了！</p>
      <p class="empty-sub">新错题会自动加入，到时间会提醒你复习</p>
    </div>

    <!-- All mistakes list -->
    <div class="mistake-list" v-else-if="tab === 'all'">
      <div class="mistake-item" v-for="m in store.mistakes" :key="m.id">
        <div class="mistake-head">
          <span class="subject-tag">{{ subjectName(m.subject) }}</span>
          <span class="status-tag" :class="m.status">{{ statusName(m.status) }}</span>
          <span class="delete-btn" @click="removeMistake(m.id)">✕</span>
        </div>
        <div class="mistake-question">{{ m.question }}</div>
        <div class="mistake-answer" v-if="m.correct_answer">
          <span class="answer-label">答案：</span>{{ m.correct_answer }}
        </div>
        <div class="mistake-meta">
          <span>复习 {{ m.review_count }} 次</span>
          <span>间隔 {{ m.interval_days }} 天</span>
          <span>下次 {{ formatDate(m.next_review_at) }}</span>
        </div>
      </div>

      <div class="empty-state" v-if="store.mistakes.length === 0 && !store.loading">
        <span class="empty-icon">📭</span>
        <p>错题本是空的</p>
        <p class="empty-sub">做错的题会自动收录到这里</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useMistakesStore } from '../stores/mistakes'

const store = useMistakesStore()
const tab = ref<'due' | 'all'>('due')
const currentReview = ref<any>(null)
const revealed = ref(false)

const subjectMap: Record<string, string> = {
  math: '数学', english: '英语', chinese: '语文', physics: '物理', chemistry: '化学', general: '通用',
}
const statusMap: Record<string, string> = {
  learning: '学习中', reviewing: '复习中', mastered: '已掌握',
}

function subjectName(s: string) { return subjectMap[s] || s }
function statusName(s: string) { return statusMap[s] || s }

function formatDate(iso: string) {
  const d = new Date(iso)
  return `${d.getMonth() + 1}/${d.getDate()}`
}

async function switchTab(t: 'due' | 'all') {
  tab.value = t
  if (t === 'due') {
    await store.fetchDue()
    currentReview.value = store.due[0] || null
    revealed.value = false
  } else {
    await store.fetchAll()
  }
}

async function submitReview(quality: number) {
  if (!currentReview.value) return
  const id = currentReview.value.id
  await store.review(id, quality)
  // Move to next due item
  await store.fetchDue()
  currentReview.value = store.due[0] || null
  revealed.value = false
  await store.fetchStats()
}

async function removeMistake(id: number) {
  if (confirm('删除这条错题？')) {
    await store.remove(id)
    await store.fetchStats()
  }
}

onMounted(async () => {
  await Promise.all([store.fetchStats(), store.fetchDue(), store.fetchAll()])
  currentReview.value = store.due[0] || null
})
</script>

<style scoped>
.mistakes-view {
  min-height: 100vh;
  max-width: 720px;
  margin: 0 auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.back-btn {
  background: transparent;
  color: var(--text-secondary);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px 12px;
  cursor: pointer;
  font-size: 13px;
}

.page-title {
  font-size: 20px;
  font-weight: 700;
  flex: 1;
}

.header-spacer { width: 60px; }

/* Stats */
.stats-bar {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.stat {
  flex: 1;
  min-width: 60px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 10px;
  text-align: center;
}

.stat.total { background: rgba(74, 158, 255, 0.1); border-color: var(--accent); }

.stat-value { display: block; font-size: 20px; font-weight: 700; }
.stat-label { display: block; font-size: 11px; color: var(--text-secondary); margin-top: 2px; }

/* Tabs */
.tabs {
  display: flex;
  gap: 0;
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
}

.tabs button {
  flex: 1;
  padding: 10px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 14px;
}

.tabs button.active { background: var(--accent); color: white; }

/* Review card */
.review-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 20px;
}

.review-subject { font-size: 12px; color: var(--text-secondary); margin-bottom: 10px; }

.review-question {
  font-size: 17px;
  line-height: 1.6;
  margin-bottom: 16px;
  white-space: pre-wrap;
}

.reveal-btn {
  background: var(--accent);
  color: white;
  text-align: center;
  padding: 12px;
  border-radius: 10px;
  cursor: pointer;
  font-weight: 600;
}

.review-answer { display: flex; flex-direction: column; gap: 12px; margin-bottom: 16px; }

.answer-section {
  background: var(--bg-tertiary);
  border-radius: 10px;
  padding: 12px;
}

.answer-section.wrong { border: 1px solid #ff6b6b; }

.answer-label { font-size: 11px; color: var(--text-secondary); display: block; margin-bottom: 4px; }
.answer-content { white-space: pre-wrap; line-height: 1.5; }

.review-buttons {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.q-btn {
  flex: 1;
  min-width: 60px;
  padding: 10px 6px;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  color: white;
}

.q0 { background: #d44a4a; }
.q3 { background: #d49a4a; }
.q4 { background: #5a9fd4; }
.q5 { background: #4ad47a; }

/* List */
.mistake-list { display: flex; flex-direction: column; gap: 10px; }

.mistake-item {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px;
}

.mistake-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }

.subject-tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 6px;
  background: rgba(74, 158, 255, 0.15);
  color: var(--accent);
}

.status-tag { font-size: 11px; padding: 2px 8px; border-radius: 6px; }
.status-tag.learning { background: rgba(255, 107, 107, 0.15); color: #ff6b6b; }
.status-tag.reviewing { background: rgba(212, 154, 74, 0.15); color: #d49a4a; }
.status-tag.mastered { background: rgba(74, 212, 122, 0.15); color: #4ad47a; }

.delete-btn {
  margin-left: auto;
  color: var(--text-secondary);
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
}

.delete-btn:hover { color: #ff6b6b; }

.mistake-question { margin-bottom: 6px; line-height: 1.5; }
.mistake-answer { font-size: 13px; color: var(--text-secondary); margin-bottom: 8px; }
.mistake-meta { display: flex; gap: 12px; font-size: 11px; color: var(--text-secondary); }

/* Empty */
.empty-state {
  text-align: center;
  padding: 40px 20px;
  color: var(--text-secondary);
}

.empty-icon { font-size: 40px; display: block; margin-bottom: 10px; }
.empty-sub { font-size: 13px; margin-top: 6px; }
</style>
