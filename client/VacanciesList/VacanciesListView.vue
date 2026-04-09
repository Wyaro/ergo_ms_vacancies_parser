<template>
  <div class="vp-page p-4">
    <div class="vp-cc-header d-flex flex-column flex-lg-row align-items-lg-center justify-content-between gap-2 mb-3">
      <div class="d-flex align-items-center gap-2">
        <div class="vp-cc-title-icon d-flex align-items-center justify-content-center">
          <BriefcaseBusiness :size="22" :stroke-width="1.7" />
        </div>
        <div>
          <h2 class="mb-1 d-flex align-items-center gap-2">
            Вакансии
            <span class="badge vp-pill-badge vp-pill-badge-accent">Всего: {{ totalCount }}</span>
          </h2>
          <div class="text-muted small d-flex flex-wrap align-items-center gap-3">
            <span class="d-inline-flex align-items-center gap-1">
              <ListChecks :size="14" /> Показано: {{ vacancies.length }}
            </span>
            <span class="d-inline-flex align-items-center gap-1" v-if="lastLoadedAt">
              <Clock3 :size="14" /> Обновлено: {{ lastLoadedAt }}
            </span>
          </div>
        </div>
      </div>
      <div class="d-flex gap-2 flex-wrap">
        <button
          class="btn btn-outline-secondary btn-sm d-flex align-items-center gap-1"
          @click="loadData"
          :disabled="loading"
        >
          <RefreshCw :size="14" :class="{ 'vp-spinner': loading }" />
          Обновить
        </button>
        <button
          class="btn btn-outline-success btn-sm d-flex align-items-center gap-1"
          @click="exportCsv"
          :disabled="exporting"
        >
          <span v-if="exporting" class="spinner-border spinner-border-sm"></span>
          <Download v-else :size="14" />
          Экспорт CSV
        </button>
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
          <button type="button" class="btn btn-link btn-sm text-decoration-none p-0" @click="resetFilters">
            Сбросить
          </button>
        </div>
        <div class="row g-2 align-items-end">
          <div class="col-12 col-md-5">
            <div class="input-group input-group-sm">
              <span class="input-group-text"><Search :size="14" /></span>
              <input
                v-model="filters.search"
                type="text"
                class="form-control"
                placeholder="Поиск по названию, компании..."
                @input="handleSearch"
              />
              <button v-if="filters.search" class="btn btn-outline-secondary" @click="clearSearch">
                <X :size="14" />
              </button>
            </div>
          </div>
          <div class="col-6 col-sm-4 col-md-2">
            <select v-model="filters.city" class="form-select form-select-sm" @change="applyFilters">
              <option value="">Все города</option>
              <option v-for="city in cities" :key="city" :value="city">{{ city }}</option>
            </select>
          </div>
          <div class="col-6 col-sm-12 col-md-1">
            <button class="btn btn-outline-secondary btn-sm w-100" @click="resetFilters" title="Сброс фильтров">
              <FilterX :size="14" />
            </button>
          </div>
        </div>
        <div class="mt-2 d-flex gap-2 flex-wrap">
          <div v-for="src in sources" :key="src.value" class="form-check form-check-inline mb-0">
            <input
              class="form-check-input"
              type="checkbox"
              :id="`src-${src.value}`"
              :value="src.value"
              v-model="filters.sources"
              @change="applyFilters"
            />
            <label class="form-check-label" :for="`src-${src.value}`" style="font-size:0.8125rem;">
              <span class="badge vp-pill-badge vp-pill-badge-neutral">{{ src.label }}</span>
            </label>
          </div>
        </div>
      </div>
    </div>

    <!-- Результаты -->
    <div class="d-flex align-items-center justify-content-between mb-2" v-if="!loading">
      <small class="text-secondary">
        Найдено: <strong>{{ totalCount }}</strong> вакансий
      </small>
    </div>

    <StateLoading v-if="loading && vacancies.length === 0" />
    <StateError v-else-if="error && vacancies.length === 0" :message="error" @retry="loadData" />
    <StateEmpty
      v-else-if="!loading && vacancies.length === 0"
      title="Вакансии не найдены"
      description="Попробуйте изменить параметры фильтрации"
      icon="search"
    />

    <div v-else class="table-responsive">
      <table class="table table-hover align-middle vp-table">
        <thead>
          <tr>
            <th>Вакансия</th>
            <th class="d-none d-md-table-cell">Источник</th>
            <th class="d-none d-lg-table-cell">Зарплата</th>
            <th class="d-none d-lg-table-cell">Статус</th>
            <th class="text-end">Дата</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="vacancy in vacancies" :key="vacancy.id">
            <td>
              <div class="fw-semibold">{{ vacancy.title }}</div>
              <div class="text-muted small">
                {{ vacancy.company_name || '—' }}
                <span v-if="vacancy.area_name"> · {{ vacancy.area_name }}</span>
                <span v-if="vacancy.experience"> · {{ vacancy.experience }}</span>
              </div>
            </td>
            <td class="d-none d-md-table-cell">
              <span class="badge vp-pill-badge vp-pill-badge-source">{{ vacancy.source_display || sourceLabel(vacancy.source) }}</span>
            </td>
            <td class="d-none d-lg-table-cell">
              <span v-if="vacancy.salary_display" class="fw-semibold">{{ vacancy.salary_display }}</span>
              <span v-else class="text-muted small">—</span>
            </td>
            <td class="d-none d-lg-table-cell">
              <span class="badge vp-pill-badge" :class="statusBadgeClass(vacancy)">
                {{ statusText(vacancy) }}
              </span>
            </td>
            <td class="text-end">
              <div class="d-flex flex-column align-items-end gap-1">
                <div class="text-muted small">{{ formatDateTime(vacancy.published_at || vacancy.created_at) }}</div>
              </div>
            </td>
            <td class="text-end">
              <div class="d-flex justify-content-end align-items-center gap-2">
                <button class="btn btn-sm btn-outline-primary" type="button" @click="$router.push({ name: 'VacancyDetail', params: { id: vacancy.id } })">
                  Открыть
                </button>
                <a
                  v-if="vacancy.source_url"
                  class="btn btn-sm btn-outline-secondary"
                  :href="vacancy.source_url"
                  target="_blank"
                  rel="noopener"
                >
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
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { BriefcaseBusiness, RefreshCw, Download, Search, X, FilterX, Filter, ListChecks, Clock3 } from 'lucide-vue-next'
import { useToast } from 'vue-toastification'
import { vacanciesApi } from '../js/api'
import StateLoading from '../components/StateLoading.vue'
import StateEmpty from '../components/StateEmpty.vue'
import StateError from '../components/StateError.vue'
import Pagination from '../components/Pagination.vue'

