<template>
  <Teleport to="body">
    <div class="modal fade show d-block" tabindex="-1" @mousedown.self="$emit('close')" style="background: rgba(0,0,0,0.5);">
      <div class="modal-dialog modal-lg modal-dialog-centered modal-dialog-scrollable">
        <div class="modal-content">
          <div class="modal-header border-bottom">
            <h5 class="modal-title d-flex align-items-center gap-2">
              <Plus :size="20" class="text-primary" />
              Создать задачу парсинга
            </h5>
            <button type="button" class="btn-close" @click="$emit('close')" :disabled="loading"></button>
          </div>

          <div class="modal-body">
            <StepIndicator :steps="steps" :current-step="currentStep" />

            <SourceStep
              v-if="currentStep === 0"
              v-model="formData"
              :sources="sources"
              :errors="errors"
              @source-changed="handleSourceChanged"
              @mode-changed="handleModeChanged"
            />
            <QueryStep
              v-if="currentStep === 1"
              :source="formData.source"
              :parsing-mode="formData.parsing_mode"
              v-model:config="formData.config"
              :errors="errors"
            />
            <SummaryStep
              v-if="currentStep === 2"
              :task-name="formData.name"
              :source="formData.source"
              :parsing-mode="formData.parsing_mode"
              :config="formData.config"
              :sources="sources"
            />
          </div>

          <div class="modal-footer border-top">
            <button
              v-if="currentStep > 0"
              type="button"
              class="btn btn-outline-secondary me-auto"
              @click="prevStep"
              :disabled="loading"
            >
              Назад
            </button>
            <button type="button" class="btn btn-outline-secondary" @click="$emit('close')" :disabled="loading">
              Отмена
            </button>
            <button
              v-if="currentStep < steps.length - 1"
              type="button"
              class="btn btn-primary"
              :disabled="!canProceed || loading"
              @click="nextStep"
            >
              Далее
            </button>
            <button
              v-else
              type="button"
              class="btn btn-primary d-flex align-items-center gap-2"
              :disabled="!isFormValid || loading"
              @click="handleSubmit"
            >
              <span v-if="loading" class="spinner-border spinner-border-sm"></span>
              Создать и запустить
            </button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { Plus } from 'lucide-vue-next'
import { useToast } from 'vue-toastification'
import { useParsingTasks } from '../composables/useParsingTasks'
import { tasksApi } from '../js/api'
import StepIndicator from './CreateTaskModal/StepIndicator.vue'
import SourceStep from './CreateTaskModal/SourceStep.vue'
import QueryStep from './CreateTaskModal/QueryStep.vue'
import SummaryStep from './CreateTaskModal/SummaryStep.vue'

const toast = useToast()
const emit = defineEmits(['close', 'created', 'task-created'])
const { createTask, loading } = useParsingTasks()

const steps = [
  { label: 'Источник и режим', key: 'source' },
  { label: 'Параметры поиска', key: 'query' },
  { label: 'Проверка', key: 'summary' }
]
const currentStep = ref(0)
const sources = ref([])
const formData = ref({ name: '', source: '', parsing_mode: '', config: {} })
const errors = ref({})

const defaultConfigs = {
  headhunter_api:   { area: '', pages: 5, per_page: 100, delay: 0.5, text: '' },
  headhunter_html:  { area: '', max_pages: 10, items_per_page: 50, experience: '', text: '' },
  habr_career_api:  { max_pages: 10, delay: 0.5, q: '' },
  habr_career_html: { max_pages: 10, q: '' },
  superjob_api:     { pages: 10, delay: 0.5, keyword: '', town: '', catalogues: '' },
  superjob_html:    { max_pages: 10, keywords: '', town: '' }
}

const availableModes = computed(() => {
  const src = sources.value.find(s => s.value === formData.value.source)
  return src ? src.modes : []
})

const canProceed = computed(() => {
  if (currentStep.value === 0) return !!(formData.value.source && formData.value.parsing_mode)
  if (currentStep.value === 1) return validateQueryStep()
  return true
})

