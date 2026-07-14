<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts'
import type { HeatmapData } from '../../api/types'

const props = defineProps<{
  data: HeatmapData[]
}>()

const chartRef = ref<HTMLDivElement>()
let chartInstance: echarts.ECharts | null = null

function buildOption() {
  // 提取所有日期和品种
  const dates = [...new Set(props.data.map((d) => d.date))].sort()
  const products = [...new Set(props.data.map((d) => d.product))]

  // 构建矩阵
  const matrix: number[][] = products.map(() => dates.map(() => 0))
  const valueMap = new Map<string, number>()
  for (const item of props.data) {
    valueMap.set(`${item.product}-${item.date}`, item.value)
  }
  for (let i = 0; i < products.length; i++) {
    const row = matrix[i]
    if (!row) continue
    for (let j = 0; j < dates.length; j++) {
      row[j] = valueMap.get(`${products[i]}-${dates[j]}`) ?? 0
    }
  }

  return {
    tooltip: {
      position: 'top',
      formatter: (params: any) => {
        const date = dates[params.value[0]]
        const product = products[params.value[1]]
        const val = params.value[2]
        const direction = val > 0 ? '看涨' : val < 0 ? '看跌' : '中性'
        return `${product}<br/>${date}<br/>方向：${direction}<br/>强度：${Math.abs(val).toFixed(2)}`
      },
    },
    grid: {
      left: '10%',
      right: '4%',
      bottom: '12%',
      top: '4%',
      containLabel: true,
    },
    xAxis: {
      type: 'category',
      data: dates,
      splitArea: { show: true },
      axisLabel: {
        rotate: 45,
        fontSize: 11,
        color: '#666',
      },
    },
    yAxis: {
      type: 'category',
      data: products,
      splitArea: { show: true },
      axisLabel: {
        fontSize: 12,
        fontWeight: 600,
        color: '#333',
      },
    },
    visualMap: {
      min: -1,
      max: 1,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
      inRange: {
        color: ['#27ae60', '#f0f0f0', '#e74c3c'],
      },
      text: ['看涨', '看跌'],
      textStyle: { color: '#666', fontSize: 12 },
    },
    series: [
      {
        type: 'heatmap',
        data: matrix.flatMap((row, i) =>
          // ECharts heatmap data uses [xAxisIndex, yAxisIndex, value].
          row.map((val, j) => [j, i, val])
        ),
        label: {
          show: true,
          formatter: (params: any) => {
            const val = params.value[2]
            if (val === 0) return '稳'
            return val > 0 ? '涨' : '跌'
          },
          fontSize: 11,
          fontWeight: 600,
        },
        emphasis: {
          itemStyle: {
            shadowBlur: 10,
            shadowColor: 'rgba(0, 0, 0, 0.15)',
          },
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
  <div ref="chartRef" class="heatmap-chart"></div>
</template>

<style scoped>
.heatmap-chart {
  width: 100%;
  height: 480px;
  background: #fff;
  border-radius: 12px;
  padding: 8px;
  border: 1px solid #f0f0f0;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}
</style>
