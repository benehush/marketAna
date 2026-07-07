import type { ApiResponse } from './types'
import type {
  ProductItem,
  CompanyItem,
  HeatmapData,
  ArticleItem,
  ArticleDetail,
} from './types'

// 把 ../mock/products.json 这个 JSON 文件当成一个模块导入，并赋值给变量 productsMock。
import productsMock from '../mock/products.json'
import companiesMock from '../mock/companies.json'
import trendsMock from '../mock/trends.json'
import articlesMock from '../mock/articles.json'
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

export async function getArticles(): Promise<ApiResponse<ArticleItem[]>> {
  if (USE_MOCK) return fetchMock(articlesMock as ApiResponse<ArticleItem[]>)
  return fetchApi('/api/articles')
}

export async function getArticleDetail(id: number): Promise<ApiResponse<ArticleDetail>> {
  if (USE_MOCK) return fetchMock(articleDetailMock as ApiResponse<ArticleDetail>)
  return fetchApi(`/api/articles/${id}`)
}