const isFormValid = computed(() => {
  const { source, parsing_mode, config } = formData.value
  if (!source || !parsing_mode) return false
  if (source === 'headhunter' && parsing_mode === 'api') return !!(config.area && config.pages > 0)
  if (source === 'headhunter' && parsing_mode === 'html') return !!(config.area && config.max_pages > 0)
  if (source === 'habr_career') return config.max_pages > 0
  if (source === 'superjob' && parsing_mode === 'api') return config.pages > 0
  if (source === 'superjob' && parsing_mode === 'html') return config.max_pages > 0
  return true
})

watch(
  () => [formData.value.source, formData.value.parsing_mode],
  ([src, mode]) => {
    if (src && mode) {
      formData.value.config = { ...defaultConfigs[`${src}_${mode}`] || {} }
      errors.value = {}
    }
  }
)

onMounted(loadSources)

async function loadSources() {
  try {
    const response = await tasksApi.getSources()
    const data = response.data || response
    sources.value = (data.sources || []).map(s => ({
      value: s.id,
      label: s.name,
      modes: s.modes.filter(m => m.available).map(m => ({ value: m.id, label: m.name }))
    }))
  } catch (err) {
    toast.error('Ошибка загрузки источников')
  }
}

function handleSourceChanged() {
  formData.value.parsing_mode = ''
  formData.value.config = {}
  errors.value = {}
}
function handleModeChanged() {
  formData.value.config = {}
  errors.value = {}
}

function validateQueryStep() {
  errors.value = {}
  const { source, parsing_mode, config } = formData.value
  if (source === 'headhunter' && parsing_mode === 'api') {
    if (!config.area) { errors.value.area = 'Выберите регион'; return false }
    if (!config.pages || config.pages < 1 || config.pages > 20) { errors.value.pages = 'Укажите 1-20 страниц'; return false }
  }
  if (source === 'headhunter' && parsing_mode === 'html') {
    if (!config.area) { errors.value.area = 'Выберите регион'; return false }
    if (!config.max_pages || config.max_pages < 1) { errors.value.max_pages = 'Укажите количество страниц'; return false }
  }
  if (source === 'habr_career') {
    if (!config.max_pages || config.max_pages < 1) { errors.value.max_pages = 'Укажите количество страниц'; return false }
  }
  if (source === 'superjob' && parsing_mode === 'api') {
    if (!config.pages || config.pages < 1) { errors.value.pages = 'Укажите количество страниц'; return false }
  }
  if (source === 'superjob' && parsing_mode === 'html') {
    if (!config.max_pages || config.max_pages < 1) { errors.value.max_pages = 'Укажите количество страниц'; return false }
  }
  return true
}

function nextStep() {
  if (currentStep.value === 1 && !validateQueryStep()) return
  if (currentStep.value < steps.length - 1) currentStep.value++
}
function prevStep() {
  if (currentStep.value > 0) currentStep.value--
}

async function handleSubmit() {
  if (!isFormValid.value) { toast.error('Заполните все обязательные поля'); return }
  errors.value = {}
  try {
    const config = { ...formData.value.config }
    Object.keys(config).forEach(k => { if (config[k] === '' || config[k] == null) delete config[k] })

    const src = formData.value.source
    const srcLabel = sources.value.find(s => s.value === src)?.label || src
    const taskData = {
      source: String(src),
      parsing_mode: String(formData.value.parsing_mode),
      name: formData.value.name?.trim() || `${srcLabel} парсинг`,
      config
    }
    const result = await createTask(taskData)
    toast.success('Задача создана и запущена!')
    emit('task-created', result)
    emit('created')
    emit('close')
  } catch (err) {
    const responseData = err.responseData || err.response?.data
    if (responseData && typeof responseData === 'object') {
      const fieldErrors = {}
      for (const [key, value] of Object.entries(responseData)) {
        if (key !== 'detail') fieldErrors[key] = Array.isArray(value) ? value.join(' ') : String(value)
      }
      errors.value = fieldErrors
      const detail = responseData.detail
      if (responseData.broker?.length) {
        toast.error('Сервис очередей недоступен. Проверьте конфигурацию брокера.')
      } else {
        toast.error(typeof detail === 'string' ? detail : (err.message || 'Ошибка создания задачи'))
      }
    } else {
      toast.error(err.message || 'Ошибка создания задачи')
    }
  }
}
</script>
