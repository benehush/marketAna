<script setup lang="ts">
import { ref, onMounted } from 'vue'
import type { ArticleItem } from '../api/types'
import { getArticles } from '../api/client'
import ArticleCard from '../components/articles/ArticleCard.vue'
import LoadingState from '../components/common/LoadingState.vue'
import EmptyState from '../components/common/EmptyState.vue'
import ErrorState from '../components/common/ErrorState.vue'

const articles = ref<ArticleItem[]>([])
const loading = ref(true)
const error = ref('')

async function fetchData() {
  loading.value = true
  error.value = ''
  try {
    const res = await getArticles()
    if (res.code === 0) {
      articles.value = res.data
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
  <div class="articles-page">
    <div class="page-header">
      <h1 class="page-title">资讯</h1>
      <p class="page-desc">相关期货分析文章（点击标题可查看原文）</p>
    </div>

    <LoadingState v-if="loading" />
    <ErrorState v-else-if="error" :message="error" :on-retry="fetchData" />
    <EmptyState v-else-if="articles.length === 0" message="暂无资讯文章" />

    <div v-else class="article-list">
      <ArticleCard
        v-for="item in articles"
        :key="item.id"
        :article="item"
      />
    </div>
  </div>
</template>

<style scoped>
.articles-page {
  max-width: 800px;
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

.article-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
</style>
