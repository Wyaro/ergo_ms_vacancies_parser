<template>
  <div class="vp-empty-state">
    <div class="vp-empty-icon bg-danger bg-opacity-10">
      <AlertTriangle :size="28" class="text-danger" />
    </div>
    <h5>{{ title }}</h5>
    <p class="mb-0 text-secondary" v-if="message">{{ message }}</p>
    <button class="btn btn-outline-danger btn-sm mt-3" @click="$emit('retry')">
      Повторить
    </button>
  </div>
</template>

<script setup>
import { AlertTriangle } from 'lucide-vue-next'
defineProps({
  title:   { type: String, default: 'Ошибка загрузки' },
  message: { type: String, default: '' }
})
defineEmits(['retry'])
</script>

<style lang="scss" scoped>
@import '../scss/main';
</style>
