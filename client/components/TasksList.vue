<template>
  <div class="container py-4">
    <div class="vp-cc-header d-flex flex-column flex-lg-row align-items-lg-center justify-content-between gap-2 mb-3">
      <div class="d-flex align-items-center gap-2">
        <div class="vp-cc-title-icon d-flex align-items-center justify-content-center">
          <ClipboardList :size="22" :stroke-width="1.7" />
        </div>
        <div>
          <h2 class="mb-1 d-flex align-items-center gap-2">
            {{ activeTab === 'parsing' ? 'Задачи парсинга' : 'Системные задачи' }}
            <span v-if="activeTab === 'parsing'" class="badge vp-pill-badge vp-pill-badge-accent">Всего: {{ totalCount }}</span>
          </h2>
          <div class="text-muted small d-flex flex-wrap align-items-center gap-2">
            <span v-if="activeTab === 'parsing'" class="d-inline-flex align-items-center gap-1">
              <Activity :size="14" /> Активных: {{ activeCount }}
            </span>
            <span v-if="activeTab === 'system'" class="d-inline-flex align-items-center gap-1">
              <Layers :size="14" /> Запусков: {{ sysTotalCount }}
            </span>
            <span v-if="activeTab === 'system'" class="d-inline-flex align-items-center gap-1">
              <Activity :size="14" /> Running: {{ sysRunningCount }}
            </span>
            <span class="d-inline-flex align-items-center gap-1" v-if="lastLoadedAt && activeTab === 'parsing'">
              <Clock3 :size="14" /> Обновлено: {{ lastLoadedAt }}
            </span>
            <span class="d-inline-flex align-items-center gap-1" v-if="sysLastLoadedAt && activeTab === 'system'">
              <Clock3 :size="14" /> Обновлено: {{ sysLastLoadedAt }}
            </span>
          </div>
        </div>
      </div>
      <div class="d-flex flex-wrap gap-2 justify-content-start justify-content-lg-end">
        <button
          class="btn btn-sm btn-outline-secondary"
          type="button"
          :disabled="loading || sysLoading"
          @click="activeTab === 'parsing' ? loadData() : loadSystemData()"
        >
          Обновить
        </button>
        <div v-if="activeTab === 'parsing' && isRefreshing" class="text-muted small d-inline-flex align-items-center gap-1 px-2">
          <span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>
          Обновление…
        </div>
        <div v-else-if="activeTab === 'system' && isSysRefreshing" class="text-muted small d-inline-flex align-items-center gap-1 px-2">
          <span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>
          Обновление…
        </div>
        <button
          v-if="activeTab === 'parsing'"
          class="btn btn-sm btn-danger d-flex align-items-center gap-1"
          type="button"
          @click="showCreateModal = true"
        >
          <Plus :size="14" />
          Создать задачу
        </button>
        <button
          v-else
          class="btn btn-sm btn-outline-primary d-flex align-items-center gap-1"
          type="button"
          :disabled="sysLoadingJobs || !selectedJobId"
          @click="runSelectedJob"
        >
          <PlayCircle :size="14" />
          Запустить сейчас
        </button>
      </div>
    </div>

    <div class="btn-group mb-3 vp-tab-switch" role="group" aria-label="Переключатель типа задач">
      <button
        type="button"
        class="btn btn-sm"
        :class="activeTab === 'parsing' ? 'btn-primary' : 'btn-outline-primary'"
        @click="activeTab = 'parsing'"
        :aria-pressed="activeTab === 'parsing'"
      >
        Задачи парсинга
      </button>
      <button
        type="button"
        class="btn btn-sm"
        :class="activeTab === 'system' ? 'btn-primary' : 'btn-outline-primary'"
        @click="activeTab = 'system'; loadSystemData()"
        :aria-pressed="activeTab === 'system'"
      >
        Системные задачи
      </button>
    </div>

    <!-- Фильтры -->
    <div v-if="activeTab === 'parsing'" class="card shadow-sm border-0 mb-3 vp-filters-card">
      <div class="card-body">
        <div class="d-flex justify-content-between align-items-start mb-2">
          <div>
            <div class="d-flex align-items-center gap-1 fw-semibold">
              <Filter :size="16" /> Фильтры и представление
            </div>
            <div class="text-muted small">Фильтры применяются мгновенно.</div>
          </div>
          <button type="button" class="btn btn-link btn-sm text-decoration-none p-0" @click="resetFilters">Сбросить</button>
        </div>
        <div class="row g-2 align-items-end">
          <div class="col-12 col-sm-6 col-lg-4">
            <div class="input-group input-group-sm">
              <span class="input-group-text"><Search :size="14" /></span>
              <input
                v-model="searchQuery"
                type="text"
                class="form-control"
                placeholder="Поиск задач..."
                @input="handleSearch"
              />
              <button
                v-if="searchQuery"
                type="button"
                class="btn btn-outline-secondary"
                aria-label="Очистить поиск"
                @click="clearSearch"
              >
                <X :size="14" />
              </button>
            </div>
          </div>
          <div class="col-6 col-sm-3 col-lg-2">
            <select v-model="filters.source" class="form-select form-select-sm" @change="applyFilters">
              <option value="">Все источники</option>
              <option value="headhunter">HeadHunter</option>
              <option value="superjob">SuperJob</option>
              <option value="habr_career">Habr Career</option>
            </select>
          </div>
          <div class="col-6 col-sm-3 col-lg-2">
            <select v-model="filters.parsing_mode" class="form-select form-select-sm" @change="applyFilters">
              <option value="">Все режимы</option>
              <option value="api">API</option>
              <option value="html">HTML</option>
            </select>
          </div>
          <div class="col-6 col-sm-3 col-lg-2">
            <select v-model="filters.status" class="form-select form-select-sm" @change="applyFilters">
              <option value="">Все статусы</option>
              <option value="pending">Ожидает</option>
              <option value="running">Выполняется</option>
              <option value="paused">Пауза</option>
              <option value="completed">Завершена</option>
              <option value="failed">Ошибка</option>
              <option value="stopped">Остановлена</option>
            </select>
          </div>
          <div class="col-6 col-sm-3 col-lg-2">
            <button class="btn btn-outline-secondary btn-sm w-100 d-flex align-items-center justify-content-center gap-1" @click="resetFilters">
              <FilterX :size="14" />
              Сброс
            </button>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="card shadow-sm border-0 mb-3 vp-filters-card">
      <div class="card-body">
        <div class="d-flex justify-content-between align-items-start mb-2">
          <div>
            <div class="d-flex align-items-center gap-1 fw-semibold">
              <Filter :size="16" /> Фильтры и запуск job’ов
            </div>
            <div class="text-muted small">Список — последние запуски (TaskRun). Запуск — через реестр системных задач.</div>
          </div>
          <button type="button" class="btn btn-link btn-sm text-decoration-none p-0" @click="resetSystemFilters">Сбросить</button>
        </div>
        <div class="row g-2 align-items-end">
          <div class="col-12 col-lg-4">
            <label class="form-label small text-muted mb-1" for="vp-sys-job">Системная задача</label>
            <select id="vp-sys-job" v-model="selectedJobId" class="form-select form-select-sm">
              <option value="">Выберите job…</option>
              <option v-for="job in systemJobs" :key="job.id" :value="job.id">
                {{ job.title }}
              </option>
            </select>
          </div>
          <div v-if="selectedJob?.requires_task_id" class="col-12 col-lg-2">
            <label class="form-label small text-muted mb-1" for="vp-sys-task-id">ID задачи парсинга</label>
            <input
              id="vp-sys-task-id"
              v-model="selectedJobTaskId"
              type="number"
              class="form-control form-control-sm"
              placeholder="Например: 123"
              inputmode="numeric"
            />
          </div>
          <div class="col-6 col-lg-2">
            <label class="form-label small text-muted mb-1" for="vp-sys-status">Статус</label>
            <select id="vp-sys-status" v-model="sysFilters.status" class="form-select form-select-sm" @change="loadSystemRuns">
              <option value="">Все</option>
              <option value="running">выполняется</option>
              <option value="success">успех</option>
              <option value="failure">ошибка</option>
            </select>
          </div>
          <div class="col-6 col-lg-2">
            <label class="form-label small text-muted mb-1" for="vp-sys-source">Источник</label>
            <select id="vp-sys-source" v-model="sysFilters.source" class="form-select form-select-sm" @change="loadSystemRuns">
              <option value="">Все</option>
              <option value="headhunter">headhunter</option>
              <option value="superjob">superjob</option>
              <option value="habr_career">habr_career</option>
            </select>
          </div>
          <div class="col-12 col-lg-3">
            <label class="form-label small text-muted mb-1" for="vp-sys-search">Поиск</label>
            <div class="input-group input-group-sm">
              <span class="input-group-text"><Search :size="14" /></span>
              <input
                id="vp-sys-search"
                v-model="sysFilters.search"
                type="text"
                class="form-control"
                placeholder="Имя задачи или ошибка…"
                @input="handleSystemSearch"
              />
              <button
                v-if="sysFilters.search"
                type="button"
                class="btn btn-outline-secondary"
                aria-label="Очистить поиск"
                @click="clearSystemSearch"
              >
                <X :size="14" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Состояния загрузки/ошибки/пусто -->
    <StateLoading v-if="activeTab === 'parsing' && loading && tasks.length === 0" />
    <StateError v-else-if="activeTab === 'parsing' && error && tasks.length === 0" :message="error" @retry="loadData" />
    <StateEmpty
      v-else-if="activeTab === 'parsing' && !loading && tasks.length === 0"
      title="Задач не найдено"
      description="Создайте новую задачу парсинга"
      action-label="Создать задачу"
      @action="showCreateModal = true"
    />

    <StateLoading v-else-if="activeTab === 'system' && sysLoading && sysRuns.length === 0" />
    <StateError v-else-if="activeTab === 'system' && sysError && sysRuns.length === 0" :message="sysError" @retry="loadSystemData" />
    <StateEmpty
      v-else-if="activeTab === 'system' && !sysLoading && sysRuns.length === 0"
      title="Запусков не найдено"
      description="Запустите системный job или ослабьте фильтры."
      :action-label="selectedJobId ? 'Запустить выбранную задачу' : 'Обновить'"
      @action="selectedJobId ? runSelectedJob() : loadSystemData()"
    />

    <!-- Список задач -->
    <div v-else-if="activeTab === 'parsing'" class="table-responsive">
      <table class="table table-hover align-middle vp-table">
        <caption class="visually-hidden">Список задач парсинга с текущим статусом, прогрессом и временем последнего обновления.</caption>
        <thead>
          <tr>
            <th scope="col">Задача</th>
            <th scope="col" class="d-none d-md-table-cell">Статус</th>
            <th scope="col" class="d-none d-lg-table-cell">Обновление</th>
            <th scope="col" class="d-none d-lg-table-cell">Прогресс</th>
            <th scope="col" class="text-end">Создана</th>
            <th scope="col" class="text-end">Действия</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="task in tasks" :key="task.id" :class="rowClass(task)">
            <td>
              <div class="fw-semibold">{{ task.name }}</div>
              <div class="text-muted small d-flex flex-wrap gap-2 align-items-center">
                <span class="badge vp-pill-badge vp-pill-badge-source">{{ sourceLabel(task.source) }}</span>
                <span class="badge vp-pill-badge vp-pill-badge-neutral">{{ (task.parsing_mode_display || task.parsing_mode || '').toUpperCase() }}</span>
                <span v-if="task.started_at" class="d-inline-flex align-items-center gap-1">
                  <PlayCircle :size="14" /> Запущена: {{ formatDate(task.started_at) }}
                </span>
                <span v-if="task.error_message" class="d-inline-flex align-items-center gap-1 text-danger">
                  Ошибка: {{ truncate(task.error_message, 140) }}
                </span>
              </div>
            </td>
            <td class="d-none d-md-table-cell">
              <span class="badge vp-pill-badge" :class="statusPillClass(task.status)">
                {{ task.status_display || statusLabel(task.status) }}
              </span>
            </td>
            <td class="d-none d-lg-table-cell">
              <div class="d-flex flex-column gap-1">
                <span class="text-muted small">Обновлено {{ timeAgo(task.updated_at) }}</span>
                <span v-if="isStale(task)" class="badge vp-pill-badge vp-pill-badge-warning">Давно не обновлялась</span>
              </div>
            </td>
            <td class="d-none d-lg-table-cell">
              <div class="d-flex flex-column gap-1">
                <div class="d-flex justify-content-between text-muted small">
                  <span>{{ task.completed_items || 0 }} / {{ task.total_items || 0 }}</span>
                  <span v-if="task.failed_items">ошибок: {{ task.failed_items }}</span>
                </div>
                <div class="progress" style="height:4px">
                  <div class="progress-bar" :class="statusProgressClass(task.status)" :style="{ width: (task.progress_percent || 0) + '%' }"></div>
                </div>
              </div>
            </td>
            <td class="text-end">
              <div class="d-flex flex-column align-items-end gap-1">
                <div class="text-muted small">{{ formatDate(task.created_at) }}</div>
              </div>
            </td>
            <td class="text-end">
              <div class="d-flex justify-content-end align-items-center gap-2">
                <TaskControlButtons
                  :task="task"
                  :loading="loading"
                  @pause="pauseTask"
                  @resume="resumeTask"
                  @stop="confirmStop(task)"
                  @delete="confirmDelete(task)"
                />
              </div>
            </td>
          </tr>
        </tbody>
      </table>

      <Pagination
        v-if="totalPages > 1"
        v-model="currentPage"
        :total-pages="totalPages"
        @update:model-value="changePage"
        class="mt-3"
      />
    </div>

    <!-- Системные задачи: TaskRun -->
    <div v-else class="table-responsive">
      <table class="table table-hover align-middle vp-table">
        <caption class="visually-hidden">Список системных запусков (TaskRun): статус, время выполнения, метрики, время последнего обновления.</caption>
        <thead>
          <tr>
            <th scope="col">Задача</th>
            <th scope="col" class="d-none d-md-table-cell">Статус</th>
            <th scope="col" class="d-none d-lg-table-cell">Время</th>
            <th scope="col" class="d-none d-xl-table-cell">Метрики</th>
            <th scope="col" class="d-none d-lg-table-cell">Обновление</th>
            <th scope="col" class="text-end">Старт</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="run in sysRuns" :key="run.id" :class="sysRowClass(run)">
            <td>
              <div class="fw-semibold">{{ jobTitle(run) }}</div>
              <div class="text-muted small d-flex flex-wrap gap-2 align-items-center">
                <span class="badge vp-pill-badge vp-pill-badge-neutral">{{ run.task_name }}</span>
                <span v-if="shouldShowSource(run.source)" class="badge vp-pill-badge vp-pill-badge-source">{{ sourceLabel(run.source) }}</span>
                <span v-if="run.error_message" class="d-inline-flex align-items-center gap-1 text-danger">
                  Ошибка: {{ truncate(run.error_message, 140) }}
                </span>
              </div>
            </td>
            <td class="d-none d-md-table-cell">
              <span class="badge vp-pill-badge" :class="sysStatusPillClass(run.status)">
                {{ run.status_display || run.status }}
              </span>
              <div v-if="run.status === 'failure' && (run.error_type || run.error_message)" class="text-muted small lh-sm mt-1">
                {{ run.error_type || 'Ошибка' }}<span v-if="run.error_message">: {{ truncate(run.error_message, 90) }}</span>
              </div>
            </td>
            <td class="d-none d-lg-table-cell">
              <div class="text-muted small lh-sm d-flex flex-column gap-1">
                <span>
                  <span class="me-2">Старт:</span>
                  <span class="fw-semibold text-body">{{ formatTime(run.started_at) }}</span>
                  <span class="text-muted">({{ formatDateShort(run.started_at) }})</span>
                </span>
                <span>
                  <span class="me-2">Длит.:</span>
                  <span class="fw-semibold text-body">{{ formatDuration(run.duration_sec) }}</span>
                  <span class="text-muted">/ Финиш: {{ run.finished_at ? formatTime(run.finished_at) : '—' }}</span>
                </span>
              </div>
            </td>
            <td class="d-none d-xl-table-cell">
              <div class="d-flex flex-wrap gap-1 vp-mini-pills">
                <span class="badge vp-pill-badge vp-pill-badge-neutral">обраб {{ run.processed ?? 0 }}</span>
                <span class="badge vp-pill-badge vp-pill-badge-neutral">сохр {{ run.saved ?? 0 }}</span>
                <span class="badge vp-pill-badge vp-pill-badge-neutral">обн {{ run.updated ?? 0 }}</span>
                <span
                  class="badge vp-pill-badge"
                  :class="(run.errors ?? 0) > 0 ? 'vp-pill-badge-danger' : 'vp-pill-badge-neutral'"
                >
                  ошиб {{ run.errors ?? 0 }}
                </span>
                <span
                  class="badge vp-pill-badge"
                  :class="(run.http_429 ?? 0) > 0 ? 'vp-pill-badge-warning' : 'vp-pill-badge-neutral'"
                >
                  429 {{ run.http_429 ?? 0 }}
                </span>
                <span
                  class="badge vp-pill-badge"
                  :class="(run.timeouts ?? 0) > 0 ? 'vp-pill-badge-warning' : 'vp-pill-badge-neutral'"
                >
                  тайм {{ run.timeouts ?? 0 }}
                </span>
                <span class="badge vp-pill-badge vp-pill-badge-neutral">повт {{ run.retries ?? 0 }}</span>
              </div>
            </td>
            <td class="d-none d-lg-table-cell">
              <div class="d-flex flex-column gap-1 lh-sm">
                <span class="text-muted small">Обновлено {{ timeAgo(run.updated_at) }}</span>
                <span v-if="isSysStale(run)" class="badge vp-pill-badge vp-pill-badge-warning">Давно не обновлялась</span>
              </div>
            </td>
            <td class="text-end">
              <div class="text-muted small lh-sm">
                <div class="fw-semibold text-body">{{ formatTime(run.started_at) }}</div>
                <div>{{ formatDateShort(run.started_at) }}</div>
              </div>
            </td>
          </tr>
        </tbody>
      </table>

      <Pagination
        v-if="sysTotalPages > 1"
        v-model="sysCurrentPage"
        :total-pages="sysTotalPages"
        @update:model-value="changeSystemPage"
        class="mt-3"
      />
    </div>

    <CreateTaskModal
      v-if="showCreateModal"
      @close="showCreateModal = false"
      @created="onTaskCreated"
    />

    <ConfirmDialog ref="confirmDialogRef" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ClipboardList, Plus, Search, X, FilterX, Filter, Activity, Clock3, PlayCircle, Layers } from 'lucide-vue-next'
