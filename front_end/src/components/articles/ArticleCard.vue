<script setup lang="ts">
import type { ReviewQueueArticle } from '../../api/types'

defineProps<{ article: ReviewQueueArticle; busy?: boolean }>()
defineEmits<{ rerun: [article: ReviewQueueArticle]; source: [article: ReviewQueueArticle] }>()
</script>

<template>
  <article class="queue-card">
    <div class="card-heading">
      <div>
        <router-link :to="`/articles/${article.id}`" class="article-title">{{ article.title }}</router-link>
        <div class="article-meta">
          <span>{{ article.company || '未知机构' }}</span>
          <span>{{ article.publish_time || '发布日期未知' }}</span>
          <span>{{ article.entered_at?.slice(0, 16).replace('T', ' ') || '入队时间未知' }}</span>
        </div>
      </div>
      <span class="status-pill" :class="`status-${article.status}`">
        {{ article.status === 'pending' ? `待审核 ${article.counts.pending} 项` : article.status === 'completed' ? '已完成' : article.status === 'rejected' ? '已驳回' : '处理异常' }}
      </span>
    </div>

    <div v-if="article.products.length" class="products">
      <span v-for="product in article.products" :key="product.product_key">{{ product.product }}</span>
    </div>
    <p class="reason">触发原因：{{ article.trigger_reason_label || article.latest_task?.message || '暂无' }}</p>
    <p v-if="article.evidence_excerpt && article.evidence_kind === 'candidate_context'" class="context-label">待核对原文上下文</p>
    <blockquote v-if="article.evidence_excerpt" class="evidence">{{ article.evidence_excerpt }}</blockquote>
    <p v-else class="missing-evidence">暂无有效触发证据</p>

    <div class="card-actions">
      <router-link class="primary" :to="`/articles/${article.id}`">进入审核</router-link>
      <button type="button" :disabled="busy" @click="$emit('rerun', article)">{{ busy ? '解析中…' : '重新解析整篇' }}</button>
      <button type="button" @click="$emit('source', article)">查看原文</button>
      <router-link :to="{ path: `/articles/${article.id}`, query: { logs: '1' } }">查看处理日志</router-link>
    </div>
  </article>
</template>

<style scoped>
.queue-card { background:#fff; border:1px solid #e5e8ec; border-radius:12px; padding:18px 20px; }
.card-heading { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; }
.article-title { color:#15172a; font-size:16px; font-weight:700; }
.article-meta { color:#8a919a; display:flex; flex-wrap:wrap; gap:14px; font-size:12px; margin-top:6px; }
.status-pill { border-radius:999px; flex:none; font-size:12px; font-weight:700; padding:4px 10px; }
.status-pending { background:#fff3d6; color:#946200; }.status-completed { background:#e4f6e9; color:#26733b; }
.status-rejected { background:#f0f1f3; color:#68717c; }.status-error { background:#fde7e5; color:#a8342a; }
.products { display:flex; flex-wrap:wrap; gap:6px; margin-top:13px; }
.products span { background:#edf3fc; border-radius:5px; color:#355d91; font-size:12px; padding:2px 8px; }
.reason { color:#4d5661; margin-top:12px; }
.context-label { color:#7b8490; font-size:12px; font-weight:600; margin-top:8px; }
.evidence { background:#f7f8fa; border-left:3px solid #9eacc0; color:#49515b; margin-top:8px; padding:9px 12px; }
.missing-evidence { background:#fff8ed; color:#946200; margin-top:8px; padding:9px 12px; }
.card-actions { display:flex; flex-wrap:wrap; gap:8px; margin-top:14px; }
.card-actions a,.card-actions button { background:#fff; border:1px solid #cdd4de; border-radius:5px; color:#38424f; cursor:pointer; font:inherit; padding:6px 11px; }
.card-actions .primary { background:#2367d1; border-color:#2367d1; color:#fff; }
.card-actions button:disabled { cursor:not-allowed; opacity:.55; }
</style>
