<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { ArticleDetail, Direction, ProductCatalogItem, ReviewDiagnostic, ReviewQueueItem } from '../api/types'
import { articleSourceUrl, createManualConclusion, getArticleDetail, getProductCatalog, rejectReviewItem, runArticleTask } from '../api/client'
import LoadingState from '../components/common/LoadingState.vue'
import ErrorState from '../components/common/ErrorState.vue'

const route = useRoute(); const router = useRouter(); const articleId = computed(() => Number(route.params.id))
const detail = ref<ArticleDetail | null>(null); const catalog = ref<ProductCatalogItem[]>([])
const loading = ref(true); const error = ref(''); const articleBusy = ref(false); const showLogs = ref(route.query.logs === '1')
const reviewer = ref(localStorage.getItem('marketana_reviewer') || '')
const busy = ref<Record<number,string>>({}); const itemError = ref<Record<number,string>>({})
const openConclusion = ref<Record<number,boolean>>({}); const direction = ref<Record<number,Direction>>({})
const reason = ref<Record<number,string>>({}); const evidence = ref<Record<number,string>>({}); const productKey = ref<Record<number,string>>({})
const rejecting = ref<ReviewQueueItem | null>(null); const rejectionCode = ref('navigation_noise'); const rejectionNote = ref('')
const rejectionReasons = [
  ['navigation_noise','网页导航误识别'], ['not_futures_product','非期货品种'],
  ['no_analysis_content','无有效分析内容'], ['duplicate','重复审核项'], ['other','其他'],
]
const concreteCatalog = computed(() => catalog.value.filter(item => item.active && !item.product_key.startsWith('GROUP.')))

async function fetchData() {
  loading.value=true; error.value=''
  try { const [article, products] = await Promise.all([getArticleDetail(articleId.value), getProductCatalog()]); detail.value=article.data; catalog.value=products.data }
  catch(cause){ error.value=cause instanceof Error?cause.message:'详情加载失败' } finally { loading.value=false }
}
function saveReviewer(){ reviewer.value=reviewer.value.trim(); if(reviewer.value) localStorage.setItem('marketana_reviewer',reviewer.value); else localStorage.removeItem('marketana_reviewer') }
function goBack(){ router.push('/review-queue') }
function openSource(){ window.open(articleSourceUrl(articleId.value),'_blank','noopener') }
async function rerun(){ articleBusy.value=true; try{await runArticleTask(articleId.value);await fetchData()}catch(cause){error.value=cause instanceof Error?cause.message:'重新解析失败'}finally{articleBusy.value=false} }
function quotes(item:ReviewQueueItem):string[]{
  const value=item.evidence;if(!value)return[];if(typeof value==='string')return[value]
  const rows=Array.isArray(value)?value:(typeof value==='object'&&value&&Array.isArray((value as Record<string,unknown>).excerpts)?(value as Record<string,unknown>).excerpts as unknown[]:[])
  return rows.flatMap(row=>typeof row==='string'?[row]:row&&typeof row==='object'&&'quote' in row?[String((row as Record<string,unknown>).quote||'')]:[]).filter(Boolean)
}
function diagnostic(item:ReviewQueueItem):ReviewDiagnostic|null{
  if(!item.evidence||typeof item.evidence!=='object'||Array.isArray(item.evidence))return null
  const value=(item.evidence as Record<string,unknown>).diagnostic
  return value&&typeof value==='object'?value as ReviewDiagnostic:null
}
function evidenceKind(item:ReviewQueueItem):'verified'|'candidate_context'|null{
  if(!item.evidence||typeof item.evidence!=='object'||Array.isArray(item.evidence))return null
  const value=(item.evidence as Record<string,unknown>).kind
  return value==='verified'||value==='candidate_context'?value:null
}
function evidenceNotes(item:ReviewQueueItem):string{
  if(!item.evidence||typeof item.evidence!=='object'||Array.isArray(item.evidence))return''
  return String((item.evidence as Record<string,unknown>).notes||'')
}
function retrySummary(value:ReviewDiagnostic):string{
  const parts:string[]=[]
  if(value.transport_retry_count)parts.push(`传输重试 ${value.transport_retry_count} 次`)
  if(value.correction_retry_count)parts.push(`格式纠错 ${value.correction_retry_count} 次`)
  return parts.length?`已自动${parts.join('，')}，仍未通过。`:'该错误不满足自动重试条件。'
}
function beginConclusion(item:ReviewQueueItem){openConclusion.value[item.id]=true;direction.value[item.id]||='中性';productKey.value[item.id]||=item.product_key||''}
function complete(item:ReviewQueueItem){return !!reviewer.value.trim()&&!!productKey.value[item.id]&&!!direction.value[item.id]&&!!reason.value[item.id]?.trim()&&!!evidence.value[item.id]?.trim()}
async function submitConclusion(item:ReviewQueueItem){
  if(!complete(item))return;busy.value[item.id]='正在创建…';itemError.value[item.id]='';saveReviewer()
  try{await createManualConclusion(item.id,{product_key:productKey.value[item.id]||'',direction:direction.value[item.id]||'中性',reason:(reason.value[item.id]||'').trim(),evidence:(evidence.value[item.id]||'').trim(),reviewed_by:reviewer.value});await fetchData()}
  catch(cause){itemError.value[item.id]=cause instanceof Error?cause.message:'创建失败'}finally{delete busy.value[item.id]}
}
function beginReject(item:ReviewQueueItem){rejecting.value=item;rejectionCode.value='navigation_noise';rejectionNote.value=''}
async function confirmReject(){
  const item=rejecting.value;if(!item||!reviewer.value.trim())return;busy.value[item.id]='正在驳回…';saveReviewer()
  try{await rejectReviewItem(item.id,{reviewed_by:reviewer.value,reason_code:rejectionCode.value,note:rejectionNote.value.trim()||undefined});rejecting.value=null;await fetchData()}
  catch(cause){itemError.value[item.id]=cause instanceof Error?cause.message:'驳回失败'}finally{delete busy.value[item.id]}
}
function statusLabel(status:string){return status==='rejected'?'已驳回':status==='resolved'?'已创建人工结论':'待审核'}
onMounted(fetchData)
</script>

