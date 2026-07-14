<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { articleSourceUrl, getAnalysisResult } from '../api/client'
import type { AnalysisResultDetail, Direction } from '../api/types'
import { DIRECTION_CONFIG } from '../api/types'
import ErrorState from '../components/common/ErrorState.vue'
import LoadingState from '../components/common/LoadingState.vue'

const route = useRoute()
const router = useRouter()
const detail = ref<AnalysisResultDetail | null>(null)
const loading = ref(true)
const error = ref('')

const resultId = computed(() => Number(route.params.id))
const returnTarget = computed(() => route.query.from === 'companies' ? '/companies' : '/products')
const returnLabel = computed(() => returnTarget.value === '/companies' ? '返回期货公司页' : '返回品种页')
const result = computed(() => detail.value?.result ?? null)
const article = computed(() => detail.value?.article ?? null)
const evidenceExcerpts = computed(() => result.value?.evidence?.excerpts.filter(item => item.quote.trim()) ?? [])
const visibleEvidenceSummary = computed(() => {
  const summary = result.value?.evidence?.summary?.trim()
  if (!summary) return ''
  const normalizedSummary = normalizeEvidenceText(summary)
  const duplicatesExcerpt = evidenceExcerpts.value.some(
    excerpt => normalizeEvidenceText(excerpt.quote) === normalizedSummary,
  )
  return duplicatesExcerpt ? '' : summary
})

const methodLabels: Record<AnalysisResultDetail['result']['analysis_method'], string> = {
  rule: '规则分析',
  llm: '大模型分析',
  manual: '人工分析',
}

function directionInfo(direction: Direction) {
  return DIRECTION_CONFIG[direction]
}

function formatDate(value: string | null | undefined) {
  return value ? value.slice(0, 10) : '发布日期未知'
}

function normalizeEvidenceText(value: string) {
  return value.replace(/\s+/g, '')
}

async function fetchData() {
  detail.value = null
  error.value = ''
  if (!Number.isInteger(resultId.value) || resultId.value <= 0) {
    loading.value = false
    error.value = '分析结果不存在或链接无效'
    return
  }

  loading.value = true
  try {
    const response = await getAnalysisResult(resultId.value)
    detail.value = response.data
  } catch (cause) {
    const message = cause instanceof Error ? cause.message : ''
    error.value = message.includes('404')
      ? '分析结果不存在或尚未形成正式结论'
      : '分析结果加载失败，请检查后端服务'
  } finally {
    loading.value = false
  }
}

function goBack() {
  router.push(returnTarget.value)
}

function openSource() {
  if (article.value?.has_source) {
    window.open(articleSourceUrl(article.value.id), '_blank', 'noopener')
  }
}

watch(resultId, fetchData, { immediate: true })
</script>

<template>
  <div class="result-page">
    <button class="back-button" @click="goBack">← {{ returnLabel }}</button>

    <LoadingState v-if="loading" message="正在加载分析结果..." />
    <ErrorState v-else-if="error" :message="error" :on-retry="fetchData" />

    <template v-else-if="result && article">
      <header class="result-header">
        <div>
          <p class="eyebrow">正式分析结果</p>
          <h1>{{ result.product }}</h1>
          <p v-if="result.contract" class="contract">{{ result.contract }}</p>
        </div>
        <div
          class="direction-badge"
          :style="{
            color: directionInfo(result.direction).color,
            background: directionInfo(result.direction).bgColor,
          }"
        >
          {{ result.direction }}
        </div>
      </header>

      <section class="summary-grid">
        <div class="summary-item">
          <span>置信度</span>
          <strong>{{ (result.confidence * 100).toFixed(0) }}%</strong>
        </div>
        <div class="summary-item">
          <span>期货公司</span>
          <strong>{{ article.company || article.source || '未知机构' }}</strong>
        </div>
        <div class="summary-item">
          <span>发布日期</span>
          <strong>{{ formatDate(article.publish_time) }}</strong>
        </div>
        <div class="summary-item">
          <span>分析方式</span>
          <strong>{{ methodLabels[result.analysis_method] }}</strong>
        </div>
      </section>

      <section class="content-card">
        <h2>分析理由</h2>
        <p class="reason">{{ result.reason || '暂无分析理由' }}</p>
      </section>

      <section class="content-card">
        <h2>结论证据</h2>
        <p v-if="visibleEvidenceSummary" class="evidence-summary">
          {{ visibleEvidenceSummary }}
        </p>
        <div v-if="evidenceExcerpts.length" class="evidence-list">
          <blockquote v-for="(excerpt, index) in evidenceExcerpts" :key="index">
            {{ excerpt.quote }}
          </blockquote>
        </div>
        <p v-else class="empty-evidence">暂无可展示的结论证据</p>
        <p v-if="result.evidence?.notes" class="evidence-notes">
          {{ result.evidence.notes }}
        </p>
      </section>

      <section class="source-card">
        <div>
          <h2>所属文章</h2>
          <p>{{ article.title }}</p>
        </div>
        <button v-if="article.has_source" class="primary-button" @click="openSource">查看原文</button>
        <span v-else class="source-unavailable">原文不可用</span>
      </section>
    </template>
  </div>
