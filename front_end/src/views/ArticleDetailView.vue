<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { ArticleDetail, Direction, AnalysisResultItem } from '../api/types'
import { getArticleDetail } from '../api/client'
import { DIRECTION_CONFIG } from '../api/types'
import LoadingState from '../components/common/LoadingState.vue'
import ErrorState from '../components/common/ErrorState.vue'

const route = useRoute()
const router = useRouter()
const detail = ref<ArticleDetail | null>(null)
const loading = ref(true)
const error = ref('')
const showRawText = ref(false)

const articleId = computed(() => Number(route.params.id))
const activeProduct = computed(() => (route.query.product as string) || '')

// 所有分析结果
const allResults = computed(() =>
  detail.value?.analysis_results ?? (
    detail.value?.analysis_result ? [detail.value.analysis_result as unknown as AnalysisResultItem] : []
  )
)

// 当前聚焦品种的分析结果
const activeResult = computed(() => {
  if (!activeProduct.value) return allResults.value[0] ?? null
  return allResults.value.find((r) => r.product === activeProduct.value) ?? allResults.value[0] ?? null
})

const displayText = computed(() => detail.value?.text?.refined_text || detail.value?.text?.cleaned_text || '')

// 其他品种（本研报还覆盖）
const otherResults = computed(() =>
  allResults.value.filter((r) => r.product !== activeResult.value?.product)
)

function dirCfg(direction: string) {
  return DIRECTION_CONFIG[direction as Direction]
}

function methodLabel(method: string): string {
  if (method === 'rule') return '规则引擎'
  if (method === 'llm') return '大模型'
  if (method === 'manual') return '人工'
  return method
}

function sourceLabel(source: string): string {
  if (source === 'cleaned_text') return '清洗文本'
  if (source === 'raw_text') return '原始文本'
  if (source === 'analysis_reason') return '分析理由'
  return source
}

function matchLabel(mt: string): string {
  if (mt === 'reason') return '理由匹配'
  if (mt === 'keyword') return '关键词匹配'
  if (mt === 'fallback') return '分析摘要'
  return mt
}

function switchProduct(product: string) {
  router.push({ query: { product } })
}

function goBack() {
  if (window.history.length > 1) {
    router.back()
  } else {
    router.push('/products')
  }
}

async function fetchData() {
  loading.value = true
  error.value = ''
  try {
    const res = await getArticleDetail(articleId.value)
    if (res.code === 0) {
      detail.value = res.data
    } else {
      error.value = res.message || '加载失败'
    }
  } catch (e) {
    error.value = '网络错误'
  } finally {
    loading.value = false
  }
}

onMounted(fetchData)
</script>

