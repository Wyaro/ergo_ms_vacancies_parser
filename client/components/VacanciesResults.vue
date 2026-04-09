<template>
  <div class="vp-page p-4">
    <div class="vp-cc-header d-flex flex-column flex-lg-row align-items-lg-center justify-content-between gap-2 mb-3">
      <div class="d-flex align-items-center gap-2">
        <div class="vp-cc-title-icon d-flex align-items-center justify-content-center">
          <Database :size="22" :stroke-width="1.7" />
        </div>
        <div>
          <h2 class="mb-1 d-flex align-items-center gap-2">
            Результаты парсинга
            <span class="badge vp-pill-badge vp-pill-badge-accent">Всего: {{ totalCount }}</span>
          </h2>
          <div class="text-muted small">Сырые данные вакансий из источников</div>
        </div>
      </div>
      <button class="btn btn-outline-secondary btn-sm d-flex align-items-center gap-1" @click="loadData">
        <RefreshCw :size="14" />
        Обновить
      </button>
    </div>

    <!-- Счётчики -->
    <div class="row g-3 mb-3">
      <div class="col-6 col-sm-4">
        <div class="card shadow-sm border-0 h-100 vp-kpi-card vp-kpi-accent-primary">
          <div class="d-flex align-items-center gap-3">
            <div class="vp-stat-icon bg-primary bg-opacity-10">
              <Database :size="18" class="text-primary" />
            </div>
            <div>
              <div class="vp-stat-value">{{ totalCount }}</div>
              <div class="vp-stat-label">Всего вакансий</div>
            </div>
          </div>
        </div>
      </div>
      <div class="col-6 col-sm-4">
        <div class="card shadow-sm border-0 h-100 vp-kpi-card vp-kpi-accent-success">
          <div class="d-flex align-items-center gap-3">
            <div class="vp-stat-icon bg-success bg-opacity-10">
              <CheckCircle2 :size="18" class="text-success" />
            </div>
            <div>
              <div class="vp-stat-value">{{ activeCount }}</div>
              <div class="vp-stat-label">Активных</div>
            </div>
          </div>
        </div>
      </div>
      <div class="col-6 col-sm-4">
        <div class="card shadow-sm border-0 h-100 vp-kpi-card vp-kpi-accent-info">
          <div class="d-flex align-items-center gap-3">
            <div class="vp-stat-icon bg-info bg-opacity-10">
              <CalendarDays :size="18" class="text-info" />
            </div>
            <div>
              <div class="vp-stat-value">{{ todayCount }}</div>
              <div class="vp-stat-label">Сегодня</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Фильтры -->
    <div class="card shadow-sm border-0 mb-3 vp-filters-card">
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
        <div class="row g-2">
          <div class="col-12 col-sm-6 col-lg-4">
            <div class="input-group input-group-sm">
              <span class="input-group-text"><Search :size="14" /></span>
              <input v-model="filters.search" type="text" class="form-control" placeholder="Поиск..." @input="handleSearch" />
              <button v-if="filters.search" class="btn btn-outline-secondary" @click="clearSearch"><X :size="14" /></button>
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
            <input v-model="filters.company" type="text" class="form-control form-control-sm" placeholder="Компания" @input="handleSearch" />
          </div>
          <div class="col-6 col-sm-3 col-lg-2">
            <input v-model="filters.city" type="text" class="form-control form-control-sm" placeholder="Город" @input="handleSearch" />
          </div>
          <div class="col-6 col-sm-3 col-lg-2">
            <button class="btn btn-outline-secondary btn-sm w-100 d-flex align-items-center justify-content-center gap-1" @click="resetFilters">
              <FilterX :size="14" />Сброс
            </button>
          </div>
        </div>
      </div>
    </div>

    <StateLoading v-if="loading && items.length === 0" />
    <StateError v-else-if="error && items.length === 0" :message="error" @retry="loadData" />
    <StateEmpty
      v-else-if="!loading && items.length === 0"
      title="Результаты не найдены"
      :description="filters.source ? 'Запустите задачи парсинга для получения данных' : 'Выберите источник в фильтре, чтобы просмотреть сырые вакансии'"
      icon="inbox"
    />

    <div v-else class="table-responsive">
      <table class="table table-hover align-middle vp-table">
        <thead>
          <tr>
            <th>Вакансия</th>
            <th class="d-none d-md-table-cell">Источник</th>
            <th class="d-none d-lg-table-cell">Зарплата</th>
            <th class="text-end">Дата</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in items" :key="item.id">
            <td>
              <div class="fw-semibold">{{ item.title || item.name || '—' }}</div>
              <div class="text-muted small">
                {{ item.company_name || item.employer?.name || '—' }}
                <span v-if="item.city || item.area?.name"> · {{ item.city || item.area?.name }}</span>
              </div>
            </td>
            <td class="d-none d-md-table-cell">
              <span class="badge vp-pill-badge vp-pill-badge-source">{{ sourceLabel(item.source || filters.source) }}</span>
            </td>
            <td class="d-none d-lg-table-cell">
              <span v-if="item.salary_from || item.salary_to" class="fw-semibold">
                {{ formatSalary(item.salary_from, item.salary_to, item.salary_currency) }}
              </span>
              <span v-else class="text-muted small">—</span>
            </td>
            <td class="text-end">
              <div class="text-muted small">{{ formatDateTime(item.published_at || item.created_at) }}</div>
            </td>
            <td class="text-end">
              <div class="d-flex justify-content-end align-items-center gap-2">
                <a v-if="item.url || item.alternate_url" :href="item.url || item.alternate_url" target="_blank" rel="noopener" class="btn btn-sm btn-outline-secondary">
                  Сайт
                </a>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      <Pagination v-if="totalPages > 1" v-model="currentPage" :total-pages="totalPages" @update:model-value="changePage" class="mt-3" />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Database, RefreshCw, Search, X, FilterX, CheckCircle2, CalendarDays, Filter } from 'lucide-vue-next'
