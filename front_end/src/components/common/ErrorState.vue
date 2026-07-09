<script setup lang="ts">
defineProps<{
  message?: string
  onRetry?: () => void
}>()
</script>

<template>
  <div class="error-state">
    <span class="error-icon">⚠️</span>
    <p class="error-text">{{ message || '加载失败，请稍后重试' }}</p>
    <button v-if="onRetry" class="retry-btn" @click="onRetry">
      重新加载
    </button>
  </div>
</template>

<style scoped>
.error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 0;
}

.error-icon {
  font-size: 40px;
  margin-bottom: 12px;
}

.error-text {
  color: #e74c3c;
  font-size: 14px;
  margin-bottom: 16px;
}

.retry-btn {
  padding: 8px 20px;
  border: 1px solid #e74c3c;
  border-radius: 6px;
  background: #fff;
  color: #e74c3c;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.retry-btn:hover {
  background: #e74c3c;
  color: #fff;
}
</style>