</template>

<style scoped>
.result-page {
  max-width: 960px;
}

.back-button {
  background: #fff;
  border: 1px solid #ccd3dc;
  border-radius: 6px;
  color: #56616e;
  cursor: pointer;
  margin-bottom: 16px;
  padding: 7px 13px;
}

.result-header,
.summary-grid,
.content-card,
.source-card {
  background: #fff;
  border: 1px solid #e5e8ec;
  border-radius: 12px;
}

.result-header {
  align-items: center;
  display: flex;
  justify-content: space-between;
  padding: 24px;
}

.eyebrow {
  color: #87909b;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: .08em;
  margin: 0 0 7px;
  text-transform: uppercase;
}

.result-header h1 {
  color: #17192d;
  font-size: 28px;
  margin: 0;
}

.contract {
  color: #6f7884;
  margin: 6px 0 0;
}

.direction-badge {
  border-radius: 8px;
  font-size: 18px;
  font-weight: 700;
  padding: 10px 18px;
}

.summary-grid {
  display: grid;
  gap: 0;
  grid-template-columns: repeat(4, 1fr);
  margin-top: 14px;
  overflow: hidden;
}

.summary-item {
  display: grid;
  gap: 7px;
  padding: 18px;
}

.summary-item + .summary-item {
  border-left: 1px solid #edf0f3;
}

.summary-item span {
  color: #8a929d;
  font-size: 12px;
}

.summary-item strong {
  color: #25283a;
  font-size: 15px;
}

.content-card,
.source-card {
  margin-top: 14px;
  padding: 20px;
}

.content-card h2,
.source-card h2 {
  color: #242739;
  font-size: 17px;
  margin: 0 0 12px;
}

.reason,
.evidence-summary,
.source-card p {
  color: #4f5966;
  line-height: 1.75;
  margin: 0;
  white-space: pre-wrap;
}

.evidence-summary {
  background: #f7f8fa;
  border-radius: 7px;
  padding: 11px 13px;
}

.evidence-list {
  display: grid;
  gap: 10px;
  margin-top: 12px;
}

.evidence-list blockquote {
  background: #fafbfc;
  border-left: 4px solid #7f91aa;
  color: #3f4956;
  line-height: 1.7;
  margin: 0;
  padding: 11px 14px;
}

.empty-evidence,
.evidence-notes,
.source-unavailable {
  color: #929aa5;
  font-size: 13px;
}

.evidence-notes {
  margin: 12px 0 0;
}

.source-card {
  align-items: center;
  display: flex;
  justify-content: space-between;
}

.source-card h2 {
  margin-bottom: 5px;
}

.primary-button {
  background: #2367d1;
  border: 1px solid #2367d1;
  border-radius: 6px;
  color: #fff;
  cursor: pointer;
  flex-shrink: 0;
  padding: 8px 15px;
}

@media (max-width: 760px) {
  .summary-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .summary-item + .summary-item {
    border-left: 0;
  }

  .summary-item:nth-child(even) {
    border-left: 1px solid #edf0f3;
  }

  .summary-item:nth-child(n + 3) {
    border-top: 1px solid #edf0f3;
  }
}

@media (max-width: 520px) {
  .result-header,
  .source-card {
    align-items: flex-start;
    gap: 16px;
  }

  .summary-grid {
    grid-template-columns: 1fr;
  }

  .summary-item:nth-child(n) {
    border-left: 0;
    border-top: 1px solid #edf0f3;
  }

  .summary-item:first-child {
    border-top: 0;
  }
}
</style>