import { useToast } from 'vue-toastification'
import { sourceApi } from '../js/api'
import StateLoading from './StateLoading.vue'
import StateEmpty from './StateEmpty.vue'
import StateError from './StateError.vue'
import Pagination from './Pagination.vue'

const toast = useToast()
const items = ref([])
const loading = ref(false)
const error = ref(null)
const totalCount = ref(0)
const activeCount = ref(0)
const todayCount = ref(0)
const currentPage = ref(1)
const pageSize = 20

const filters = ref({ search: '', source: '', company: '', city: '' })
const totalPages = computed(() => Math.ceil(totalCount.value / pageSize))

function sourceLabel(src) {
  return { headhunter: 'HeadHunter', superjob: 'SuperJob', habr_career: 'Habr Career' }[src] || (src || '—')
}
function formatSalary(from, to, currency = 'RUB') {
  const c = currency === 'RUB' ? '₽' : currency
  if (from && to) return `${from.toLocaleString()} – ${to.toLocaleString()} ${c}`
  if (from) return `от ${from.toLocaleString()} ${c}`
  if (to) return `до ${to.toLocaleString()} ${c}`
  return ''
}
function formatDate(d) {
  if (!d) return '—'
  return new Date(d).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' })
}
function formatDateTime(d) {
  if (!d) return '—'
  return new Date(d).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' })
}

async function loadData() {
  if (!filters.value.source) {
    items.value = []
    totalCount.value = 0
    activeCount.value = 0
    todayCount.value = 0
    return
  }
  loading.value = true
  error.value = null
  try {
    const searchText = [filters.value.search, filters.value.company].map(v => String(v || '').trim()).filter(Boolean).join(' ')
    const params = {
      page: currentPage.value,
      page_size: pageSize,
      ...(searchText && { search: searchText }),
      ...(filters.value.city && { city: filters.value.city })
    }
    const r = await sourceApi.getVacancies(filters.value.source, params)
    const data = r.data
    items.value = Array.isArray(data?.results) ? data.results : (Array.isArray(data) ? data : [])
    totalCount.value = data?.count || items.value.length
    activeCount.value = items.value.filter(i => i.status === 'active' || i.is_active).length
    const today = new Date().toLocaleDateString('ru-RU')
    todayCount.value = items.value.filter(i => {
      const d = i.created_at || i.published_at
      return d && new Date(d).toLocaleDateString('ru-RU') === today
    }).length
  } catch (e) {
    error.value = e.message || 'Ошибка загрузки'
  } finally {
    loading.value = false
  }
}

let searchTimer = null
function handleSearch() { clearTimeout(searchTimer); searchTimer = setTimeout(() => { currentPage.value = 1; loadData() }, 300) }
function clearSearch() { filters.value.search = ''; currentPage.value = 1; loadData() }
function applyFilters() { currentPage.value = 1; loadData() }
function resetFilters() { filters.value = { search: '', source: '', company: '', city: '' }; currentPage.value = 1; loadData() }
function changePage(p) { currentPage.value = p; loadData() }

onMounted(() => {
  // Источник обязателен для source-specific эндпоинтов.
  // Чтобы “Результаты” не выглядели пустыми, выбираем дефолтный источник.
  if (!filters.value.source) {
    filters.value.source = 'headhunter'
  }
  loadData()
})
</script>

<style lang="scss" scoped>
@import '../scss/main';
</style>
