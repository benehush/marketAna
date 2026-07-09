<script setup lang="ts">
import { ref, onMounted } from 'vue'
import type { ProductItem } from '../api/types'
import { getProducts } from '../api/client'
import ProductCard from '../components/products/ProductCard.vue'
import LoadingState from '../components/common/LoadingState.vue'
import EmptyState from '../components/common/EmptyState.vue'
import ErrorState from '../components/common/ErrorState.vue'

const products = ref<ProductItem[]>([])
const loading = ref(true)
const error = ref('')

async function fetchData() {
  loading.value = true
  error.value = ''
  try {
    const res = await getProducts()
    if (res.code === 0) {
      products.value = res.data
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
  <div class="products-page">
    <div class="page-header">
      <h1 class="page-title">品种</h1>
      <p class="page-desc">各期货品种的预测观点，点击卡片展开详情</p>
    </div>

    <LoadingState v-if="loading" />
    <ErrorState v-else-if="error" :message="error" :on-retry="fetchData" />
    <EmptyState v-else-if="products.length === 0" message="暂无品种数据" />

    <div v-else class="card-grid">
      <ProductCard
        v-for="item in products"
        :key="item.product"
        :product="item"
      />
    </div>
  </div>
</template>

<style scoped>
.products-page {
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
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}
</style>
