<script setup lang="ts">
import { ref, onMounted } from 'vue'
import type { HeatmapData } from '../api/types'
import { getTrends } from '../api/client'
import HeatmapChart from '../components/trends/HeatmapChart.vue'
import LoadingState from '../components/common/LoadingState.vue'
import EmptyState from '../components/common/EmptyState.vue'
import ErrorState from '../components/common/ErrorState.vue'

const trends = ref<HeatmapData[]>([])
const loading = ref(true)
const error = ref('')

async function fetchData() {
  loading.value = true
  error.value = ''
  try {
    const res = await getTrends()
    if (res.code === 0) {
      trends.value = res.data
    } else {
      error.value = res.message || '数据加载失败'
    }
  } catch (e) {
    error.value = '网络错误，请检查后端是否启动'
  } finally {
    loading.value = false
  }
}

onMounted(fetchData)
</script>

<template>
  <div class="trends-page">
    <div class="page-header">
      <h1 class="page-title">趋势分析</h1>
      <p class="page-desc">
        品种涨跌热力图 ·
        <span class="legend-red">红色=看涨</span> ·
        <span class="legend-green">绿色=看跌</span> ·
        <span class="legend-gray">灰色=中性</span>
      </p>
    </div>

    <LoadingState v-if="loading" />
    <ErrorState v-else-if="error" :message="error" :on-retry="fetchData" />
    <EmptyState v-else-if="trends.length === 0" message="暂无趋势数据" />

    <HeatmapChart v-else :data="trends" />
  </div>
</template>

<style scoped>
.trends-page {
  max-width: 1000px;
}

.page-header {
  margin-bottom: 24px;
}

.page-title {
  font-size: 24px;
  font-weight: 700;
  color: #1a1a2e;
  margin: 0 0 6px;
}

.page-desc {
  font-size: 13px;
  color: #999;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

.legend-red { color: #e74c3c; font-weight: 600; }
.legend-green { color: #27ae60; font-weight: 600; }
.legend-gray { color: #95a5a6; font-weight: 600; }
</style>