import { useToast } from 'vue-toastification'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { tasksApi, monitoringApi, systemApi } from '../js/api'
import TaskControlButtons from './TaskControlButtons.vue'
import StateLoading from './StateLoading.vue'
import StateEmpty from './StateEmpty.vue'
import StateError from './StateError.vue'
import Pagination from './Pagination.vue'
import CreateTaskModal from './CreateTaskModal.vue'

const route  = useRoute()
const router = useRouter()
const toast  = useToast()

const tasks       = ref([])
const loading     = ref(false)
const error       = ref(null)
const isRefreshing = ref(false)
const searchQuery = ref('')
const currentPage = ref(1)
const totalCount  = ref(0)
const pageSize    = 20
const confirmDialogRef = ref(null)
const showCreateModal  = ref(false)
let refreshTimer = null
const lastLoadedAt = ref('')
const activeTab = ref('parsing')

// system tasks
const systemJobs = ref([])
const selectedJobId = ref('')
const selectedJobTaskId = ref('')
const sysRuns = ref([])
const sysLoading = ref(false)
const sysLoadingJobs = ref(false)
const isSysRefreshing = ref(false)
const sysError = ref(null)
const sysCurrentPage = ref(1)
const sysTotalCount = ref(0)
const sysLastLoadedAt = ref('')
let sysSearchTimer = null
const sysPageSize = 20
const sysFilters = ref({
  status: '',
  source: '',
  search: ''
})

