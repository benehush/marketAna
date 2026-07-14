import { createRouter, createWebHashHistory } from 'vue-router'
import ProductsView from '../views/ProductsView.vue'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/',
      redirect: '/products',
    },
    {
      path: '/products',
      name: 'products',
      component: ProductsView,
    },
    {
      path: '/companies',
      name: 'companies',
      component: () => import('../views/CompaniesView.vue'),
    },
    {
      path: '/trends',
      name: 'trends',
      component: () => import('../views/TrendsView.vue'),
    },
    {
      path: '/analysis-results/:id',
      name: 'analysis-result-detail',
      component: () => import('../views/AnalysisResultDetailView.vue'),
    },
    {
      path: '/articles',
      redirect: '/review-queue',
    },
    {
      path: '/review-queue',
      name: 'review-queue',
      component: () => import('../views/ArticlesView.vue'),
    },
    {
      path: '/articles/:id',
      name: 'article-detail',
      component: () => import('../views/ArticleDetailView.vue'),
    },
    {
      path: '/review-queue/:id',
      redirect: (to) => ({ path: `/articles/${to.params.id}`, query: to.query }),
    },
  ],
})

export default router
