<script setup lang="ts">
import { ref, onMounted } from 'vue'
import type { CompanyItem } from '../api/types'
import { getCompanies } from '../api/client'
import CompanyCard from '../components/companies/CompanyCard.vue'
import LoadingState from '../components/common/LoadingState.vue'
import EmptyState from '../components/common/EmptyState.vue'
import ErrorState from '../components/common/ErrorState.vue'

const companies = ref<CompanyItem[]>([])
const loading = ref(true)
const error = ref('')

async function fetchData() {
  loading.value = true
  error.value = ''
  try {
    const res = await getCompanies()
    if (res.code === 0) {
      companies.value = res.data
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
  <div class="companies-page">
    <div class="page-header">
      <h1 class="page-title">期货公司</h1>
      <p class="page-desc">各期货公司对各品种的预测观点</p>
    </div>

    <LoadingState v-if="loading" />
    <ErrorState v-else-if="error" :message="error" :on-retry="fetchData" />
    <EmptyState v-else-if="companies.length === 0" message="暂无公司数据" />

    <div v-else class="card-grid">
      <CompanyCard
        v-for="item in companies"
        :key="item.company"
        :company="item"
      />
    </div>
  </div>
</template>

<style scoped>
.companies-page {
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
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 16px;
}
</style>
