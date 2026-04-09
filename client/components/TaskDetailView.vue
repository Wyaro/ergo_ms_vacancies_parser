<template>
  <div class="vp-page p-4">
    <StateLoading v-if="loading && !currentTask" text="Загрузка задачи..." />
    <StateError v-else-if="error && !currentTask" :message="error" @retry="fetchTask" />

    <div v-else-if="currentTask">
      <!-- Заголовок -->
      <div class="mb-4">
        <button class="btn btn-link btn-sm p-0 text-secondary mb-2 d-flex align-items-center gap-1 text-decoration-none" @click="$router.push({ name: 'VacanciesParser' })">
          <ArrowLeft :size="14" />
          К списку задач
        </button>
        <div class="d-flex align-items-start justify-content-between gap-3 flex-wrap">
          <div>
            <div class="d-flex align-items-center gap-2 flex-wrap mb-1">
              <span class="badge vp-pill-badge vp-pill-badge-source">
                {{ currentTask.source_display || currentTask.source }}
              </span>
              <span class="badge bg-secondary bg-opacity-10 text-body" style="font-size:0.72rem;">
                {{ currentTask.parsing_mode_display || currentTask.parsing_mode }}
              </span>
              <span class="badge vp-pill-badge" :class="statusPillClass(currentTask.status)">
                {{ currentTask.status_display || currentTask.status }}
              </span>
            </div>
            <h2 class="fw-bold mb-0" style="font-size:1.375rem;">{{ currentTask.name }}</h2>
          </div>
          <div class="d-flex align-items-center gap-2">
            <button class="btn btn-outline-secondary btn-sm d-flex align-items-center gap-1" @click="fetchTask">
              <RefreshCw :size="14" />
              Обновить
            </button>
            <TaskControlButtons
              :task="currentTask"
              :loading="loading"
              @pause="handleAction('pause', $event)"
              @resume="handleAction('resume', $event)"
              @stop="handleAction('stop', $event)"
              @delete="handleDelete"
            />
          </div>
        </div>
      </div>

      <div class="row g-4">
        <!-- Основная часть -->
        <div class="col-lg-8">
          <!-- Прогресс -->
          <div class="vp-card p-3 mb-3">
            <h6 class="fw-semibold mb-3 d-flex align-items-center gap-2">
              <TrendingUp :size="16" class="text-primary" />
              Прогресс выполнения
            </h6>
            <TaskProgressBar
              :completed="taskProgress?.completed || currentTask.completed_items || 0"
              :total="taskProgress?.total || currentTask.total_items || 0"
              :failed="taskProgress?.failed || currentTask.failed_items || 0"
              :status="currentTask.status"
              label="Общий прогресс"
            />
            <div class="row g-2 mt-3" v-if="taskProgress">
              <div class="col" v-for="st in progressStats" :key="st.label">
                <div class="text-center p-2 rounded-2" :class="st.bg">
                  <div class="fw-bold" style="font-size:1.125rem;" :class="st.color">{{ st.value }}</div>
                  <div class="text-secondary" style="font-size:0.72rem;">{{ st.label }}</div>
                </div>
              </div>
            </div>
          </div>

          <!-- Конфигурация -->
          <div class="vp-card p-0 mb-3">
            <div class="accordion" id="configAccordion">
              <div class="accordion-item border-0">
                <h6 class="accordion-header">
                  <button class="accordion-button collapsed fw-semibold py-2 px-3" type="button" data-bs-toggle="collapse" data-bs-target="#configStructured">
                    <Settings :size="15" class="me-2 text-secondary" />
                    Конфигурация
                  </button>
                </h6>
                <div id="configStructured" class="accordion-collapse collapse">
                  <div class="accordion-body pt-0">
                    <dl class="row mb-0 small">
                      <template v-for="[key, val] in configEntries" :key="key">
                        <dt class="col-sm-4 text-secondary fw-normal">{{ configLabel(key) }}</dt>
                        <dd class="col-sm-8 mb-1">{{ configFormatValue(key, val) }}</dd>
                      </template>
                    </dl>
                    <div class="mt-3">
                      <button class="btn btn-link btn-sm p-0 text-secondary" @click="showRawConfig = !showRawConfig">
                        {{ showRawConfig ? 'Скрыть JSON' : 'Показать JSON' }}
                      </button>
                      <div v-if="showRawConfig" class="vp-json-block mt-2">{{ JSON.stringify(currentTask.config, null, 2) }}</div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Ошибка задачи -->
          <div v-if="currentTask.error_message" class="alert alert-danger d-flex align-items-start gap-2" role="alert">
            <AlertCircle :size="18" class="flex-shrink-0 mt-1" />
            <div>
              <div class="fw-semibold mb-1">Ошибка выполнения</div>
              <small>{{ currentTask.error_message }}</small>
            </div>
          </div>

          <!-- Статистика (для завершённых) -->
          <div v-if="currentTask.is_finished" class="vp-card p-3">
            <div class="d-flex align-items-center justify-content-between mb-3">
              <h6 class="fw-semibold mb-0 d-flex align-items-center gap-2">
                <BarChart2 :size="16" class="text-secondary" />
                Статистика выполнения
              </h6>
              <button class="btn btn-outline-secondary btn-sm d-flex align-items-center gap-1" @click="loadStatistics" :disabled="loadingStats">
                <span v-if="loadingStats" class="spinner-border spinner-border-sm"></span>
                <RefreshCw v-else :size="13" />
                Загрузить
              </button>
            </div>
            <div v-if="statistics" class="row g-2 text-center">
              <div class="col-6 col-sm-3" v-for="st in statsCards" :key="st.label">
                <div class="p-2 rounded-2 bg-body-secondary">
                  <div class="fw-bold fs-5">{{ st.value }}</div>
                  <div class="text-secondary" style="font-size:0.75rem;">{{ st.label }}</div>
                </div>
              </div>
            </div>
            <p v-else class="text-secondary mb-0 small">Нажмите «Загрузить» для отображения статистики</p>
          </div>
        </div>

        <!-- Sidebar -->
        <div class="col-lg-4">
          <div class="vp-card p-3 mb-3">
            <h6 class="fw-semibold mb-3 d-flex align-items-center gap-2">
              <Info :size="16" class="text-secondary" />
              Информация
            </h6>
            <ul class="list-group list-group-flush">
              <li class="list-group-item px-0 py-2 d-flex justify-content-between align-items-center small">
                <span class="text-secondary">ID задачи</span>
                <span class="fw-medium">{{ currentTask.id }}</span>
              </li>
              <li class="list-group-item px-0 py-2 d-flex justify-content-between align-items-center small">
                <span class="text-secondary">Создана</span>
                <span>{{ formatDate(currentTask.created_at) }}</span>
              </li>
              <li v-if="currentTask.started_at" class="list-group-item px-0 py-2 d-flex justify-content-between align-items-center small">
                <span class="text-secondary">Запущена</span>
                <span>{{ formatDate(currentTask.started_at) }}</span>
              </li>
              <li v-if="currentTask.completed_at" class="list-group-item px-0 py-2 d-flex justify-content-between align-items-center small">
                <span class="text-secondary">Завершена</span>
                <span>{{ formatDate(currentTask.completed_at) }}</span>
              </li>
              <li class="list-group-item px-0 py-2 d-flex justify-content-between align-items-center small">
                <span class="text-secondary">Автор</span>
                <span>{{ currentTask.created_by_username || 'Система' }}</span>
              </li>
              <li v-if="currentTask.celery_task_id" class="list-group-item px-0 py-2 small">
                <div class="text-secondary mb-1">Celery Task ID</div>
                <code style="font-size:0.7rem; word-break: break-all;">{{ currentTask.celery_task_id }}</code>
              </li>
            </ul>
          </div>
        </div>
      </div>
    </div>

    <ConfirmDialog ref="confirmDialogRef" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, RefreshCw, TrendingUp, Settings, BarChart2, AlertCircle, Info } from 'lucide-vue-next'
