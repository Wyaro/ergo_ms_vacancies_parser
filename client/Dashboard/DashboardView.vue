<template>
  <div class="vp-page p-4">
    <div class="vp-cc-header d-flex flex-column flex-lg-row align-items-lg-center justify-content-between gap-2 mb-3">
      <div class="d-flex align-items-center gap-2">
        <div class="vp-cc-title-icon d-flex align-items-center justify-content-center">
          <LayoutDashboard :size="22" :stroke-width="1.7" />
        </div>
        <div>
          <h2 class="mb-1 d-flex align-items-center gap-2">
            Дашборд
            <span class="badge vp-pill-badge vp-pill-badge-accent">Задачи: {{ tasks.length }}</span>
          </h2>
          <div class="text-muted small">Обзор задач парсинга и расписание</div>
        </div>
      </div>
      <div class="d-flex gap-2">
        <button class="btn btn-outline-secondary btn-sm d-flex align-items-center gap-1" @click="loadData">
          <RefreshCw :size="14" :class="{ 'vp-spinner': loading }" />
          Обновить
        </button>
        <RouterLink :to="{ name: 'VacanciesParser' }" class="btn btn-primary btn-sm d-flex align-items-center gap-1">
          <Plus :size="14" />
          Новая задача
        </RouterLink>
      </div>
    </div>

    <!-- Статистика -->
    <div class="row g-3 mb-4">
      <div class="col-6 col-lg-3" v-for="stat in stats" :key="stat.key">
        <div class="card shadow-sm border-0 h-100 vp-kpi-card" :class="stat.kpiVariant">
          <div class="d-flex align-items-center gap-3">
            <div class="vp-stat-icon" :class="stat.iconBg">
              <component :is="stat.icon" :size="20" :class="stat.iconColor" />
            </div>
            <div>
              <div class="vp-stat-value">{{ stat.value }}</div>
              <div class="vp-stat-label">{{ stat.label }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="row g-4">
      <!-- Активные задачи -->
      <div class="col-lg-5">
        <div class="vp-card p-0 h-100">
          <div class="d-flex align-items-center justify-content-between px-3 py-2 border-bottom">
            <h6 class="mb-0 fw-semibold d-flex align-items-center gap-2">
              <Activity :size="16" class="text-primary" />
              Активные задачи
              <span class="badge bg-primary rounded-pill">{{ activeTasks.length }}</span>
            </h6>
            <RouterLink :to="{ name: 'VacanciesParser' }" class="text-secondary" style="font-size:0.8125rem;">
              Все задачи
            </RouterLink>
          </div>
          <div v-if="activeTasks.length === 0" class="vp-empty-state py-4">
            <div class="vp-empty-icon">
              <CheckCircle2 :size="24" />
            </div>
            <h5 style="font-size:0.9375rem;">Нет активных задач</h5>
            <p style="font-size:0.8125rem;">Все задачи выполнены</p>
          </div>
          <ul class="list-group list-group-flush" v-else>
            <li
              v-for="task in activeTasks"
              :key="task.id"
              class="list-group-item px-3 py-2"
            >
              <div class="d-flex align-items-center justify-content-between mb-1">
                <div class="d-flex align-items-center gap-2 min-w-0">
                  <span class="badge vp-pill-badge vp-pill-badge-source" style="flex-shrink:0;">
                    {{ sourceLabel(task.source) }}
                  </span>
                  <span class="text-truncate fw-medium" style="font-size:0.875rem;">{{ task.name }}</span>
                </div>
                <span class="badge vp-pill-badge flex-shrink-0" :class="statusPillClass(task.status)">
                  {{ task.status_display || task.status }}
                </span>
              </div>
              <TaskProgressBar
                :completed="task.progress?.completed_items || 0"
                :total="task.progress?.total_items || 0"
                :failed="task.progress?.failed_items || 0"
                :status="task.status"
                :show-counts="true"
                label=""
              />
            </li>
          </ul>
        </div>
      </div>

      <!-- Последние задачи -->
      <div class="col-lg-7">
        <div class="vp-card p-0">
          <div class="d-flex align-items-center justify-content-between px-3 py-2 border-bottom">
            <h6 class="mb-0 fw-semibold d-flex align-items-center gap-2">
              <ClipboardList :size="16" class="text-secondary" />
              Последние задачи
            </h6>
          </div>
          <div class="vp-table-responsive">
            <table class="table table-sm table-hover mb-0 align-middle vp-table">
              <thead>
                <tr>
                  <th class="text-secondary fw-medium" style="font-size:0.8rem;">Задача</th>
                  <th class="text-secondary fw-medium" style="font-size:0.8rem;">Источник</th>
                  <th class="text-secondary fw-medium" style="font-size:0.8rem;">Статус</th>
                  <th class="text-secondary fw-medium" style="font-size:0.8rem;">Дата</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="recentTasks.length === 0">
                  <td colspan="4" class="text-center text-secondary py-4" style="font-size:0.875rem;">Нет задач</td>
                </tr>
                <tr
                  v-for="task in recentTasks"
                  :key="task.id"
                  class="cursor-pointer"
                  @click="$router.push({ name: 'VacanciesParserTaskDetail', params: { id: task.id } })"
                >
                  <td>
                    <span class="fw-medium" style="font-size:0.875rem;">{{ task.name }}</span>
                  </td>
                  <td>
                    <span class="vp-source-badge" :class="`source-${task.source}`">
                      {{ sourceLabel(task.source) }}
                    </span>
                  </td>
                  <td>
                    <span class="badge vp-pill-badge" :class="statusPillClass(task.status)">{{ task.status_display || task.status }}</span>
                  </td>
                  <td class="text-secondary" style="font-size:0.8125rem;">{{ formatDate(task.created_at) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- Расписание Celery Beat -->
        <div class="vp-card p-0 mt-4">
          <div class="d-flex align-items-center justify-content-between px-3 py-2 border-bottom">
            <h6 class="mb-0 fw-semibold d-flex align-items-center gap-2">
              <CalendarDays :size="16" class="text-secondary" />
              Расписание Celery Beat
              <span class="badge bg-secondary bg-opacity-15 text-body rounded-pill">{{ scheduleItems.length }}</span>
            </h6>
            <button
              class="btn btn-link btn-sm p-0 text-secondary text-decoration-none"
              @click="showSchedule = !showSchedule"
              style="font-size:0.8125rem;"
            >
              {{ showSchedule ? 'Свернуть' : 'Развернуть' }}
            </button>
          </div>
          <div v-if="showSchedule" class="vp-table-responsive" style="max-height: 320px; overflow-y: auto;">
            <table class="table table-sm mb-0 align-middle vp-table">
              <thead class="sticky-top bg-body">
                <tr>
                  <th class="text-secondary fw-medium" style="font-size:0.8rem;">Задача</th>
                  <th class="text-secondary fw-medium" style="font-size:0.8rem;">Очередь</th>
                  <th class="text-secondary fw-medium" style="font-size:0.8rem;">Расписание</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in scheduleItems" :key="item.id">
                  <td>
                    <div class="fw-medium" style="font-size:0.8125rem;">{{ item.title }}</div>
                    <div class="text-secondary" style="font-size:0.75rem;">{{ item.description }}</div>
                  </td>
                  <td>
                    <span class="badge" :class="`bg-${item.queueVariant} bg-opacity-15 text-${item.queueVariant}`">
                      {{ item.queueLabel }}
                    </span>
                  </td>
                  <td class="text-secondary" style="font-size:0.8125rem; white-space: nowrap;">{{ item.frequency }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  LayoutDashboard, RefreshCw, Plus, Activity, CheckCircle2,
  ClipboardList, CalendarDays, ListChecks, AlertCircle, Loader, CheckCheck
} from 'lucide-vue-next'
import { tasksApi } from '../js/api'
import { scheduleItems } from './scheduleData'
import TaskProgressBar from '../components/TaskProgressBar.vue'

const router = useRouter()
const tasks = ref([])
const loading = ref(false)
const showSchedule = ref(false)
let refreshTimer = null

const activeTasks = computed(() => tasks.value.filter(t => t.is_active))
const recentTasks = computed(() => [...tasks.value].sort((a, b) => new Date(b.created_at) - new Date(a.created_at)).slice(0, 10))

const stats = computed(() => [
  { key: 'total',     value: tasks.value.length,                                       label: 'Всего задач',   icon: ListChecks,  iconBg: 'bg-primary bg-opacity-10', iconColor: 'text-primary', kpiVariant: 'vp-kpi-accent-primary' },
  { key: 'active',    value: activeTasks.value.length,                                 label: 'Активных',      icon: Activity,    iconBg: 'bg-info bg-opacity-10',    iconColor: 'text-info',    kpiVariant: 'vp-kpi-accent-info' },
  { key: 'completed', value: tasks.value.filter(t => t.status === 'completed').length, label: 'Завершённых',   icon: CheckCheck,  iconBg: 'bg-success bg-opacity-10', iconColor: 'text-success', kpiVariant: 'vp-kpi-accent-success' },
  { key: 'failed',    value: tasks.value.filter(t => t.status === 'failed').length,    label: 'С ошибками',    icon: AlertCircle, iconBg: 'bg-danger bg-opacity-10',  iconColor: 'text-danger',  kpiVariant: 'vp-kpi-accent-danger' }
])

const sourceNames = { headhunter: 'HH', superjob: 'SJ', habr_career: 'Habr' }
function sourceLabel(src) { return sourceNames[src] || src }
function formatDate(dateStr) {
  if (!dateStr) return '—'
  return new Date(dateStr).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' })
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

async function loadData() {
  loading.value = true
  try {
    const response = await tasksApi.list({ page_size: 50 })
    const data = response.data
    tasks.value = Array.isArray(data?.results) ? data.results : (Array.isArray(data) ? data : [])
  } catch (e) {
    // Silent refresh
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadData()
  refreshTimer = setInterval(loadData, 10000)
})
onUnmounted(() => clearInterval(refreshTimer))
</script>

<style lang="scss" scoped>
@import '../scss/main';

.cursor-pointer { cursor: pointer; }
</style>
