<template>
  <div>
    <p class="text-secondary mb-4">Выберите платформу для парсинга вакансий и предпочтительный режим работы</p>

    <div class="mb-3">
      <label class="form-label fw-medium">Название задачи</label>
      <input
        v-model="localData.name"
        type="text"
        class="form-control"
        placeholder="Например: Парсинг Python вакансий Москва"
      />
    </div>

    <div class="mb-3">
      <label class="form-label fw-medium">Источник данных <span class="text-danger">*</span></label>
      <select
        v-model="localData.source"
        class="form-select"
        :class="{ 'is-invalid': errors.source }"
        @change="handleSourceChange"
      >
        <option value="">Выберите источник</option>
        <option v-for="s in sources" :key="s.value" :value="s.value">{{ s.label }}</option>
      </select>
      <div class="invalid-feedback" v-if="errors.source">{{ errors.source }}</div>
    </div>

    <div class="mb-3">
      <label class="form-label fw-medium">Режим парсинга <span class="text-danger">*</span></label>
      <select
        v-model="localData.parsing_mode"
        class="form-select"
        :class="{ 'is-invalid': errors.parsing_mode }"
        :disabled="!localData.source"
        @change="handleModeChange"
      >
        <option value="">{{ localData.source ? 'Выберите режим' : 'Сначала выберите источник' }}</option>
        <option v-for="m in availableModes" :key="m.value" :value="m.value">{{ m.label }}</option>
      </select>
      <div class="invalid-feedback" v-if="errors.parsing_mode">{{ errors.parsing_mode }}</div>
    </div>

    <div v-if="localData.source && localData.parsing_mode" class="alert border" :class="sourceAlertClass" role="alert">
      <div class="d-flex align-items-center gap-2">
        <component :is="sourceIcon" :size="20" />
        <div>
          <div class="fw-semibold">{{ sourceLabel }}</div>
          <small class="opacity-75">{{ modeLabel }}</small>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Briefcase, Building2, Database } from 'lucide-vue-next'

const props = defineProps({
  modelValue: { type: Object, required: true },
  sources:    { type: Array, required: true },
  errors:     { type: Object, default: () => ({}) }
})
const emit = defineEmits(['update:modelValue', 'source-changed', 'mode-changed'])

const localData = computed({
  get: () => props.modelValue,
  set: v => emit('update:modelValue', v)
})

const availableModes = computed(() => {
  const src = props.sources.find(s => s.value === localData.value.source)
  return src ? src.modes : []
})
const sourceLabel = computed(() => props.sources.find(s => s.value === localData.value.source)?.label || '')
const modeLabel   = computed(() => availableModes.value.find(m => m.value === localData.value.parsing_mode)?.label || '')

const sourceAlertClass = computed(() => ({
  headhunter:   'alert-danger',
  habr_career:  'alert-info',
  superjob:     'alert-success'
})[localData.value.source] || 'alert-secondary')

const sourceIcon = computed(() => ({
  headhunter:  Briefcase,
  habr_career: Building2,
  superjob:    Database
})[localData.value.source] || Briefcase)

function handleSourceChange() {
  localData.value.parsing_mode = ''
  emit('source-changed', localData.value.source)
}
function handleModeChange() {
  emit('mode-changed', localData.value.parsing_mode)
}
</script>
