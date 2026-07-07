<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import type { CompanyItem, Direction } from '../../api/types'
import { DIRECTION_CONFIG } from '../../api/types'

const router = useRouter()
const props = defineProps<{
  company: CompanyItem
}>()

const expanded = ref(false)

function getDirectionInfo(direction: Direction) {
  return DIRECTION_CONFIG[direction]
}

function confidenceColor(confidence: number): string {
  if (confidence >= 0.7) return '#27ae60'
  if (confidence >= 0.5) return '#f39c12'
  return '#e74c3c'
}

function goToArticle(articleId: number) {
  router.push(`/articles/${articleId}`)
}
</script>

<template>
  <div class="company-card" @click="expanded = !expanded">
    <div class="card-header">
      <div class="company-icon">{{ company.company.slice(0, 2) }}</div>
      <div class="company-info">
        <h3 class="company-name">{{ company.company }}</h3>
        <span class="company-count">{{ company.predictions.length }} 条预测</span>
      </div>
      <span class="expand-icon">{{ expanded ? '▲' : '▼' }}</span>
    </div>

    <Transition name="slide">
      <div v-if="expanded" class="card-body">
        <div
          v-for="(pred, i) in company.predictions"
          :key="i"
          class="prediction-row"
          @click.stop="goToArticle(pred.article_id)"
        >
          <span class="pred-product">{{ pred.product }}</span>
          <div class="pred-detail">
            <span
              class="pred-direction"
              :style="{
                background: getDirectionInfo(pred.direction).bgColor,
                color: getDirectionInfo(pred.direction).color,
              }"
            >
              {{ pred.direction }}
            </span>
            <span class="pred-confidence" :style="{ color: confidenceColor(pred.confidence) }">
              {{ (pred.confidence * 100).toFixed(0) }}%
            </span>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.company-card {
  background: #fff;
  border-radius: 12px;
  padding: 16px 20px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
  cursor: pointer;
  transition: box-shadow 0.2s;
  border: 1px solid #f0f0f0;
}

.company-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.card-header {
  display: flex;
  align-items: center;
  gap: 14px;
}

.company-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: #1a1a2e;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 700;
  flex-shrink: 0;
}

.company-info {
  flex: 1;
}

.company-name {
  font-size: 16px;
  font-weight: 600;
  color: #1a1a2e;
  margin: 0;
}

.company-count {
  font-size: 12px;
  color: #999;
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

.pred-product {
  font-size: 14px;
  font-weight: 500;
  color: #333;
}

.pred-detail {
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

.pred-confidence {
  font-size: 14px;
  font-weight: 700;
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
