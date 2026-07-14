<script setup lang="ts">
import { useRoute } from 'vue-router'

const route = useRoute()

const menuItems = [
  { name: '品种', path: '/products', icon: '📊' },
  { name: '期货公司', path: '/companies', icon: '🏢' },
  { name: '趋势分析', path: '/trends', icon: '📈' },
  { name: '审核队列', path: '/review-queue', icon: '✓' },
]

function isActive(path: string) {
  if (route.path === path || (path === '/review-queue' && route.path.startsWith('/articles/'))) {
    return true
  }
  if (!route.path.startsWith('/analysis-results/')) return false
  const source = route.query.from === 'companies' ? '/companies' : '/products'
  return path === source
}
</script>

<template>
  <aside class="sidebar">
    <div class="logo">
      <h2>MarketANA</h2>
      <span class="subtitle">期货市场分析</span>
    </div>
    <nav class="nav-menu">
      <router-link
        v-for="item in menuItems"
        :key="item.path"
        :to="item.path"
        class="nav-item"
        :class="{ active: isActive(item.path) }"
      >
        <span class="nav-icon">{{ item.icon }}</span>
        <span class="nav-label">{{ item.name }}</span>
      </router-link>
    </nav>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 200px;
  min-width: 200px;
  background: #1a1a2e;
  color: #eee;
  display: flex;
  flex-direction: column;
  height: 100vh;
}

.logo {
  padding: 24px 20px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.logo h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  color: #fff;
  letter-spacing: 1px;
}

.subtitle {
  font-size: 12px;
  color: #8899aa;
  margin-top: 4px;
  display: block;
}

.nav-menu {
  flex: 1;
  padding: 12px 0;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 20px;
  color: #aabbcc;
  text-decoration: none;
  font-size: 15px;
  transition: all 0.2s;
  border-left: 3px solid transparent;
}

.nav-item:hover {
  background: rgba(255, 255, 255, 0.05);
  color: #fff;
}

.nav-item.active {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
  border-left-color: #e74c3c;
  font-weight: 600;
}

.nav-icon {
  font-size: 18px;
  width: 24px;
  text-align: center;
}

.nav-label {
  font-size: 14px;
}
</style>