<template>
  <div class="detail-page">
    <button class="back" @click="goBack">← 返回审核队列</button>
    <LoadingState v-if="loading"/><ErrorState v-else-if="error" :message="error" :on-retry="fetchData"/>
    <template v-else-if="detail">
      <header class="article-header"><div><h1>{{ detail.article.title }}</h1><p>{{ detail.article.company||detail.article.source||'未知机构' }} · {{ detail.article.publish_time?.slice(0,10)||'发布日期未知' }}</p></div>
        <div class="article-actions"><button @click="openSource">查看原文</button><button :disabled="articleBusy" @click="rerun">{{articleBusy?'解析中…':'重新解析整篇'}}</button><button @click="showLogs=!showLogs">{{showLogs?'收起日志':'查看处理日志'}}</button></div>
      </header>
      <section v-if="showLogs" class="logs"><h2>处理日志</h2><div v-for="log in detail.task_logs" :key="log.id"><strong>{{log.stage}} · {{log.status}}</strong><span>{{log.created_at.slice(0,16).replace('T',' ')}}</span><p>{{log.message||'无详细信息'}}</p></div><p v-if="!detail.task_logs.length">暂无处理日志</p></section>
      <section v-if="detail.analysis_results.length" class="formal-results"><h2>正式分析结果</h2><article v-for="result in detail.analysis_results" :key="result.id"><strong>{{result.product}} · {{result.direction}}</strong><span>{{result.analysis_method==='manual'?'人工结论':result.analysis_method}}</span><p>{{result.reason||'暂无理由'}}</p></article></section>
      <section v-if="detail.review_queue?.length" class="review-section">
        <div class="section-heading"><div><h2>人工审核</h2><p>方向、标准品种、理由和证据完整后才会创建正式结果。</p></div><label>审核人<input v-model="reviewer" placeholder="请输入姓名" @change="saveReviewer"></label></div>
        <article v-for="(item,index) in detail.review_queue" :key="item.id" class="review-card">
          <div class="item-heading"><strong>#{{index+1}} {{item.product||item.product_key||'未识别品种'}}</strong><span :class="`status-${item.status}`">{{statusLabel(item.status)}}</span></div>
          <p>触发原因：{{item.reason_label||item.reason}}</p>
          <div v-if="diagnostic(item)" class="diagnostic-summary">
            <p><strong>具体原因：</strong>{{diagnostic(item)?.message}} <code>{{diagnostic(item)?.error_type}}</code></p>
            <p>{{retrySummary(diagnostic(item)!)}}</p>
            <details><summary>诊断详情</summary>
              <dl><dt>服务商</dt><dd>{{diagnostic(item)?.provider||'未知'}}</dd><dt>请求尝试</dt><dd>{{diagnostic(item)?.attempt_count}} 次</dd>
                <template v-if="diagnostic(item)?.http_status!==undefined"><dt>HTTP 状态</dt><dd>{{diagnostic(item)?.http_status}}</dd></template>
                <template v-if="diagnostic(item)?.content_type"><dt>Content-Type</dt><dd>{{diagnostic(item)?.content_type}}</dd></template>
                <template v-if="diagnostic(item)?.sse_line_count!==undefined"><dt>SSE 行数</dt><dd>{{diagnostic(item)?.sse_line_count}}</dd><dt>收到 [DONE]</dt><dd>{{diagnostic(item)?.done_received?'是':'否'}}</dd></template>
              </dl>
              <ul v-if="diagnostic(item)?.parse_errors?.length"><li v-for="(failure,i) in diagnostic(item)?.parse_errors" :key="i">{{failure.phase==='correction'?'纠错返回':'初次返回'}} · {{failure.message}}</li></ul>
              <div v-if="diagnostic(item)?.raw_response_excerpt"><strong>响应片段</strong><pre>{{diagnostic(item)?.raw_response_excerpt}}</pre></div>
              <div v-if="diagnostic(item)?.sse_event_samples?.length"><strong>SSE 事件样本</strong><pre v-for="(sample,i) in diagnostic(item)?.sse_event_samples" :key="i">{{sample}}</pre></div>
            </details>
          </div>
          <div class="evidence-box"><strong>{{evidenceKind(item)==='candidate_context'?'待核对原文上下文':'触发证据'}}</strong><small v-if="evidenceNotes(item)">{{evidenceNotes(item)}}</small><blockquote v-for="(quote,i) in quotes(item)" :key="i">{{quote}}</blockquote><em v-if="!quotes(item).length">暂无有效触发证据</em></div>
          <div v-if="item.status==='pending'" class="item-actions"><button class="danger" :disabled="!!busy[item.id]" @click="beginReject(item)">误识别/驳回</button><button class="primary" :disabled="!!busy[item.id]" @click="beginConclusion(item)">创建人工结论</button><span>{{busy[item.id]}}</span></div>
          <form v-if="item.status==='pending'&&openConclusion[item.id]" class="conclusion-form" @submit.prevent="submitConclusion(item)">
            <label>标准品种<select v-model="productKey[item.id]" required><option value="">请选择</option><option v-for="product in concreteCatalog" :key="product.product_key" :value="product.product_key">{{product.display_name}} · {{product.exchange}} {{product.symbol}}</option></select></label>
            <label>方向<select v-model="direction[item.id]" required><option>看涨</option><option>看跌</option><option>中性</option></select></label>
            <label>理由<textarea v-model="reason[item.id]" required rows="3"/></label><label>证据<textarea v-model="evidence[item.id]" required rows="4"/></label>
            <div class="form-actions"><button type="button" @click="openConclusion[item.id]=false">取消</button><button class="primary" :disabled="!complete(item)||!!busy[item.id]">创建正式结果</button></div>
          </form><p v-if="itemError[item.id]" class="error">{{itemError[item.id]}}</p>
        </article>
      </section><section v-else class="empty">该文章当前没有审核项。</section>
    </template>
    <div v-if="rejecting" class="modal-backdrop" @click.self="rejecting=null"><form class="modal" @submit.prevent="confirmReject"><h2>确定驳回该识别项吗？</h2><p>驳回后流水线重跑不会重新进入待审核。</p><label>驳回原因<select v-model="rejectionCode" required><option v-for="row in rejectionReasons" :key="row[0]" :value="row[0]">{{row[1]}}</option></select></label><label>补充说明<textarea v-model="rejectionNote" rows="3"/></label><p v-if="!reviewer.trim()" class="error">请先填写审核人姓名。</p><div class="form-actions"><button type="button" @click="rejecting=null">取消</button><button class="danger" :disabled="!reviewer.trim()">确认驳回</button></div></form></div>
  </div>
