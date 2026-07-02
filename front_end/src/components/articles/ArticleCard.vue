<script setup lang="ts">
import type { ArticleItem } from '../../api/types'

defineProps<{
  article: ArticleItem
}>()
</script>

<template>
  <div class="article-card">
    <h4 class="article-title">{{ article.title }}</h4>
    <div class="article-meta">
      <span class="article-source">来源：{{ article.source }}</span>
      <span class="article-date">{{ article.publish_time }}</span>
    </div>
    <p v-if="article.summary" class="article-summary">
      {{ article.summary }}
    </p>
  </div>
</template>

<style scoped>
.article-card {
  background: #fff;
  border-radius: 10px;
  padding: 16px 20px;
  border: 1px solid #f0f0f0;
  transition: box-shadow 0.2s;
}

.article-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

.article-title {
  font-size: 15px;
  font-weight: 600;
  color: #1a1a2e;
  margin: 0 0 8px;
  line-height: 1.4;
}

.article-meta {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: #999;
  margin-bottom: 8px;
}

.article-summary {
  font-size: 13px;
  color: #666;
  margin: 0;
  line-height: 1.5;
}
</style>