<template>
  <div class="detail-page">
    <button class="back-btn" @click="goBack">← 返回</button>

    <LoadingState v-if="loading" />
    <ErrorState v-else-if="error" :message="error" :on-retry="fetchData" />

    <template v-else-if="detail && activeResult">
      <!-- 研报标题 -->
      <div class="article-header">
        <h1 class="article-title">{{ detail.article.title }}</h1>
        <div class="article-meta">
          <span>{{ detail.article.source || '未知来源' }}</span>
          <span class="meta-divider">/</span>
          <span>{{ detail.article.company || '未知公司' }}</span>
          <span class="meta-divider">/</span>
          <span>{{ detail.article.publish_time?.slice(0, 10) || '未知日期' }}</span>
        </div>
      </div>

      <!-- 当前品种观点摘要（核心卡片） -->
      <div class="focus-card">
        <div class="focus-top">
          <span class="focus-product">{{ activeResult.product }}</span>
          <span
            v-if="dirCfg(activeResult.direction)"
            class="focus-direction"
            :style="{ background: dirCfg(activeResult.direction).bgColor, color: dirCfg(activeResult.direction).color }"
          >
            {{ activeResult.direction }}
          </span>
          <span
            class="focus-confidence"
            :class="activeResult.confidence >= 0.5 ? 'conf-high' : 'conf-low'"
          >
            {{ (activeResult.confidence * 100).toFixed(0) }}%
          </span>
          <span class="focus-method">{{ methodLabel(activeResult.analysis_method) }}</span>
          <span v-if="activeResult.need_manual_review" class="focus-review">待人工确认</span>
        </div>

        <p class="focus-reason">{{ activeResult.reason || activeResult.evidence?.summary || '暂无理由' }}</p>

        <!-- 结论依据 -->
        <div v-if="activeResult.evidence || activeResult.reason" class="evidence-section">
          <h3 class="evidence-heading">结论依据</h3>

          <div v-if="activeResult.evidence?.excerpts?.length" class="excerpt-list">
            <figure
              v-for="(excerpt, i) in activeResult.evidence.excerpts.slice(0, 3)"
              :key="i"
              class="excerpt-item"
            >
              <blockquote>{{ excerpt.quote }}</blockquote>
              <figcaption>
                <span>{{ sourceLabel(excerpt.source) }}</span>
                <span>{{ matchLabel(excerpt.match_type) }}</span>
              </figcaption>
            </figure>
          </div>

          <p v-if="activeResult.evidence?.notes" class="evidence-note">
            {{ activeResult.evidence.notes }}
          </p>
        </div>
      </div>

      <!-- 本研报还覆盖 -->
      <div v-if="otherResults.length" class="other-section">
        <h3 class="other-heading">本研报还覆盖</h3>
        <div class="other-list">
          <button
            v-for="result in otherResults"
            :key="result.product + (result.contract ?? '')"
            class="other-chip"
            @click="switchProduct(result.product)"
          >
            <span class="other-product">{{ result.product }}</span>
            <span
              v-if="dirCfg(result.direction)"
              class="other-direction"
              :style="{ color: dirCfg(result.direction).color }"
            >
              {{ result.direction }}
            </span>
            <span class="other-confidence" :class="result.confidence >= 0.5 ? 'conf-high' : 'conf-low'">
              {{ (result.confidence * 100).toFixed(0) }}%
            </span>
          </button>
        </div>
      </div>

      <!-- 完整研报文本（折叠） -->
      <div v-if="displayText || detail.text?.raw_text" class="raw-section">
        <button class="raw-toggle" @click="showRawText = !showRawText">
          {{ showRawText ? '收起完整研报文本' : '查看完整研报文本' }}
          <span class="toggle-arrow">{{ showRawText ? '▲' : '▼' }}</span>
        </button>
        <div v-if="showRawText" class="raw-content">
          <p v-if="displayText" class="clean-text">{{ displayText }}</p>
          <pre v-if="detail.text?.raw_text" class="raw-text">{{ detail.text.raw_text }}</pre>
        </div>
      </div>
    </template>

    <!-- 无分析结果 -->
    <div v-else-if="detail && !allResults.length" class="empty-card">
      <p>暂无分析结果</p>
    </div>
  </div>
</template>

<style scoped>
.detail-page {
  max-width: 800px;
}

/* 返回按钮 */
.back-btn {
  background: none;
  border: 1px solid #ddd;
  border-radius: 6px;
  padding: 6px 14px;
  font-size: 13px;
  color: #666;
  cursor: pointer;
  margin-bottom: 16px;
  transition: all 0.15s;
}

.back-btn:hover {
  border-color: #e74c3c;
  color: #e74c3c;
}

/* 研报标题 */
.article-header {
  margin-bottom: 20px;
}

.article-title {
  font-size: 20px;
  font-weight: 700;
  color: #1a1a2e;
  margin: 0 0 8px;
  line-height: 1.4;
}

.article-meta {
  font-size: 13px;
  color: #888;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.meta-divider {
  color: #ddd;
}

/* 聚焦品种卡片 */
.focus-card {
  background: #fff;
  border-radius: 12px;
  padding: 20px 24px;
  border: 1px solid #f0f0f0;
  border-left: 4px solid #e74c3c;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  margin-bottom: 16px;
}

