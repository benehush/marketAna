<script setup lang="ts">
import { ref } from 'vue'
import type { ProductItem, Direction } from '../../api/types'
import { DIRECTION_CONFIG } from '../../api/types'

const props = defineProps<{
  product: ProductItem
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
</script>

<template>
  <div class="product-card" @click="expanded = !expanded">
    <div class="card-header">
      <h3 class="product-name">{{ product.product }}</h3>
      <div class="prediction-summary">
        <span
          v-for="(pred, i) in product.predictions"
          :key="i"
          class="direction-badge"
          :style="{
            background: getDirectionInfo(pred.direction).bgColor,
            color: getDirectionInfo(pred.direction).color,
          }"
        >
          {{ getDirectionInfo(pred.direction).label }}
        </span>
      </div>
      <span class="expand-icon">{{ expanded ? '▲' : '▼' }}</span>
    </div>

    <Transition name="slide">
      <div v-if="expanded" class="card-body">
        <div
          v-for="(pred, i) in product.predictions"
          :key="i"
          class="prediction-row"
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
  min-width: 80px;
}

.prediction-summary {
  flex: 1;
  display: flex;
  gap: 6px;
}

.direction-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
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
  padding: 8px 0;
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
