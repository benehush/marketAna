<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { ReviewQueueArticle, ReviewQueueResponse, ReviewQueueTab } from '../api/types'
import { articleSourceUrl, getReviewQueue, runArticleTask } from '../api/client'
import ArticleCard from '../components/articles/ArticleCard.vue'
import LoadingState from '../components/common/LoadingState.vue'
import EmptyState from '../components/common/EmptyState.vue'
import ErrorState from '../components/common/ErrorState.vue'

const route = useRoute(); const router = useRouter()
const data = ref<ReviewQueueResponse | null>(null); const loading = ref(true); const error = ref('')
const busy = ref<Record<number, boolean>>({})
const tab = ref<ReviewQueueTab>((route.query.tab as ReviewQueueTab) || 'pending')
const keyword = ref(String(route.query.keyword || '')); const company = ref(String(route.query.company || ''))
const productKey = ref(String(route.query.product_key || '')); const reason = ref(String(route.query.reason || ''))
const missingEvidence = ref(route.query.missing_evidence === 'true'); const sort = ref(String(route.query.sort || 'pending_count'))
const page = ref(Number(route.query.page || 1)); const pageSize = 20

const tabs: Array<{ key: ReviewQueueTab; label: string }> = [
  { key:'pending', label:'待审核' }, { key:'completed', label:'已完成' },
  { key:'rejected', label:'已驳回' }, { key:'error', label:'处理异常' },
]
const totalPages = computed(() => Math.max(1, Math.ceil((data.value?.total || 0) / pageSize)))

function params() {
  const value = new URLSearchParams({ tab:tab.value, page:String(page.value), page_size:String(pageSize), sort:sort.value })
  if (keyword.value.trim()) value.set('keyword', keyword.value.trim())
  if (company.value) value.set('company', company.value)
  if (productKey.value) value.set('product_key', productKey.value)
  if (reason.value) value.set('reason', reason.value)
  if (missingEvidence.value) value.set('missing_evidence', 'true')
  return value
}
function syncUrl() { router.replace({ query: Object.fromEntries(params()) }) }
async function fetchData() {
  loading.value = true; error.value = ''
  try { const result = await getReviewQueue(params()); data.value = result.data; syncUrl() }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '审核队列加载失败' }
  finally { loading.value = false }
}
function changeTab(value: ReviewQueueTab) { tab.value = value; page.value = 1; fetchData() }
function applyFilters() { page.value = 1; fetchData() }
function clearFilters() { keyword.value=''; company.value=''; productKey.value=''; reason.value=''; missingEvidence.value=false; sort.value='pending_count'; applyFilters() }
async function rerun(article: ReviewQueueArticle) {
  busy.value[article.id] = true
  try { await runArticleTask(article.id); await fetchData() }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '重新解析失败' }
  finally { delete busy.value[article.id] }
}
function openSource(article: ReviewQueueArticle) { window.open(articleSourceUrl(article.id), '_blank', 'noopener') }
watch(() => route.query.tab, (value) => { if (value && value !== tab.value) { tab.value = value as ReviewQueueTab; fetchData() } })
onMounted(fetchData)
</script>

<template>
  <div class="queue-page">
    <header><h1>待审核研报</h1><p>处理未形成正式分析结论的研报及异常识别项</p></header>
    <nav class="tabs">
      <button v-for="item in tabs" :key="item.key" :class="{ active:tab===item.key }" @click="changeTab(item.key)">
        {{ item.label }} <span>{{ data?.counts[item.key] || 0 }}</span>
      </button>
    </nav>
    <form class="filters" @submit.prevent="applyFilters">
      <input v-model="keyword" placeholder="搜索期货公司或文章编号">
      <select v-model="company"><option value="">全部公司</option><option v-for="item in data?.filter_options.companies" :key="item">{{ item }}</option></select>
      <select v-model="productKey"><option value="">全部候选品种</option><option v-for="item in data?.filter_options.products" :key="item.product_key" :value="item.product_key">{{ item.product }}</option></select>
      <select v-model="reason"><option value="">全部触发原因</option><option v-for="item in data?.filter_options.reasons" :key="item.reason" :value="item.reason">{{ item.label }}</option></select>
      <select v-model="sort"><option value="pending_count">待审核项数量</option><option value="oldest">最早入队</option><option value="newest">最近更新</option></select>
      <label><input v-model="missingEvidence" type="checkbox"> 只看无证据项</label>
      <button class="apply" type="submit">筛选</button><button type="button" @click="clearFilters">清空</button>
    </form>
    <LoadingState v-if="loading" />
    <ErrorState v-else-if="error" :message="error" :on-retry="fetchData" />
    <EmptyState v-else-if="!data?.items.length" message="当前没有符合条件的审核文章" />
    <div v-else class="queue-list"><ArticleCard v-for="item in data.items" :key="item.id" :article="item" :busy="busy[item.id]" @rerun="rerun" @source="openSource" /></div>
    <footer v-if="data && data.total > pageSize" class="pagination">
      <button :disabled="page<=1" @click="page--; fetchData()">上一页</button><span>{{ page }} / {{ totalPages }}</span><button :disabled="page>=totalPages" @click="page++; fetchData()">下一页</button>
    </footer>
  </div>
</template>

<style scoped>
.queue-page { max-width:1080px; }.queue-page header { margin-bottom:18px; }.queue-page h1 { color:#16182c; font-size:26px; }.queue-page header p { color:#8a919a; margin-top:4px; }
.tabs { border-bottom:1px solid #dfe3e8; display:flex; gap:24px; }.tabs button { background:none; border:0; border-bottom:2px solid transparent; color:#65707c; cursor:pointer; font:inherit; font-weight:600; padding:10px 2px; }.tabs button.active { border-color:#2367d1; color:#2367d1; }.tabs span { background:#edf0f4; border-radius:999px; font-size:11px; margin-left:3px; padding:1px 6px; }
.filters { align-items:center; background:#fff; border:1px solid #e5e8ec; border-radius:9px; display:flex; flex-wrap:wrap; gap:8px; margin:16px 0; padding:12px; }.filters input,.filters select,.filters button { border:1px solid #cfd5dd; border-radius:5px; font:inherit; min-height:34px; padding:5px 8px; }.filters>input { min-width:220px; }.filters label { align-items:center; color:#59636f; display:flex; gap:5px; }.filters label input { min-height:auto; }.filters button { background:#fff; cursor:pointer; }.filters .apply { background:#2367d1; border-color:#2367d1; color:#fff; }
.queue-list { display:grid; gap:12px; }.pagination { align-items:center; display:flex; gap:12px; justify-content:center; margin-top:18px; }.pagination button { padding:6px 12px; }
@media (max-width:720px){.filters>*{width:100%}.card-heading{display:block}}
</style>