const route  = useRoute()
const router = useRouter()
const toast  = useToast()

const vacancies  = ref([])
const loading    = ref(false)
const error      = ref(null)
const exporting  = ref(false)
const totalCount = ref(0)
const currentPage = ref(1)
const pageSize = 21
const lastLoadedAt = ref('')

const filters = ref({
  search: route.query.search || '',
  city: route.query.area_name || '',
  sources: route.query.sources ? String(route.query.sources).split(',') : []
})

const sources = [
  { value: 'headhunter', label: 'HeadHunter' },
  { value: 'superjob',   label: 'SuperJob' },
  { value: 'habr_career', label: 'Habr Career' }
]
const cities = ['Москва', 'Санкт-Петербург', 'Новосибирск', 'Екатеринбург', 'Казань', 'Нижний Новгород']

const totalPages = computed(() => Math.ceil(totalCount.value / pageSize))

function sourceLabel(src) {
  return { headhunter: 'HeadHunter', superjob: 'SuperJob', habr_career: 'Habr Career' }[src] || src
}
function formatDate(d) {
  if (!d) return '—'
  return new Date(d).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' })
}
function formatDateTime(d) {
  if (!d) return '—'
  return new Date(d).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function statusText(v) {
  if (v?.archived) return 'Архив'
  if (v?.is_active === true) return 'Активна'
  if (v?.is_active === false) return 'Неактивна'
  return '—'
}
function statusBadgeClass(v) {
  if (v?.archived) return 'vp-pill-badge-neutral'
  if (v?.is_active === true) return 'vp-pill-badge-success'
  if (v?.is_active === false) return 'vp-pill-badge-neutral'
  return 'vp-pill-badge-neutral'
}

function buildParams() {
  const p = { page: currentPage.value, page_size: pageSize }
  if (filters.value.search) p.search = filters.value.search
  if (filters.value.city) p.area_name = filters.value.city
  if (filters.value.sources.length) p.sources = filters.value.sources.join(',')
  return p
}

function normalizeQueryForCompare(q) {
  const obj = {
    search: q?.search ? String(q.search) : '',
    area_name: q?.area_name ? String(q.area_name) : '',
    sources: q?.sources ? String(q.sources) : '',
    page: q?.page ? String(q.page) : ''
  }
  return Object.fromEntries(Object.entries(obj).filter(([, v]) => v !== ''))
}

async function loadData() {
  loading.value = true
  error.value = null
  try {
    const r = await vacanciesApi.list(buildParams())
    const data = r.data
    vacancies.value = Array.isArray(data?.results) ? data.results : (Array.isArray(data) ? data : [])
    totalCount.value = data?.count || vacancies.value.length
    lastLoadedAt.value = new Date().toLocaleString('ru-RU', { hour: '2-digit', minute: '2-digit' })
  } catch (e) {
    error.value = e.message || 'Ошибка загрузки вакансий'
  } finally {
    loading.value = false
  }
}

function syncQuery() {
  const q = {}
  if (filters.value.search) q.search = filters.value.search
  if (filters.value.sources.length) q.sources = filters.value.sources.join(',')
  if (filters.value.city) q.area_name = filters.value.city
  if (currentPage.value > 1) q.page = currentPage.value
  const curNorm = normalizeQueryForCompare(route.query)
  const nextNorm = normalizeQueryForCompare(q)
  if (JSON.stringify(curNorm) === JSON.stringify(nextNorm)) return
  router.replace({ query: q })
}

let searchTimer = null
function handleSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { currentPage.value = 1; syncQuery() }, 300)
}
function clearSearch() {
  filters.value.search = ''
  currentPage.value = 1
  syncQuery()
}
function applyFilters() {
  currentPage.value = 1
  syncQuery()
}
function resetFilters() {
  filters.value = { search: '', city: '', sources: [] }
  currentPage.value = 1
  syncQuery()
}
function changePage(p) {
  currentPage.value = p
  syncQuery()
}