.focus-top {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 12px;
}

.focus-product {
  font-size: 22px;
  font-weight: 700;
  color: #1a1a2e;
}

.focus-direction {
  display: inline-block;
  padding: 3px 12px;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 700;
}

.focus-confidence {
  font-size: 18px;
  font-weight: 700;
}

.conf-high { color: #27ae60; }
.conf-low { color: #e74c3c; }

.focus-method {
  font-size: 12px;
  color: #999;
  background: #f5f6fa;
  padding: 2px 8px;
  border-radius: 4px;
}

.focus-review {
  font-size: 12px;
  font-weight: 600;
  color: #e74c3c;
  background: #fce8e6;
  padding: 2px 8px;
  border-radius: 4px;
}

.focus-reason {
  font-size: 15px;
  color: #333;
  line-height: 1.6;
  margin: 0 0 4px;
}

/* 结论依据 */
.evidence-section {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #f0f0f0;
}

.evidence-heading {
  font-size: 14px;
  font-weight: 600;
  color: #1a1a2e;
  margin: 0 0 12px;
}

.excerpt-list {
  display: grid;
  gap: 10px;
}

.excerpt-item {
  margin: 0;
  border-left: 3px solid #e74c3c;
  background: #fafafa;
  border-radius: 6px;
  padding: 10px 14px;
}

.excerpt-item blockquote {
  margin: 0;
  font-size: 13px;
  color: #333;
  line-height: 1.7;
}

.excerpt-item figcaption {
  display: flex;
  gap: 10px;
  margin-top: 6px;
  font-size: 12px;
  color: #999;
}

.evidence-note {
  margin: 10px 0 0;
  font-size: 12px;
  color: #888;
  line-height: 1.5;
}

/* 本研报还覆盖 */
.other-section {
  background: #fff;
  border-radius: 12px;
  padding: 16px 20px;
  border: 1px solid #f0f0f0;
  margin-bottom: 16px;
}

.other-heading {
  font-size: 14px;
  font-weight: 600;
  color: #555;
  margin: 0 0 12px;
}

.other-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.other-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #f8f9fa;
  border: 1px solid #e8eaed;
  border-radius: 8px;
  padding: 6px 12px;
  cursor: pointer;
  transition: all 0.15s;
  font-size: 13px;
}

.other-chip:hover {
  background: #f0f0f0;
  border-color: #ccc;
}

.other-product {
  font-weight: 600;
  color: #1a1a2e;
}

.other-direction {
  font-weight: 600;
  font-size: 12px;
}

.other-confidence {
  font-size: 12px;
  font-weight: 700;
}

/* 完整研报文本 */
.raw-section {
  background: #fff;
  border-radius: 12px;
  border: 1px solid #f0f0f0;
  margin-bottom: 16px;
}

.raw-toggle {
  width: 100%;
  background: none;
  border: none;
  padding: 14px 20px;
  font-size: 14px;
  font-weight: 600;
  color: #555;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;
  transition: background 0.15s;
  border-radius: 12px;
}

.raw-toggle:hover {
  background: #fafafa;
}

.toggle-arrow {
  font-size: 12px;
  color: #bbb;
}

.raw-content {
  padding: 0 20px 16px;
}

.clean-text {
  font-size: 14px;
  color: #333;
  line-height: 1.8;
  margin: 0 0 12px;
}

.raw-text {
  font-size: 13px;
  color: #555;
  line-height: 1.6;
  background: #f8f9fa;
  padding: 12px 16px;
  border-radius: 8px;
  white-space: pre-wrap;
  word-wrap: break-word;
  max-height: 400px;
  overflow-y: auto;
  margin: 0;
}

/* 空状态 */
.empty-card {
  background: #fff;
  border-radius: 12px;
  padding: 40px;
  text-align: center;
  color: #999;
  font-size: 14px;
}
</style>