const selectedJob = computed(() => systemJobs.value.find(j => j.id === selectedJobId.value) || null)

const filters = ref({
  source: route.query.source || '',
  parsing_mode: route.query.parsing_mode || '',
  status: route.query.status || ''
})

const totalPages = computed(() => Math.ceil(totalCount.value / pageSize))
const hasActiveTasks = computed(() => tasks.value.some(t => t.is_active))
const activeCount = computed(() => tasks.value.filter(t => t.is_active).length)

const sysTotalPages = computed(() => Math.ceil(sysTotalCount.value / sysPageSize))
const sysRunningCount = computed(() => sysRuns.value.filter(r => r.status === 'running').length)

const sourceNames = { headhunter: 'HeadHunter', superjob: 'SuperJob', habr_career: 'Habr Career' }
const statusNames = { pending: 'Ожидает', running: 'Выполняется', paused: 'Пауза', completed: 'Завершена', failed: 'Ошибка', stopped: 'Остановлена' }
function sourceLabel(src) { return sourceNames[src] || src }
function statusLabel(st) { return statusNames[st] || st }
function shouldShowSource(src) {
  if (!src) return false
  const s = String(src).trim().toLowerCase()
  return s !== 'unknown' && s !== '—'
}
function formatDate(d) {
  if (!d) return '—'
  return new Date(d).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function formatTime(d) {
  if (!d) return '—'
  return new Date(d).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

function formatDateShort(d) {
  if (!d) return '—'
  return new Date(d).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' })
}

function truncate(text, maxLen = 120) {
  if (!text) return ''
  const s = String(text)
  return s.length > maxLen ? `${s.slice(0, maxLen)}…` : s
}

function formatDuration(sec) {
  if (sec === null || sec === undefined) return '—'
  const s = Number(sec)
  if (Number.isNaN(s)) return '—'
  if (s < 60) return `${Math.max(0, Math.round(s))} сек`
  const m = Math.floor(s / 60)
  const rest = s - m * 60
  if (m < 60) return `${m} мин ${Math.max(0, Math.round(rest))} сек`
  const h = Math.floor(m / 60)
  const mRest = m - h * 60
  return `${h} ч ${mRest} мин`
}

async function loadData() {
  if (tasks.value.length > 0) isRefreshing.value = true
  loading.value = tasks.value.length === 0
  error.value = null
  try {
    const params = {
      page: currentPage.value,
      page_size: pageSize,
      ...(filters.value.source       && { source: filters.value.source }),
      ...(filters.value.parsing_mode && { parsing_mode: filters.value.parsing_mode }),
      ...(filters.value.status       && { status: filters.value.status }),
      ...(searchQuery.value          && { search: searchQuery.value })
    }
    const response = await tasksApi.list(params)
    const data = response.data
    tasks.value = Array.isArray(data?.results) ? data.results : (Array.isArray(data) ? data : [])
    totalCount.value = data?.count || tasks.value.length
    lastLoadedAt.value = new Date().toLocaleString('ru-RU', { hour: '2-digit', minute: '2-digit' })
  } catch (e) {
    error.value = e.message || 'Ошибка загрузки задач'
  } finally {
    loading.value = false
    isRefreshing.value = false
  }
}

async function loadSystemData() {
  await Promise.all([loadSystemJobs(), loadSystemRuns()])
}

async function loadSystemJobs() {
  sysLoadingJobs.value = true
  try {
    const res = await systemApi.listJobs()
    systemJobs.value = Array.isArray(res.data?.jobs) ? res.data.jobs : []
    if (!selectedJobId.value && systemJobs.value.length) selectedJobId.value = systemJobs.value[0].id
  } catch (e) {
    // не блокируем страницу, если job list не загрузился
    systemJobs.value = []
  } finally {
    sysLoadingJobs.value = false
  }
}

async function loadSystemRuns() {
  if (sysRuns.value.length > 0) isSysRefreshing.value = true
  sysLoading.value = sysRuns.value.length === 0
  sysError.value = null
  try {
    const params = {
      page: sysCurrentPage.value,
      page_size: sysPageSize,
      ordering: '-started_at',
      ...(sysFilters.value.status && { status: sysFilters.value.status }),
      ...(sysFilters.value.source && { source: sysFilters.value.source }),
      ...(sysFilters.value.search && { search: sysFilters.value.search })
    }
    const res = await monitoringApi.listTaskRuns(params)
    const data = res.data
    sysRuns.value = Array.isArray(data?.results) ? data.results : (Array.isArray(data) ? data : [])
    sysTotalCount.value = data?.count || sysRuns.value.length
    sysLastLoadedAt.value = new Date().toLocaleString('ru-RU', { hour: '2-digit', minute: '2-digit' })
  } catch (e) {
    sysError.value = e.message || 'Ошибка загрузки запусков'
  } finally {
    sysLoading.value = false
    isSysRefreshing.value = false
  }
}

async function runSelectedJob() {
  if (!selectedJobId.value) return
  try {
    const payload = selectedJob.value?.requires_task_id ? { task_id: selectedJobTaskId.value } : {}
    await systemApi.runJob(selectedJobId.value, payload)
    toast.success('Системная задача запущена')
    setTimeout(loadSystemRuns, 1000)
  } catch (e) {
    const msg = e?.response?.data?.detail || e?.response?.data?.message || e?.message
    toast.error(msg ? `Не удалось запустить: ${msg}` : 'Не удалось запустить задачу')
  }
}

function timeAgo(dateStr) {
  if (!dateStr) return '—'
  const diffMs = Date.now() - new Date(dateStr).getTime()
  const min = Math.floor(diffMs / 60000)
  if (min < 1) return 'только что'
  if (min < 60) return `${min} мин назад`
  const h = Math.floor(min / 60)
  if (h < 24) return `${h} ч назад`
  const d = Math.floor(h / 24)
  return `${d} дн назад`
}

function isStale(task) {
  if (!task?.updated_at) return false
  if (task.status !== 'running') return false
  const diffMs = Date.now() - new Date(task.updated_at).getTime()
  return diffMs > 10 * 60 * 1000
}

function isSysStale(run) {
  if (!run?.updated_at) return false
  if (run.status !== 'running') return false
  const diffMs = Date.now() - new Date(run.updated_at).getTime()
  return diffMs > 10 * 60 * 1000
}

function rowClass(task) {
  if (isStale(task)) return 'table-warning'
  if (task.status === 'failed') return 'table-danger'
  return ''
}

function sysRowClass(run) {
  if (isSysStale(run)) return 'table-warning'
  if (run.status === 'failure') return 'table-danger'
  return ''
}

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

function sysStatusPillClass(status) {
  const map = {
    running: 'vp-pill-badge-info',
    success: 'vp-pill-badge-success',
    failure: 'vp-pill-badge-danger'
  }
  return map[status] || 'vp-pill-badge-neutral'
}

function statusProgressClass(status) {
  const map = {
    running: 'bg-primary',
    completed: 'bg-success',
    failed: 'bg-danger',
    paused: 'bg-warning',
    stopped: 'bg-secondary',
    pending: 'bg-secondary'
  }
  return map[status] || 'bg-secondary'
}

function syncQueryParams() {
  router.replace({
    query: {
      ...(filters.value.source       && { source: filters.value.source }),
      ...(filters.value.parsing_mode && { parsing_mode: filters.value.parsing_mode }),
      ...(filters.value.status       && { status: filters.value.status }),
      ...(searchQuery.value          && { search: searchQuery.value }),
      ...(currentPage.value > 1      && { page: currentPage.value })
    }
  })
}

let searchTimer = null
function handleSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { currentPage.value = 1; syncQueryParams(); loadData() }, 300)
}
function clearSearch() {
  searchQuery.value = ''
  currentPage.value = 1
  syncQueryParams()
  loadData()
}
function applyFilters() {
  currentPage.value = 1
  syncQueryParams()
  loadData()
}
function resetFilters() {
  filters.value = { source: '', parsing_mode: '', status: '' }
  searchQuery.value = ''
  currentPage.value = 1
  syncQueryParams()
  loadData()
}
function changePage(page) {
  currentPage.value = page
  syncQueryParams()
  loadData()
}