import { useToast } from 'vue-toastification'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { tasksApi } from '../js/api'
import TaskProgressBar from './TaskProgressBar.vue'
import TaskControlButtons from './TaskControlButtons.vue'
import StateLoading from './StateLoading.vue'
import StateError from './StateError.vue'

const route  = useRoute()
const router = useRouter()
const toast  = useToast()

const currentTask = ref(null)
const taskProgress = ref(null)
const statistics = ref(null)
const loading = ref(false)
const loadingStats = ref(false)
const error = ref(null)
const showRawConfig = ref(false)
const confirmDialogRef = ref(null)
let refreshTimer = null

const configEntries = computed(() => {
  if (!currentTask.value?.config) return []
  return Object.entries(currentTask.value.config).filter(([, v]) => v !== '' && v != null)
})

const progressStats = computed(() => {
  const p = taskProgress.value
  if (!p) return []
  return [
    { label: 'Ожидают',     value: p.pending     || 0, bg: 'bg-secondary bg-opacity-10', color: 'text-secondary' },
    { label: 'В процессе',  value: p.in_progress || 0, bg: 'bg-primary bg-opacity-10',   color: 'text-primary' },
    { label: 'Выполнено',   value: p.completed   || 0, bg: 'bg-success bg-opacity-10',   color: 'text-success' },
    { label: 'Ошибки',      value: p.failed      || 0, bg: 'bg-danger bg-opacity-10',    color: 'text-danger' },
    { label: 'Заблокировано', value: p.blocked   || 0, bg: 'bg-warning bg-opacity-10',   color: 'text-warning' }
  ]
})