async function exportCsv() {
  exporting.value = true
  try {
    const r = await vacanciesApi.exportCsv(buildParams())
    const blob = r?.data instanceof Blob ? r.data : null
    if (!r?.success || !blob) {
      throw new Error('Некорректный ответ при экспорте')
    }
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `vacancies_${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(url)
    toast.success('Экспорт завершён')
  } catch (e) {
    toast.error('Ошибка экспорта')
  } finally {
    exporting.value = false
  }
}

onMounted(() => {})

let routeHydrated = false
watch(
  () => route.query,
  (q) => {
    const nextPage = q?.page ? (parseInt(String(q.page)) || 1) : 1
    const nextSearch = q?.search ? String(q.search) : ''
    const nextCity = q?.area_name ? String(q.area_name) : ''
    const nextSources = q?.sources ? String(q.sources).split(',').filter(Boolean) : []

    const changed =
      nextPage !== currentPage.value ||
      nextSearch !== filters.value.search ||
      nextCity !== filters.value.city ||
      JSON.stringify(nextSources) !== JSON.stringify(filters.value.sources)

    if (routeHydrated && !changed) return

    currentPage.value = nextPage
    filters.value.search = nextSearch
    filters.value.city = nextCity
    filters.value.sources = nextSources
    loadData()
    routeHydrated = true
  },
  { immediate: true }
)
</script>

<style lang="scss" scoped>
@import '../scss/main';
</style>