async function pauseTask(id) {
  try { await tasksApi.pause(id); toast.info('Задача приостанавливается...'); setTimeout(loadData, 1000) }
  catch (e) { toast.error('Ошибка приостановки') }
}
async function resumeTask(id) {
  try { await tasksApi.resume(id); toast.info('Задача возобновляется...'); setTimeout(loadData, 1000) }
  catch (e) { toast.error('Ошибка возобновления') }
}
async function confirmStop(task) {
  const ok = await confirmDialogRef.value?.open({ title: 'Остановить задачу?', message: `Задача «${task.name}» будет остановлена.`, confirmText: 'Остановить', confirmVariant: 'danger' })
  if (!ok) return
  try { await tasksApi.stop(task.id); toast.warning('Задача останавливается...'); setTimeout(loadData, 1000) }
  catch (e) { toast.error('Ошибка остановки') }
}
async function confirmDelete(task) {
  const ok = await confirmDialogRef.value?.open({ title: 'Удалить задачу?', message: `Задача «${task.name}» будет удалена безвозвратно.`, confirmText: 'Удалить', confirmVariant: 'danger' })
  if (!ok) return
  try { await tasksApi.delete(task.id); toast.success('Задача удалена'); loadData() }
  catch (e) { toast.error('Ошибка удаления') }
}
function onTaskCreated() { loadData() }

