<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import type { ProductItem, Direction } from '../../api/types'
import { DIRECTION_CONFIG } from '../../api/types'

const INITIAL_SHOW = 8

const router = useRouter()
const props = defineProps<{
  product: ProductItem
}>()

const expanded = ref(false)
const showAll = ref(false)

// 方向聚合计数
const summaryCounts = computed(() => {
  const counts: Record<string, number> = { '看涨': 0, '看跌': 0, '中性': 0 }
  for (const pred of props.product.predictions) {
    if (counts[pred.direction] !== undefined) {
      counts[pred.direction]++
    }
  }
  return counts
})

// 是否超过初始显示数
const hasMany = computed(() => props.product.predictions.length > INITIAL_SHOW)

// 当前显示的预测列表
const displayedPredictions = computed(() => {
  if (showAll.value) return props.product.predictions
  return props.product.predictions.slice(0, INITIAL_SHOW)
})

function getDirectionInfo(direction: Direction) {
  return DIRECTION_CONFIG[direction]
}

function confidenceColor(confidence: number): string {
  if (confidence >= 0.7) return '#27ae60'
  if (confidence >= 0.5) return '#f39c12'
  return '#e74c3c'
}

function goToResult(resultId: number) {
  router.push({ path: `/analysis-results/${resultId}`, query: { from: 'products' } })
}

function toggleExpand() {
  expanded.value = !expanded.value
  if (!expanded.value) showAll.value = false
}
</script>

<template>
  <div class="product-card" @click="toggleExpand">
    <div class="card-header">
      <h3 class="product-name">{{ product.product }}</h3>
      <div class="prediction-summary">
        <span
          v-for="[dir, count] in Object.entries(summaryCounts)"
          :key="dir"
          v-show="count > 0"
          class="summary-chip"
          :style="{
            background: getDirectionInfo(dir as Direction).bgColor,
            color: getDirectionInfo(dir as Direction).color,
          }"
        >
          {{ getDirectionInfo(dir as Direction).label }} × {{ count }}
        </span>
      </div>
      <span class="total-badge">{{ product.predictions.length }}条</span>
      <span class="expand-icon">{{ expanded ? '▲' : '▼' }}</span>
    </div>

    <Transition name="slide">
      <div v-if="expanded" class="card-body">
        <div
          v-for="pred in displayedPredictions"
          :key="pred.result_id"
          class="prediction-row"
          @click.stop="goToResult(pred.result_id)"
        >
          <div class="pred-left">
            <span
              class="pred-direction"
              :style="{
                background: getDirectionInfo(pred.direction).bgColor,
                color: getDirectionInfo(pred.direction).color,
              }"
            >
              {{ pred.direction }}
            </span>
            <span class="pred-company">{{ pred.company }}</span>
          </div>
          <div class="pred-right">
            <span class="pred-confidence" :style="{ color: confidenceColor(pred.confidence) }">
              {{ (pred.confidence * 100).toFixed(0) }}%
            </span>
            <span class="pred-date">{{ pred.date }}</span>
          </div>
        </div>

        <!-- 展开全部按钮 -->
        <button
          v-if="hasMany && !showAll"
          class="show-more-btn"
          @click.stop="showAll = true"
        >
          展开全部 {{ product.predictions.length }} 条预测 ▼
        </button>
        <button
          v-else-if="hasMany && showAll"
          class="show-more-btn"
          @click.stop="showAll = false"
        >
          收起至前 {{ INITIAL_SHOW }} 条 ▲
        </button>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.product-card {
  background: #fff;
  border-radius: 12px;
  padding: 16px 20px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
  cursor: pointer;
  transition: box-shadow 0.2s;
  border: 1px solid #f0f0f0;
}

.product-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.card-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.product-name {
  font-size: 18px;
  font-weight: 600;
  color: #1a1a2e;
  margin: 0;
  min-width: 72px;
}

.prediction-summary {
  flex: 1;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.summary-chip {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.total-badge {
  font-size: 11px;
  color: #aaa;
  background: #f5f6fa;
  padding: 2px 8px;
  border-radius: 10px;
  white-space: nowrap;
}

.expand-icon {
  font-size: 12px;
  color: #bbb;
}

.card-body {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid #f0f0f0;
}

.prediction-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 6px;
  cursor: pointer;
  border-radius: 6px;
  transition: background 0.15s;
}

.prediction-row:hover {
  background: #f5f6fa;
}

.prediction-row + .prediction-row {
  border-top: 1px solid #f8f8f8;
}

.pred-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.pred-direction {
  padding: 2px 10px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
}

.pred-company {
  font-size: 13px;
  color: #666;
}

.pred-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.pred-confidence {
  font-size: 14px;
  font-weight: 700;
}

.pred-date {
  font-size: 12px;
  color: #bbb;
}

.show-more-btn {
  width: 100%;
  background: #f8f9fa;
  border: 1px dashed #ddd;
  border-radius: 6px;
  padding: 8px;
  margin-top: 8px;
  font-size: 13px;
  color: #888;
  cursor: pointer;
  transition: all 0.15s;
}

.show-more-btn:hover {
  background: #f0f0f0;
  color: #555;
  border-color: #ccc;
}

.slide-enter-active,
.slide-leave-active {
  transition: all 0.2s ease;
}

.slide-enter-from,
.slide-leave-to {
  opacity: 0;
  max-height: 0;
}
</style>
