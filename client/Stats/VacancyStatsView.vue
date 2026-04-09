<template>
  <div class="vp-page p-4">
    <div class="vp-page-header">
      <div class="vp-page-title">
        <div class="vp-page-icon">
          <BarChart2 :size="20" />
        </div>
        <div>
          <h1>Статистика вакансий</h1>
          <p>Аналитика по источникам, городам и технологиям</p>
        </div>
      </div>
      <div class="d-flex gap-2">
        <select v-model="selectedSource" class="form-select form-select-sm" style="width: auto;" @change="loadStats">
          <option value="headhunter">HeadHunter</option>
          <option value="superjob">SuperJob</option>
          <option value="habr_career">Habr Career</option>
        </select>
        <button class="btn btn-outline-secondary btn-sm d-flex align-items-center gap-1" @click="loadStats" :disabled="loading">
          <RefreshCw :size="14" :class="{ 'vp-spinner': loading }" />
          Обновить
        </button>
      </div>
    </div>

    <StateLoading v-if="loading && !stats" />
    <StateError v-else-if="error && !stats" :message="error" @retry="loadStats" />

    <div v-else-if="stats">
      <!-- Метрики -->
      <div class="row g-3 mb-4">
        <div class="col-6 col-lg-3" v-for="metric in metrics" :key="metric.label">
          <div class="vp-stat-card p-3">
            <div class="d-flex align-items-center gap-3">
              <div class="vp-stat-icon" :class="metric.iconBg">
                <component :is="metric.icon" :size="20" :class="metric.iconColor" />
              </div>
              <div>
                <div class="vp-stat-value">{{ metric.value }}</div>
                <div class="vp-stat-label">{{ metric.label }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="row g-4">
        <!-- Топ городов -->
        <div class="col-lg-6" v-if="topCities.length">
          <div class="vp-card p-3">
            <h6 class="fw-semibold mb-3 d-flex align-items-center gap-2">
              <MapPin :size="16" class="text-secondary" />
              Топ городов
            </h6>
            <apexchart
              type="bar"
              height="280"
              :options="citiesChartOptions"
              :series="citiesSeries"
            />
          </div>
        </div>

        <!-- Топ ролей/технологий -->
        <div class="col-lg-6" v-if="topRoles.length">
          <div class="vp-card p-3">
            <h6 class="fw-semibold mb-3 d-flex align-items-center gap-2">
              <Briefcase :size="16" class="text-secondary" />
              {{ selectedSource === 'headhunter' ? 'Топ профессиональных ролей' : 'Топ вакансий' }}
            </h6>
            <apexchart
              type="bar"
              height="280"
              :options="rolesChartOptions"
              :series="rolesSeries"
            />
          </div>
        </div>

        <!-- Распределение по опыту -->
        <div class="col-lg-6" v-if="experienceData.length">
          <div class="vp-card p-3">
            <h6 class="fw-semibold mb-3 d-flex align-items-center gap-2">
              <Award :size="16" class="text-secondary" />
              Распределение по опыту
            </h6>
            <apexchart
              type="donut"
              height="280"
              :options="experienceChartOptions"
              :series="experienceSeries"
            />
          </div>
        </div>

        <!-- Диапазон зарплат -->
        <div class="col-lg-6" v-if="stats.salary_from_avg || stats.salary_to_avg">
          <div class="vp-card p-3">
            <h6 class="fw-semibold mb-3 d-flex align-items-center gap-2">
              <TrendingUp :size="16" class="text-secondary" />
              Зарплаты
            </h6>
            <div class="row g-3 text-center">
              <div class="col-6">
                <div class="p-3 rounded-2 bg-success bg-opacity-10">
                  <div class="vp-salary" style="font-size:1.25rem;">{{ formatSalary(stats.salary_from_avg) }}</div>
                  <div class="text-secondary mt-1" style="font-size:0.8125rem;">Средняя «от»</div>
                </div>
              </div>
              <div class="col-6">
                <div class="p-3 rounded-2 bg-primary bg-opacity-10">
                  <div class="vp-salary" style="font-size:1.25rem; color: var(--bs-primary) !important;">{{ formatSalary(stats.salary_to_avg) }}</div>
                  <div class="text-secondary mt-1" style="font-size:0.8125rem;">Средняя «до»</div>
                </div>
              </div>
              <div class="col-6">
                <div class="p-3 rounded-2 bg-body-secondary">
                  <div class="fw-bold" style="font-size:1.125rem;">{{ formatSalary(stats.salary_min) }}</div>
                  <div class="text-secondary mt-1" style="font-size:0.8125rem;">Минимум</div>
                </div>
              </div>
              <div class="col-6">
                <div class="p-3 rounded-2 bg-body-secondary">
                  <div class="fw-bold" style="font-size:1.125rem;">{{ formatSalary(stats.salary_max) }}</div>
                  <div class="text-secondary mt-1" style="font-size:0.8125rem;">Максимум</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <StateEmpty v-else title="Нет данных" description="Выберите источник и нажмите «Обновить»" />
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { BarChart2, RefreshCw, MapPin, Briefcase, Award, TrendingUp, Database, Activity, CalendarDays, DollarSign } from 'lucide-vue-next'
import VueApexCharts from 'vue3-apexcharts'
import { sourceApi } from '../js/api'
import StateLoading from '../components/StateLoading.vue'
import StateEmpty from '../components/StateEmpty.vue'
import StateError from '../components/StateError.vue'

const apexchart = VueApexCharts

const selectedSource = ref('headhunter')
const stats = ref(null)
const loading = ref(false)
const error = ref(null)

const metrics = computed(() => {
  if (!stats.value) return []
  return [
    { label: 'Всего вакансий', value: stats.value.total?.toLocaleString() || '0', icon: Database, iconBg: 'bg-primary bg-opacity-10', iconColor: 'text-primary' },
    { label: 'Активных',       value: stats.value.active?.toLocaleString() || '0', icon: Activity, iconBg: 'bg-success bg-opacity-10', iconColor: 'text-success' },
    { label: 'За 7 дней',      value: stats.value.recent?.toLocaleString() || stats.value.recent_7_days?.toLocaleString() || '0', icon: CalendarDays, iconBg: 'bg-info bg-opacity-10', iconColor: 'text-info' },
    { label: 'Средняя зарплата', value: formatSalary(stats.value.salary_from_avg || stats.value.avg_salary_from), icon: DollarSign, iconBg: 'bg-warning bg-opacity-10', iconColor: 'text-warning' }
  ]
})

const topCities = computed(() => {
  const data = stats.value?.top_cities || stats.value?.cities || []
  return Array.isArray(data) ? data.slice(0, 10) : []
})
const topRoles = computed(() => {
  const data = stats.value?.top_roles || stats.value?.top_vacancies || stats.value?.roles || []
  return Array.isArray(data) ? data.slice(0, 10) : []
})
const experienceData = computed(() => {
  const data = stats.value?.experience_distribution || stats.value?.experience || []
  return Array.isArray(data) ? data : []
})

const chartBaseOptions = {
  chart: { toolbar: { show: false }, fontFamily: 'inherit' },
  tooltip: { theme: 'dark' },
  grid: { borderColor: 'rgba(128,128,128,0.15)', strokeDashArray: 4 }
}

const citiesChartOptions = computed(() => ({
  ...chartBaseOptions,
  xaxis: { categories: topCities.value.map(c => c.city || c.name || c[0]) },
  plotOptions: { bar: { horizontal: true, borderRadius: 4, dataLabels: { position: 'top' } } },
  dataLabels: { enabled: false },
  colors: ['#0d6efd']
}))
const citiesSeries = computed(() => [{
  name: 'Вакансий',
  data: topCities.value.map(c => c.count || c[1] || 0)
}])

const rolesChartOptions = computed(() => ({
  ...chartBaseOptions,
  xaxis: { categories: topRoles.value.map(r => r.role || r.name || r.title || r[0]) },
  plotOptions: { bar: { horizontal: true, borderRadius: 4 } },
  dataLabels: { enabled: false },
  colors: ['#198754']
}))
const rolesSeries = computed(() => [{
  name: 'Вакансий',
  data: topRoles.value.map(r => r.count || r[1] || 0)
}])

const experienceChartOptions = computed(() => ({
  ...chartBaseOptions,
  labels: experienceData.value.map(e => e.experience || e.label || e[0] || 'Не указан'),
  legend: { position: 'bottom' },
  colors: ['#0d6efd', '#198754', '#ffc107', '#dc3545', '#0dcaf0']
}))
const experienceSeries = computed(() => experienceData.value.map(e => e.count || e[1] || 0))

function formatSalary(val) {
  if (!val) return '—'
  return Math.round(val).toLocaleString('ru-RU') + ' ₽'
}

async function loadStats() {
  loading.value = true
  error.value = null
  try {
    const r = await sourceApi.getStats(selectedSource.value)
    stats.value = r.data || r
  } catch (e) {
    error.value = e.message || 'Ошибка загрузки статистики'
  } finally {
    loading.value = false
  }
}

loadStats()
</script>

<style lang="scss" scoped>
@import '../scss/main';
</style>