function resetSystemFilters() {
  sysFilters.value = { status: '', source: '', search: '' }
  sysCurrentPage.value = 1
  loadSystemRuns()
}
function handleSystemSearch() {
  clearTimeout(sysSearchTimer)
  sysSearchTimer = setTimeout(() => { sysCurrentPage.value = 1; loadSystemRuns() }, 300)
}
function clearSystemSearch() {
  sysFilters.value.search = ''
  sysCurrentPage.value = 1
  loadSystemRuns()
}
function changeSystemPage(page) {
  sysCurrentPage.value = page
  loadSystemRuns()
}

function jobTitle(run) {
  const byCelery = systemJobs.value.find(j => j.celery_task_name === run.task_name)
  if (byCelery) return byCelery.title
  const byAttr = systemJobs.value.find(j => j.task_attr === run.task_name)
  return byAttr?.title || 'Системный job'
}

onMounted(() => {
  if (route.query.search) searchQuery.value = route.query.search
  if (route.query.page) currentPage.value = parseInt(route.query.page) || 1
  loadData()
  refreshTimer = setInterval(() => { if (hasActiveTasks.value) loadData() }, 10000)
})
onUnmounted(() => { clearInterval(refreshTimer); clearTimeout(searchTimer); clearTimeout(sysSearchTimer) })
</script>

<style lang="scss" scoped>
@import '../scss/main';
</style>
