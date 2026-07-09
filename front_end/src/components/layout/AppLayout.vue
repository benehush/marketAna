<script setup lang="ts">
import AppSidebar from './AppSidebar.vue'
</script>

<template>
  <div class="app-layout">
    <AppSidebar />
    <main class="main-content">
      <router-view />
    </main>
    <aside class="right-panel">
      <div class="search-section">
        <input
          type="text"
          class="search-input"
          placeholder="搜索品种、公司..."
          disabled
          title="搜索功能待开发"
        />
      </div>
      <div class="right-placeholder">
        <p class="hint-text">搜索功能</p>
        <p class="hint-sub">后续阶段开发</p>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.app-layout {
  display: flex;
  height: 100vh;
  background: #f5f6fa;
}

.main-content {
  flex: 1;
  overflow-y: auto;
  padding: 28px 32px;
  min-width: 0;
}

.right-panel {
  width: 240px;
  min-width: 240px;
  background: #fff;
  border-left: 1px solid #e8eaed;
  padding: 20px 16px;
}

.search-section {
  margin-bottom: 24px;
}

.search-input {
  width: 100%;
  padding: 10px 14px;
  border: 1px solid #ddd;
  border-radius: 8px;
  font-size: 14px;
  background: #f8f9fa;
  color: #999;
  outline: none;
  box-sizing: border-box;
}

.search-input::placeholder {
  color: #bbb;
}

.right-placeholder {
  text-align: center;
  padding: 40px 0;
}

.hint-text {
  font-size: 14px;
  color: #999;
  margin: 0 0 6px;
}

.hint-sub {
  font-size: 12px;
  color: #ccc;
  margin: 0;
}
</style>
