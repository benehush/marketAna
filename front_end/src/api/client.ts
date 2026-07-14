import type { ApiResponse } from './types'
import type {
  ProductItem,
  CompanyItem,
  HeatmapData,
  ArticleDetail,
  AnalysisResultDetail,
  ProductCatalogItem,
  ReviewQueueResponse,
} from './types'

// 把 ../mock/products.json 这个 JSON 文件当成一个模块导入，并赋值给变量 productsMock。
import productsMock from '../mock/products.json'
import companiesMock from '../mock/companies.json'
import trendsMock from '../mock/trends.json'
import articleDetailMock from '../mock/article_detail.json'

// 切换开关：true = 使用 mock 数据，false = 调用真实后端
const USE_MOCK = false

// 真实后端基础地址
const API_BASE = 'http://localhost:8000'

async function fetchMock<T>(mockData: ApiResponse<T>): Promise<ApiResponse<T>> {
  // 模拟网络延迟
  await new Promise((r) => setTimeout(r, 300))
  return mockData
}

async function fetchApi<T>(url: string): Promise<ApiResponse<T>> {
  const res = await fetch(`${API_BASE}${url}`)
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${res.statusText}`)
  }
  return res.json()
}

async function postApi<T>(url: string, body: object = {}): Promise<ApiResponse<T>> {
  const res = await fetch(`${API_BASE}${url}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const payload = await res.json()
  if (!res.ok) {
    throw new Error(payload?.message || `HTTP ${res.status}: ${res.statusText}`)
  }
  return payload
}

// ===== API 接口 =====

export async function getProducts(): Promise<ApiResponse<ProductItem[]>> {
  if (USE_MOCK) return fetchMock(productsMock as ApiResponse<ProductItem[]>)
  return fetchApi('/api/products')
}

export async function getCompanies(): Promise<ApiResponse<CompanyItem[]>> {
  if (USE_MOCK) return fetchMock(companiesMock as ApiResponse<CompanyItem[]>)
  return fetchApi('/api/companies')
}

export async function getTrends(): Promise<ApiResponse<HeatmapData[]>> {
  if (USE_MOCK) return fetchMock(trendsMock as ApiResponse<HeatmapData[]>)
  return fetchApi('/api/trends')
}

export function getReviewQueue(params: URLSearchParams): Promise<ApiResponse<ReviewQueueResponse>> {
  return fetchApi(`/api/review-queue?${params.toString()}`)
}

export async function getArticleDetail(id: number): Promise<ApiResponse<ArticleDetail>> {
  if (USE_MOCK) return fetchMock(articleDetailMock as ApiResponse<ArticleDetail>)
  return fetchApi(`/api/articles/${id}`)
}

export function getAnalysisResult(resultId: number): Promise<ApiResponse<AnalysisResultDetail>> {
  return fetchApi(`/api/results/${resultId}`)
}

export function runArticleTask(articleId: number): Promise<ApiResponse<Record<string, unknown>>> {
  return postApi('/api/tasks/run', { article_id: articleId })
}

export function rejectReviewItem(
  reviewId: number,
  payload: { reviewed_by: string; reason_code: string; note?: string },
): Promise<ApiResponse<{ id: number; status: string }>> {
  return postApi(`/api/review-items/${reviewId}/reject`, payload)
}

export function createManualConclusion(
  reviewId: number,
  payload: { direction: string; reason: string; evidence: string; product_key: string; reviewed_by: string },
): Promise<ApiResponse<Record<string, unknown>>> {
  return postApi(`/api/review-items/${reviewId}/conclusion`, payload)
}

export function getProductCatalog(): Promise<ApiResponse<ProductCatalogItem[]>> {
  return fetchApi('/api/product-catalog')
}

export function articleSourceUrl(articleId: number): string {
  return `${API_BASE}/api/articles/${articleId}/source`
}

export function confirmResult(
  resultId: number,
  payload: { product: string; product_key?: string; direction: string; reason?: string; confidence: number; confirmed_by?: string },
): Promise<ApiResponse<Record<string, unknown>>> {
  return postApi(`/api/results/${resultId}/confirm`, payload)
}
