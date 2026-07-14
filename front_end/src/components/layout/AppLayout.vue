<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import type { Direction } from '../../api/types'
import { getProducts } from '../../api/client'
import { DIRECTION_CONFIG } from '../../api/types'
import AppSidebar from './AppSidebar.vue'

interface SearchItem {
  result_id: number
  product: string
  direction: string
  confidence: number
  company: string
  date: string
  reason?: string
}

const router = useRouter()
const keyword = ref('')
const results = ref<SearchItem[]>([])
const showResults = ref(false)
const searching = ref(false)
let allItems: SearchItem[] = []

// 提前加载所有品种预测数据
getProducts().then((res) => {
  if (res.code === 0) {
    allItems = res.data.flatMap((p) =>
      p.predictions.map((pred) => ({
        result_id: pred.result_id,
        product: p.product,
        direction: pred.direction,
        confidence: pred.confidence,
        company: pred.company,
        date: pred.date,
        reason: pred.reason,
      }))
    )
  }
})

async function handleSearch() {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) {
    results.value = []
    showResults.value = false
    return
  }
  searching.value = true
  showResults.value = true

  // 前端本地筛选：按品种名、公司、理由匹配
  results.value = allItems.filter((p) => {
    return (
      p.product.toLowerCase().includes(kw) ||
      p.company.toLowerCase().includes(kw) ||
      (p.reason && p.reason.toLowerCase().includes(kw))
    )
  }).slice(0, 10)

  searching.value = false
}

function goToResult(resultId: number) {
  showResults.value = false
  keyword.value = ''
  results.value = []
  router.push(`/analysis-results/${resultId}?from=products`)
}

function handleBlur() {
  setTimeout(() => { showResults.value = false }, 200)
}

function getDirectionInfo(direction: string) {
  return DIRECTION_CONFIG[direction as Direction]
}

function confidenceColor(confidence: number): string {
  if (confidence >= 0.7) return '#27ae60'
  if (confidence >= 0.5) return '#f39c12'
  return '#e74c3c'
}
</script>

<template>
  <div class="app-layout">
    <AppSidebar />
    <main class="main-content">
      <router-view />
    </main>
    <aside class="right-panel">
      <div class="search-section">
        <div class="search-box">
          <span class="search-icon">🔍</span>
          <input
            v-model="keyword"
            type="text"
            class="search-input"
            placeholder="搜索品种、公司..."
            @input="handleSearch"
            @focus="showResults = results.length > 0"
            @blur="handleBlur"
          />
        </div>

        <div v-if="showResults" class="search-results">
          <div v-if="searching" class="search-hint">搜索中...</div>
          <div v-else-if="results.length === 0" class="search-hint">无匹配品种</div>
          <div
            v-for="(item, i) in results"
            :key="item.result_id || i"
            class="search-result-item"
            @mousedown.prevent="goToResult(item.result_id)"
          >
            <div class="result-top">
              <span class="result-product">{{ item.product }}</span>
              <span
                class="result-direction"
                :style="{ color: getDirectionInfo(item.direction)?.color }"
              >
                {{ item.direction }}
              </span>
              <span class="result-confidence" :style="{ color: confidenceColor(item.confidence) }">
                {{ (item.confidence * 100).toFixed(0) }}%
              </span>
            </div>
            <div class="result-meta">
              <span>{{ item.company }}</span>
              <span class="result-date">{{ item.date }}</span>
            </div>
          </div>
        </div>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.app-layout {
  display: flex;
  height: 100vh;
  background: #f5f6fa;
}

.main-content {
  flex: 1;
  overflow-y: auto;
  padding: 28px 32px;
  min-width: 0;
}

.right-panel {
  width: 260px;
  min-width: 260px;
  background: #fff;
  border-left: 1px solid #e8eaed;
  padding: 20px 16px;
  position: relative;
}

.search-section {
  position: relative;
}

.search-box {
  display: flex;
  align-items: center;
  border: 1px solid #ddd;
  border-radius: 8px;
  background: #f8f9fa;
  padding: 0 12px;
  transition: border-color 0.2s;
}

.search-box:focus-within {
  border-color: #e74c3c;
  background: #fff;
}

.search-icon {
  font-size: 14px;
  margin-right: 6px;
  flex-shrink: 0;
}

.search-input {
  flex: 1;
  border: none;
  background: none;
  padding: 10px 0;
  font-size: 13px;
  outline: none;
  color: #333;
  min-width: 0;
}

.search-input::placeholder {
  color: #bbb;
}

.search-results {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  margin-top: 6px;
  background: #fff;
  border: 1px solid #e8eaed;
  border-radius: 10px;
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.1);
  max-height: 400px;
  overflow-y: auto;
  z-index: 100;
}

.search-hint {
  padding: 16px;
  text-align: center;
  font-size: 13px;
  color: #999;
}

.search-result-item {
  padding: 10px 14px;
  cursor: pointer;
  border-bottom: 1px solid #f5f5f5;
  transition: background 0.1s;
}

.search-result-item:last-child {
  border-bottom: none;
}

.search-result-item:hover {
  background: #f8f9fa;
}

.result-top {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 3px;
}

.result-product {
  font-size: 14px;
  font-weight: 700;
  color: #1a1a2e;
}

.result-direction {
  font-size: 12px;
  font-weight: 600;
}

.result-confidence {
  font-size: 12px;
  font-weight: 700;
}

.result-meta {
  font-size: 11px;
  color: #aaa;
  display: flex;
  gap: 8px;
}

.result-date {
  color: #ccc;
}
</style>
