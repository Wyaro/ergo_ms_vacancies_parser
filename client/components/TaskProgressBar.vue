<template>
  <div>
    <div class="d-flex justify-content-between align-items-center mb-1">
      <small class="text-secondary">{{ label }}</small>
      <small class="fw-semibold">{{ percent }}%</small>
    </div>
    <div class="progress" style="height: 8px; border-radius: 4px;">
      <div
        class="progress-bar"
        :class="barClass"
        role="progressbar"
        :style="{ width: percent + '%' }"
        :aria-valuenow="percent"
        aria-valuemin="0"
        aria-valuemax="100"
      ></div>
    </div>
    <div class="d-flex justify-content-between mt-1" v-if="showCounts">
      <small class="text-secondary">{{ completed }} / {{ total }}</small>
      <small class="text-danger" v-if="failed > 0">{{ failed }} ошибок</small>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  completed:  { type: Number, default: 0 },
  total:      { type: Number, default: 0 },
  failed:     { type: Number, default: 0 },
  status:     { type: String, default: 'running' },
  label:      { type: String, default: 'Прогресс' },
  showCounts: { type: Boolean, default: true }
})

const percent = computed(() => {
  if (!props.total) return 0
  return Math.min(100, Math.round((props.completed / props.total) * 100))
})

const barClass = computed(() => {
  const map = {
    completed: 'bg-success',
    failed:    'bg-danger',
    paused:    'bg-warning',
    stopped:   'bg-secondary'
  }
  const base = map[props.status] || 'bg-primary'
  return [base, props.status === 'running' ? 'progress-bar-animated progress-bar-striped' : '']
})
</script>
