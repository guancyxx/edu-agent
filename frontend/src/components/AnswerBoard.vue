<template>
  <div class="answer-board">
    <!-- ── Question area (top) ── -->
    <div class="ab-section ab-question-area">
      <div class="ab-toolbar">
        <span class="ab-toolbar-label">题目</span>
        <button class="ab-mini-btn" @click="askAgent" :disabled="!question.trim()">
          💬 发给 AI 讲解
        </button>
        <button class="ab-mini-btn" @click="$emit('import-from-chat')" title="从聊天区导入最近题目">
          ⤵ 从对话导入
        </button>
        <button class="ab-mini-btn" v-if="question" @click="clearQuestion">清空</button>
      </div>
      <textarea
        v-if="editing"
        class="ab-answer-input"
        v-model="question"
        placeholder="在这里输入或粘贴题目…（也可拍照后在对话区让 AI 识别，再点「从对话导入」）"
        @blur="editing = false"
      ></textarea>
      <div
        v-else
        class="ab-question-empty"
        @click="editing = true"
        role="button"
        tabindex="0"
        @keydown.enter.prevent="editing = true"
      >
        <span class="big-icon">📝</span>
        <span>点击输入题目<br />或从对话中导入</span>
      </div>
      <div class="ab-question-content" v-if="!editing && question">{{ question }}</div>
    </div>

    <div class="ab-divider" title="拖动调整比例" v-show="showDivider"></div>

    <!-- ── Answer area (bottom) ── -->
    <div class="ab-section ab-answer-area">
      <div class="ab-toolbar">
        <span class="ab-toolbar-label">作答</span>
        <button class="ab-mini-btn" @click="askAgentCheck" :disabled="!question.trim() || !answer.trim()">
          ✅ 让 AI 判定
        </button>
      </div>
      <textarea
        v-if="!result"
        class="ab-answer-input"
        v-model="answer"
        placeholder="写下你的解答过程或答案…"
      ></textarea>
      <div class="ab-result" v-else>
        <div class="ab-result-card" :class="result.correct ? 'correct' : 'wrong'">
          <div class="ab-result-label">{{ result.correct ? '✓ 回答正确' : '✗ 需要再想想' }}</div>
          <div>{{ result.feedback }}</div>
          <div v-if="result.savedToMistakes" style="margin-top: 6px; font-size: 11px; color: var(--text-secondary);">
            已自动记入错题本，将按间隔复习计划安排复习。
          </div>
        </div>
        <button class="ab-mini-btn" @click="result = null">再答一次</button>
      </div>
      <div class="ab-submit-row">
        <span class="ab-hint">Enter 提交 · Shift+Enter 换行</span>
        <button
          class="ab-submit-btn"
          :disabled="!answer.trim() || !question.trim() || checking"
          @click="submit"
        >
          {{ checking ? '判定中…' : '提交答案' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const emit = defineEmits<{
  (e: 'ask-agent', payload: { message: string }): void
  (e: 'import-from-chat'): void
}>()

const question = ref('')
const answer = ref('')
const editing = ref(false)
const checking = ref(false)
const result = ref<null | { correct: boolean; feedback: string; savedToMistakes: boolean }>(null)
const showDivider = ref(true)

function setQuestion(text: string) {
  question.value = text.trim()
  editing.value = false
}

defineExpose({ setQuestion })

function clearQuestion() {
  question.value = ''
  answer.value = ''
  result.value = null
}

function askAgent() {
  emit('ask-agent', { message: `请给我讲解这道题：\n${question.value}` })
}

function askAgentCheck() {
  emit('ask-agent', {
    message: `我正在解这道题，请先不要给完整答案，指出我的思路哪里有问题：\n题目：${question.value}\n我的解答：${answer.value}`,
  })
}

async function submit() {
  if (!question.value.trim() || !answer.value.trim() || checking.value) return
  checking.value = true
  try {
    // Ask the backend (through chat agent) to judge; fall back to local check
    // on any error so the board is always usable.
    // TODO(backend): dedicated /api/practice/judge endpoint — currently reused
    // via the chat WS by the parent (ChatView wires ask-agent). Here we do the
    // optimistic local path + mistake notebook write.
    const token = localStorage.getItem('edu_token')
    let correct = false
    let feedback = ''
    let correctAnswer = ''
    let judged = false
    let saved = false
    try {
      const r = await fetch('http://localhost:8000/api/chat/judge', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          question: question.value,
          answer: answer.value,
          subject: 'math',
        }),
      })
      if (r.ok) {
        const data = await r.json()
        judged = true
        correct = !!data.correct
        feedback = data.feedback || ''
        correctAnswer = data.correct_answer || ''
        if (correctAnswer) feedback = `${feedback}（正确答案：${correctAnswer}）`
      }
    } catch { /* offline */ }

    if (!judged) {
      feedback = '暂时无法连接判定服务，请稍后重试。'
    }

    if (!correct) {
      try {
        const r = await fetch('http://localhost:8000/api/mistakes', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
          body: JSON.stringify({
            subject: 'math',
            question: question.value,
            student_answer: answer.value,
            explanation: feedback,
            source: 'answer_board',
          }),
        })
        saved = r.status === 201 || r.ok
      } catch { /* notebook offline */ }
    }

    result.value = { correct, feedback, savedToMistakes: saved }
  } finally {
    checking.value = false
  }
}
</script>