</template>

<style scoped>
.detail-page{max-width:960px}.back{background:none;border:1px solid #ccd3dc;border-radius:5px;color:#56616e;cursor:pointer;margin-bottom:16px;padding:6px 12px}.article-header,.section-heading,.item-heading{align-items:flex-start;display:flex;justify-content:space-between;gap:16px}.article-header{background:#fff;border-radius:10px;padding:20px}.article-header h1{color:#17192d;font-size:22px}.article-header p,.section-heading p{color:#87909b;margin-top:5px}.article-actions,.item-actions,.form-actions{display:flex;flex-wrap:wrap;gap:8px}.article-actions button,.item-actions button,.form-actions button{background:#fff;border:1px solid #cbd2dc;border-radius:5px;cursor:pointer;padding:6px 11px}.logs,.formal-results,.review-section,.empty{background:#fff;border:1px solid #e5e8ec;border-radius:10px;margin-top:14px;padding:18px}.logs h2,.formal-results h2,.review-section h2{font-size:18px}.logs>div,.formal-results article{border-top:1px solid #edf0f3;margin-top:10px;padding-top:10px}.logs span,.formal-results span{color:#8a919a;font-size:12px;margin-left:10px}.review-card{border:1px solid #e3e7ec;border-radius:8px;margin-top:12px;padding:15px}.item-heading span{border-radius:999px;font-size:12px;padding:3px 9px}.status-pending{background:#fff3d6;color:#946200}.status-rejected{background:#f0f1f3;color:#68717c}.status-resolved{background:#e4f6e9;color:#26733b}.review-card>p{color:#5a6470;margin:8px 0}.diagnostic-summary{background:#fff5f3;border:1px solid #efcbc6;border-radius:6px;color:#693730;margin:8px 0;padding:10px}.diagnostic-summary p{margin:0 0 5px}.diagnostic-summary code{background:#f7ded9;border-radius:4px;font-size:12px;padding:2px 5px}.diagnostic-summary summary{cursor:pointer;font-weight:600}.diagnostic-summary dl{display:grid;grid-template-columns:max-content 1fr;gap:4px 10px;margin:8px 0}.diagnostic-summary dt{font-weight:600}.diagnostic-summary dd{margin:0;word-break:break-all}.diagnostic-summary ul{padding-left:20px}.diagnostic-summary pre{background:#2c3038;border-radius:5px;color:#eef1f5;margin:5px 0;max-height:180px;overflow:auto;padding:8px;white-space:pre-wrap;word-break:break-all}.evidence-box{background:#f7f8fa;border-radius:6px;padding:10px}.evidence-box small{color:#7b8490;display:block;margin-top:4px}.evidence-box blockquote{border-left:3px solid #9eacc0;margin-top:7px;padding-left:9px}.evidence-box em{color:#946200;display:block;margin-top:5px}.item-actions{margin-top:10px}.primary{background:#2367d1!important;border-color:#2367d1!important;color:#fff}.danger{border-color:#dcaaa5!important;color:#aa382e}.conclusion-form,.modal{display:grid;gap:10px}.conclusion-form{background:#f7f9fd;border-radius:7px;margin-top:12px;padding:13px}.conclusion-form label,.modal label,.section-heading label{display:grid;font-weight:600;gap:4px}.conclusion-form select,.conclusion-form textarea,.modal select,.modal textarea,.section-heading input{border:1px solid #cbd3de;border-radius:5px;font:inherit;padding:7px}.form-actions{justify-content:flex-end}.error{color:#ae352b!important}.modal-backdrop{align-items:center;background:rgba(20,24,35,.45);display:flex;inset:0;justify-content:center;position:fixed;z-index:20}.modal{background:#fff;border-radius:10px;max-width:460px;padding:22px;width:calc(100% - 32px)}.modal p{color:#68717c}@media(max-width:720px){.article-header,.section-heading{display:block}.article-actions{margin-top:12px}}
</style>