const statsCards = computed(() => {
  if (!statistics.value) return []
  return [
    { label: 'items/sec',   value: statistics.value.items_per_second || '—' },
    { label: 'Среднее, мс', value: statistics.value.avg_item_duration_ms || '—' },
    { label: 'Успешность',  value: statistics.value.success_rate ? statistics.value.success_rate + '%' : '—' },
    { label: 'Длительность', value: formatDuration(statistics.value.duration_seconds) }
  ]
})

function statusPillClass(status) {
  const map = {
    running: 'vp-pill-badge-info',
    completed: 'vp-pill-badge-success',
    failed: 'vp-pill-badge-danger',
    paused: 'vp-pill-badge-warning',
    stopped: 'vp-pill-badge-neutral',
    pending: 'vp-pill-badge-neutral'
  }
  return map[status] || 'vp-pill-badge-neutral'
}

function formatDate(d) {
  if (!d) return '—'
  return new Date(d).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })
}
function formatDuration(s) {
  if (!s) return '—'
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60
  return `${h}ч ${m}м ${sec}с`
}
function configLabel(key) {
  const map = { area: 'Регион', pages: 'Страниц', max_pages: 'Макс. страниц', per_page: 'На страницу', delay: 'Задержка', text: 'Запрос', keyword: 'Запрос', q: 'Запрос', town: 'Город', catalogues: 'Каталоги', get_details: 'Загружать детали', experience: 'Опыт' }
  return map[key] || key
}
function configFormatValue(key, val) {
  if (key === 'area') {
    const m = { '1': 'Москва', '2': 'Санкт-Петербург', '113': 'Россия', '66': 'Нижний Новгород', '88': 'Казань', '4': 'Новосибирск', '3': 'Екатеринбург' }
    return m[val] || val
  }
  if (typeof val === 'boolean') return val ? 'Да' : 'Нет'
  return val ?? '—'
}

async function fetchTask() {
  const id = route.params.id
  loading.value = true
  error.value = null
  try {
    const r = await tasksApi.get(id)
    currentTask.value = r.data || r
    const rp = await tasksApi.getProgress(id)
    taskProgress.value = rp.data || rp
  } catch (e) {
    error.value = e.message || 'Ошибка загрузки задачи'
  } finally {
    loading.value = false
  }
}

async function loadStatistics() {
  loadingStats.value = true
  try {
    const r = await tasksApi.getStatistics(route.params.id)
    statistics.value = r.data || r
  } catch (e) {
    toast.error('Ошибка загрузки статистики')
  } finally {
    loadingStats.value = false
  }
}

async function handleAction(action, id) {
  const actions = { pause: tasksApi.pause, resume: tasksApi.resume, stop: tasksApi.stop }
  const messages = { pause: 'приостанавливается', resume: 'возобновляется', stop: 'останавливается' }
  try {
    await actions[action](id)
    toast.info(`Задача ${messages[action]}...`)
    setTimeout(fetchTask, 1000)
  } catch (e) {
    toast.error('Ошибка операции')
  }
}

async function handleDelete(id) {
  const ok = await confirmDialogRef.value?.open({ title: 'Удалить задачу?', message: 'Это действие нельзя отменить.', confirmText: 'Удалить', confirmVariant: 'danger' })
  if (!ok) return
  try {
    await tasksApi.delete(id)
    toast.success('Задача удалена')
    router.push({ name: 'VacanciesParser' })
  } catch (e) {
    toast.error('Ошибка удаления')
  }
}

onMounted(() => {
  fetchTask()
  refreshTimer = setInterval(() => {
    if (currentTask.value?.is_active) fetchTask()
  }, 5000)
})
onUnmounted(() => clearInterval(refreshTimer))
</script>

<style lang="scss" scoped>
@import '../scss/main';
</style>
