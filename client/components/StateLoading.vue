<template>
  <div class="vp-loading-state">
    <div class="vp-spinner"></div>
    <span>{{ text }}</span>
  </div>
</template>

<script setup>
defineProps({
  text: { type: String, default: 'Загрузка...' }
})
</script>

<style lang="scss" scoped>
@import '../scss/main';
</style>
