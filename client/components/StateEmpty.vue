<template>
  <div class="vp-empty-state">
    <div class="vp-empty-icon">
      <component :is="iconComponent" :size="28" />
    </div>
    <h5>{{ title }}</h5>
    <p class="mb-0 text-secondary" v-if="description">{{ description }}</p>
    <button v-if="actionLabel" class="btn btn-primary btn-sm mt-3" @click="$emit('action')">
      {{ actionLabel }}
    </button>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Inbox, SearchX, AlertCircle } from 'lucide-vue-next'

const props = defineProps({
  title:       { type: String, default: 'Нет данных' },
  description: { type: String, default: '' },
  actionLabel: { type: String, default: '' },
  icon:        { type: String, default: 'inbox' }
})
defineEmits(['action'])

const iconComponent = computed(() => {
  const map = { inbox: Inbox, search: SearchX, alert: AlertCircle }
  return map[props.icon] || Inbox
})
</script>

<style lang="scss" scoped>
@import '../scss/main';
</style>
