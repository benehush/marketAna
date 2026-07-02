// ===== 后端统一响应格式 =====
export interface ApiResponse<T> {
  code: number
  message: string
  data: T
}

// ===== 方向枚举 =====
export type Direction = '看涨' | '看跌' | '中性'

// ===== 单条预测 =====
export interface Prediction {
  direction: Direction
  confidence: number
  company: string
  date: string
  reason?: string
}

// ===== 品种页面 =====
export interface ProductItem {
  product: string
  predictions: Prediction[]
}

// ===== 期货公司页面 =====
export interface CompanyItem {
  company: string
  predictions: {
    product: string
    direction: Direction
    confidence: number
    date: string
  }[]
}

// ===== 热力图（趋势分析页面） =====
export interface HeatmapData {
  date: string
  product: string
  value: number // 正值=看涨强度, 负值=看跌强度, 0=中性
}

// ===== 资讯文章 =====
export interface ArticleItem {
  id: number
  title: string
  source: string
  company: string
  publish_time: string
  summary?: string
  url?: string
}

// ===== 方向对应的颜色和标签 =====
export const DIRECTION_CONFIG: Record<Direction, { color: string; bgColor: string; label: string }> = {
  '看涨': { color: '#e74c3c', bgColor: '#fce8e6', label: '涨' },
  '看跌': { color: '#27ae60', bgColor: '#e8f5e9', label: '跌' },
  '中性': { color: '#95a5a6', bgColor: '#f0f0f0', label: '稳' },
}
