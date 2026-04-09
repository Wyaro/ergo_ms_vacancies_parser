<template>
  <div class="vp-page-header">
    <div class="vp-page-title">
      <div class="vp-page-icon" v-if="icon">
        <component :is="iconComponent" :size="20" />
      </div>
      <div>
        <h1>{{ title }}</h1>
        <p v-if="subtitle">{{ subtitle }}</p>
      </div>
    </div>
    <div class="d-flex align-items-center gap-2 flex-wrap" v-if="$slots.actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<script setup>
import { computed, defineAsyncComponent } from 'vue'
import * as LucideIcons from 'lucide-vue-next'

const props = defineProps({
  title:    { type: String, required: true },
  subtitle: { type: String, default: '' },
  icon:     { type: String, default: '' }
})

const iconComponent = computed(() => {
  if (!props.icon) return null
  return LucideIcons[props.icon] || LucideIcons.Circle
})
</script>

<style lang="scss" scoped>
@import '../scss/main';
</style>
