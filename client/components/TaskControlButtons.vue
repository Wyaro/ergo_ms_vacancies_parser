<template>
  <div class="d-flex align-items-center gap-1">
    <button
      class="btn btn-sm btn-outline-secondary"
      @click.stop="$router.push({ name: 'VacanciesParserTaskDetail', params: { id: task.id } })"
      title="Детали задачи"
    >
      <Eye :size="14" />
    </button>
    <button
      v-if="task.status === 'running'"
      class="btn btn-sm btn-outline-warning"
      @click.stop="$emit('pause', task.id)"
      :disabled="loading"
      title="Приостановить"
    >
      <Pause :size="14" />
    </button>
    <button
      v-if="task.status === 'paused'"
      class="btn btn-sm btn-outline-primary"
      @click.stop="$emit('resume', task.id)"
      :disabled="loading"
      title="Возобновить"
    >
      <Play :size="14" />
    </button>
    <button
      v-if="task.is_active"
      class="btn btn-sm btn-outline-danger"
      @click.stop="$emit('stop', task.id)"
      :disabled="loading"
      title="Остановить"
    >
      <Square :size="14" />
    </button>
    <button
      v-if="task.is_finished"
      class="btn btn-sm btn-outline-danger"
      @click.stop="$emit('delete', task.id)"
      :disabled="loading"
      title="Удалить"
    >
      <Trash2 :size="14" />
    </button>
  </div>
</template>

<script setup>
import { Eye, Pause, Play, Square, Trash2 } from 'lucide-vue-next'

defineProps({
  task:    { type: Object, required: true },
  loading: { type: Boolean, default: false }
})
defineEmits(['pause', 'resume', 'stop', 'delete'])
</script>
