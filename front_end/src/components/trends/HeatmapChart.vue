<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts'
import type { HeatmapData } from '../../api/types'

const props = defineProps<{
  data: HeatmapData[]
}>()

const chartRef = ref<HTMLDivElement>()
let chartInstance: echarts.ECharts | null = null

// 提取所有品种并排序（按数据量降序）
const allProducts = computed(() => {
  const count = new Map<string, number>()
  for (const item of props.data) {
    count.set(item.product, (count.get(item.product) || 0) + 1)
  }
  return [...count.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([name]) => name)
})

const selectedProducts = ref<string[]>([])

// 默认选中前 5 个
watch(allProducts, (products) => {
  if (selectedProducts.length === 0 && products.length) {
    selectedProducts.value = products.slice(0, 5)
  }
}, { immediate: true })

const filteredDates = computed(() => {
  const dates = new Set<string>()
  for (const item of props.data) {
    if (selectedProducts.value.includes(item.product)) {
      dates.add(item.date)
    }
  }
  return [...dates].sort()
})

function toggleProduct(product: string) {
  const idx = selectedProducts.value.indexOf(product)
  if (idx !== -1) {
    if (selectedProducts.value.length <= 1) return // 至少保留一个
    selectedProducts.value.splice(idx, 1)
  } else {
    selectedProducts.value.push(product)
  }
}

function buildOption() {
  const dates = filteredDates.value
  const products = selectedProducts.value

  const valueMap = new Map<string, number>()
  for (const item of props.data) {
    valueMap.set(`${item.product}-${item.date}`, item.value)
  }

  const seriesData: number[][] = []
  for (let i = 0; i < products.length; i++) {
    for (let j = 0; j < dates.length; j++) {
      const val = valueMap.get(`${products[i]}-${dates[j]}`)
      if (val !== undefined && val !== 0) {
        seriesData.push([j, i, val])
      }
    }
  }

  return {
    tooltip: {
      position: 'top',
      backgroundColor: 'rgba(255,255,255,0.95)',
      borderColor: '#e8eaed',
      borderWidth: 1,
      textStyle: { color: '#333', fontSize: 13 },
      formatter: (params: any) => {
        const product = products[params.value[1]]
        const date = dates[params.value[0]]
        const val = params.value[2]
        const direction = val > 0.3 ? '看涨' : val < -0.3 ? '看跌' : '中性'
        const emoji = val > 0.3 ? '📈' : val < -0.3 ? '📉' : '➖'
        return `<strong style="font-size:14px">${product}</strong><br/>
                <span style="color:#888">${date}</span><br/>
                ${emoji} <strong>${direction}</strong> (强度: ${Math.abs(val).toFixed(2)})`
      },
    },
    grid: {
      left: '6%',
      right: '4%',
      bottom: '6%',
      top: '2%',
      containLabel: true,
    },
    xAxis: {
      type: 'category',
      data: dates,
      splitArea: { show: true, areaStyle: { color: ['#fafafa', '#f5f5f5'] } },
      axisLabel: {
        rotate: 40,
        fontSize: 11,
        color: '#777',
        fontWeight: 500,
      },
      axisLine: { lineStyle: { color: '#e0e0e0' } },
    },
    yAxis: {
      type: 'category',
      data: products,
      splitArea: { show: true, areaStyle: { color: ['#fafafa', '#f5f5f5'] } },
      axisLabel: { fontSize: 12, fontWeight: 700, color: '#333' },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    visualMap: {
      min: -1,
      max: 1,
      calculable: true,
      precision: 2,
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
      itemWidth: 14,
      itemHeight: 150,
      inRange: {
        color: ['#1a6b3c', '#27ae60', '#e8f5e9', '#fafafa', '#fce8e6', '#e74c3c', '#b03a2e'],
      },
      text: ['看跌 ↓', '看涨 ↑'],
      textStyle: { color: '#666', fontSize: 13, fontWeight: 600 },
    },
    series: [
      {
        type: 'heatmap',
        data: seriesData,
        label: {
          show: true,
          formatter: (params: any) => {
            const val = params.value[2]
            if (val === 0) return ''
            return val > 0 ? '涨' : '跌'
          },
          fontSize: 11,
          fontWeight: 700,
          color: '#333',
        },
        emphasis: {
          itemStyle: {
            shadowBlur: 8,
            shadowColor: 'rgba(0, 0, 0, 0.15)',
            borderWidth: 2,
            borderColor: '#fff',
          },
        },
        itemStyle: {
          borderRadius: 3,
          borderWidth: 1,
          borderColor: '#fff',
        },
      },
    ],
  }
}

function render() {
  if (!chartRef.value) return
  if (!chartInstance) {
    chartInstance = echarts.init(chartRef.value)
  }
  chartInstance.setOption(buildOption(), true)
}

function handleResize() {
  chartInstance?.resize()
}

watch(selectedProducts, render, { deep: true })

onMounted(() => {
  render()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  chartInstance?.dispose()
  chartInstance = null
})

watch(() => props.data, render, { deep: true })
</script>

<template>
  <div class="heatmap-wrapper">
    <!-- 品种选择器 -->
    <div class="product-selector">
      <span class="selector-label">品种筛选：</span>
      <div class="selector-tags">
        <button
          v-for="product in allProducts"
          :key="product"
          class="tag-btn"
          :class="{ active: selectedProducts.includes(product) }"
          @click="toggleProduct(product)"
        >
          {{ product }}
        </button>
      </div>
    </div>

    <div ref="chartRef" class="heatmap-chart"></div>

    <p class="chart-hint">
      点击上方品种标签切换显示 · X 轴=时间 · Y 轴=品种 · 红色=看涨 绿色=看跌
    </p>
  </div>
</template>

<style scoped>
.heatmap-wrapper {
  background: #fff;
  border-radius: 12px;
  border: 1px solid #f0f0f0;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
  padding: 20px 16px 8px;
}

.product-selector {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 16px;
}

.selector-label {
  font-size: 13px;
  color: #888;
  white-space: nowrap;
  margin-top: 4px;
}

.selector-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tag-btn {
  background: #f5f6fa;
  border: 1px solid #e0e0e0;
  border-radius: 6px;
  padding: 4px 12px;
  font-size: 12px;
  color: #666;
  cursor: pointer;
  transition: all 0.15s;
  font-weight: 500;
}

.tag-btn:hover {
  background: #e8eaed;
  border-color: #ccc;
}

.tag-btn.active {
  background: #1a1a2e;
  color: #fff;
  border-color: #1a1a2e;
}

.heatmap-chart {
  width: 100%;
  height: 420px;
}

.chart-hint {
  text-align: center;
  font-size: 12px;
  color: #ccc;
  margin: 8px 0 0;
}
</style>
