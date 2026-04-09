<template>
  <nav v-if="totalPages > 1" aria-label="Пагинация">
    <ul class="pagination pagination-sm justify-content-center mb-0">
      <li class="page-item" :class="{ disabled: modelValue === 1 }">
        <button class="page-link" @click="$emit('update:modelValue', modelValue - 1)" :disabled="modelValue === 1">
          &laquo;
        </button>
      </li>

      <template v-for="page in visiblePages" :key="page">
        <li v-if="page === '...'" class="page-item disabled">
          <span class="page-link">…</span>
        </li>
        <li v-else class="page-item" :class="{ active: page === modelValue }">
          <button class="page-link" @click="$emit('update:modelValue', page)">{{ page }}</button>
        </li>
      </template>

      <li class="page-item" :class="{ disabled: modelValue === totalPages }">
        <button class="page-link" @click="$emit('update:modelValue', modelValue + 1)" :disabled="modelValue === totalPages">
          &raquo;
        </button>
      </li>
    </ul>
  </nav>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  modelValue: { type: Number, required: true },
  totalPages: { type: Number, required: true }
})
defineEmits(['update:modelValue'])

const visiblePages = computed(() => {
  const { modelValue: cur, totalPages: total } = props
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1)

  const pages = []
  if (cur <= 4) {
    pages.push(...[1, 2, 3, 4, 5, '...', total])
  } else if (cur >= total - 3) {
    pages.push(...[1, '...', total - 4, total - 3, total - 2, total - 1, total])
  } else {
    pages.push(...[1, '...', cur - 1, cur, cur + 1, '...', total])
  }
  return pages
})
</script>
