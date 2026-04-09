<template>
  <div class="vp-page p-4">
    <StateLoading v-if="loading && !vacancy" text="Загрузка вакансии..." />
    <StateError v-else-if="error && !vacancy" :message="error" @retry="loadVacancy" />

    <div v-else-if="vacancy">
      <div class="mb-4">
        <button class="btn btn-link btn-sm p-0 text-secondary mb-2 d-flex align-items-center gap-1 text-decoration-none" @click="$router.push({ name: 'VacanciesList' })">
          <ArrowLeft :size="14" />
          К списку вакансий
        </button>
        <div class="d-flex align-items-start justify-content-between gap-3 flex-wrap">
          <div class="min-w-0">
            <h2 class="fw-bold mb-1" style="font-size:1.375rem;">{{ vacancy.title }}</h2>
            <div class="text-secondary fw-medium fs-6">{{ vacancy.company_name }}</div>
          </div>
          <button
            class="btn btn-outline-primary btn-sm d-flex align-items-center gap-1 flex-shrink-0"
            @click="refreshVacancy"
            :disabled="refreshing"
          >
            <span v-if="refreshing" class="spinner-border spinner-border-sm"></span>
            <RefreshCw v-else :size="14" />
            Обновить данные
          </button>
        </div>
      </div>

      <div class="row g-4">
        <!-- Основной контент -->
        <div class="col-lg-8">
          <!-- Ключевые данные -->
          <div class="vp-card p-3 mb-3">
            <div class="row g-3">
              <div class="col-sm-6" v-if="vacancy.salary_from || vacancy.salary_to">
                <div class="text-secondary mb-1" style="font-size:0.75rem;">Зарплата</div>
                <div class="vp-salary">
                  {{ formatSalary(vacancy.salary_from, vacancy.salary_to, vacancy.salary_currency) }}
                </div>
              </div>
              <div class="col-sm-6" v-if="vacancy.city">
                <div class="text-secondary mb-1" style="font-size:0.75rem;">Город</div>
                <div class="d-flex align-items-center gap-1 fw-medium">
                  <MapPin :size="14" class="text-secondary" />
                  {{ vacancy.city }}
                </div>
              </div>
              <div class="col-sm-6" v-if="vacancy.employment_type">
                <div class="text-secondary mb-1" style="font-size:0.75rem;">Тип занятости</div>
                <div class="d-flex align-items-center gap-1 fw-medium">
                  <Clock :size="14" class="text-secondary" />
                  {{ vacancy.employment_type }}
                </div>
              </div>
              <div class="col-sm-6" v-if="vacancy.experience">
                <div class="text-secondary mb-1" style="font-size:0.75rem;">Опыт работы</div>
                <div class="d-flex align-items-center gap-1 fw-medium">
                  <Briefcase :size="14" class="text-secondary" />
                  {{ vacancy.experience }}
                </div>
              </div>
            </div>
          </div>

          <!-- Навыки -->
          <div class="vp-card p-3 mb-3" v-if="vacancy.skills?.length">
            <h6 class="fw-semibold mb-2">Ключевые навыки</h6>
            <div class="vp-skills-list">
              <span v-for="skill in vacancy.skills" :key="skill" class="vp-skill-tag">{{ skill }}</span>
            </div>
          </div>

          <!-- Описание accordion -->
          <div class="vp-card p-0 mb-3" v-if="vacancy.description || vacancy.requirements || vacancy.responsibilities">
            <div class="accordion" id="vacancyAccordion">
              <div v-if="vacancy.description" class="accordion-item border-0">
                <h6 class="accordion-header">
                  <button class="accordion-button fw-semibold py-2 px-3" type="button" data-bs-toggle="collapse" data-bs-target="#accDescription">
                    <FileText :size="15" class="me-2 text-primary" />Описание
                  </button>
                </h6>
                <div id="accDescription" class="accordion-collapse collapse show">
                  <div class="accordion-body pt-0">
                    <div class="vacancy-html-content" v-html="vacancy.description"></div>
                  </div>
                </div>
              </div>
              <div v-if="vacancy.requirements" class="accordion-item border-0 border-top">
                <h6 class="accordion-header">
                  <button class="accordion-button collapsed fw-semibold py-2 px-3" type="button" data-bs-toggle="collapse" data-bs-target="#accRequirements">
                    <CheckSquare :size="15" class="me-2 text-success" />Требования
                  </button>
                </h6>
                <div id="accRequirements" class="accordion-collapse collapse">
                  <div class="accordion-body pt-0">
                    <div class="vacancy-html-content" v-html="vacancy.requirements"></div>
                  </div>
                </div>
              </div>
              <div v-if="vacancy.responsibilities" class="accordion-item border-0 border-top">
                <h6 class="accordion-header">
                  <button class="accordion-button collapsed fw-semibold py-2 px-3" type="button" data-bs-toggle="collapse" data-bs-target="#accResponsibilities">
                    <ListChecks :size="15" class="me-2 text-info" />Обязанности
                  </button>
                </h6>
                <div id="accResponsibilities" class="accordion-collapse collapse">
                  <div class="accordion-body pt-0">
                    <div class="vacancy-html-content" v-html="vacancy.responsibilities"></div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- История изменений -->
          <div class="vp-card p-3">
            <div class="d-flex align-items-center justify-content-between mb-3">
              <h6 class="fw-semibold mb-0 d-flex align-items-center gap-2">
                <History :size="16" class="text-secondary" />
                История изменений
              </h6>
              <button
                class="btn btn-link btn-sm p-0 text-secondary text-decoration-none"
                @click="loadChanges"
                :disabled="loadingChanges"
                v-if="!changes"
              >
                Загрузить
              </button>
            </div>
            <div v-if="loadingChanges" class="vp-loading-state py-3">
              <div class="vp-spinner"></div>
              <span>Загрузка...</span>
            </div>
            <div v-else-if="changes && changes.length === 0" class="text-secondary small">
              Изменений не найдено
            </div>
            <div v-else-if="changes">
              <div v-for="change in changes" :key="change.id" class="vp-timeline-item">
                <div class="vp-timeline-dot" :class="`dot-${changeColor(change.change_type)}`"></div>
                <div class="d-flex align-items-center gap-2 mb-1">
                  <small class="fw-semibold">{{ change.change_type_display || change.change_type }}</small>
                  <small class="text-secondary">{{ formatDate(change.detected_at) }}</small>
                </div>
                <div v-if="change.changed_fields?.length" class="d-flex flex-wrap gap-1">
                  <span v-for="field in change.changed_fields" :key="field" class="badge bg-secondary bg-opacity-10 text-body" style="font-size:0.7rem;">{{ field }}</span>
                </div>
              </div>
            </div>
            <p v-else class="text-secondary small mb-0">Нажмите «Загрузить» для просмотра истории</p>
          </div>
        </div>

        <!-- Sidebar -->
        <div class="col-lg-4">
          <div class="vp-card p-3 mb-3">
            <h6 class="fw-semibold mb-3">Метаданные</h6>
            <ul class="list-group list-group-flush">
              <li class="list-group-item px-0 py-2 small d-flex justify-content-between align-items-center">
                <span class="text-secondary">Источник</span>
                <span class="badge vp-pill-badge vp-pill-badge-source">{{ sourceLabel(vacancy.source) }}</span>
              </li>
              <li v-if="vacancy.source_id" class="list-group-item px-0 py-2 small">
                <span class="text-secondary d-block mb-1">Source ID</span>
                <code style="font-size:0.75rem;">{{ vacancy.source_id }}</code>
              </li>
              <li class="list-group-item px-0 py-2 small d-flex justify-content-between align-items-center">
                <span class="text-secondary">Статус</span>
                <span class="badge vp-pill-badge" :class="statusBadgeClass(vacancy.status)">{{ vacancy.status }}</span>
              </li>
              <li class="list-group-item px-0 py-2 small d-flex justify-content-between align-items-center">
                <span class="text-secondary">Версия</span>
                <span class="fw-medium">{{ vacancy.current_version || '—' }}</span>
              </li>
              <li class="list-group-item px-0 py-2 small d-flex justify-content-between align-items-center">
                <span class="text-secondary">Опубликована</span>
                <span>{{ formatDate(vacancy.published_at) }}</span>
              </li>
              <li class="list-group-item px-0 py-2 small d-flex justify-content-between align-items-center">
                <span class="text-secondary">Обновлена</span>
                <span>{{ formatDate(vacancy.updated_at) }}</span>
              </li>
            </ul>
          </div>

          <div class="vp-card p-3" v-if="vacancy.url">
            <h6 class="fw-semibold mb-2">Ссылки</h6>
            <a :href="vacancy.url" target="_blank" rel="noopener" class="btn btn-outline-primary btn-sm w-100 d-flex align-items-center justify-content-center gap-1">
              <ExternalLink :size="14" />
              Открыть на сайте
            </a>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, RefreshCw, MapPin, Clock, Briefcase, FileText, CheckSquare, ListChecks, History, ExternalLink } from 'lucide-vue-next'
import { useToast } from 'vue-toastification'
import { vacanciesApi, sourceApi } from '../js/api'
import StateLoading from '../components/StateLoading.vue'
import StateError from '../components/StateError.vue'

const route  = useRoute()
const router = useRouter()
const toast  = useToast()

const vacancy = ref(null)
const changes = ref(null)
const loading = ref(false)
const loadingChanges = ref(false)
const refreshing = ref(false)
const error = ref(null)

function sourceLabel(s) { return { headhunter: 'HeadHunter', superjob: 'SuperJob', habr_career: 'Habr Career' }[s] || s }
function formatSalary(from, to, currency = 'RUB') {
  const c = currency === 'RUB' ? '₽' : currency
  if (from && to) return `${from.toLocaleString()} – ${to.toLocaleString()} ${c}`
  if (from) return `от ${from.toLocaleString()} ${c}`
  if (to) return `до ${to.toLocaleString()} ${c}`
  return ''
}
function formatDate(d) {
  if (!d) return '—'
  return new Date(d).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' })
}
function changeColor(type) {
  const map = { created: 'success', updated: 'primary', deleted: 'danger', status_changed: 'warning' }
  return map[type] || 'info'
}

function statusBadgeClass(status) {
  const map = { active: 'vp-pill-badge-success', inactive: 'vp-pill-badge-neutral' }
  return map[status] || 'vp-pill-badge-neutral'
}

async function loadVacancy() {
  loading.value = true
  error.value = null
  try {
    const r = await vacanciesApi.get(route.params.id)
    vacancy.value = r.data || r
  } catch (e) {
    error.value = e.message || 'Ошибка загрузки вакансии'
  } finally {
    loading.value = false
  }
}

async function loadChanges() {
  loadingChanges.value = true
  try {
    const r = await vacanciesApi.getChanges(route.params.id)
    const data = r.data
    changes.value = Array.isArray(data?.results) ? data.results : (Array.isArray(data) ? data : [])
  } catch (e) {
    toast.error('Ошибка загрузки истории')
  } finally {
    loadingChanges.value = false
  }
}

async function refreshVacancy() {
  if (!vacancy.value?.source) return
  refreshing.value = true
  try {
    const r = await sourceApi.getDetails(vacancy.value.source, { source_id: vacancy.value.source_id })
    const taskId = r.data?.task_id
    if (taskId) {
      toast.info('Обновление запущено...')
      const checkStatus = async () => {
        const s = await sourceApi.getTaskStatus(vacancy.value.source, taskId)
        if (s.data?.status === 'SUCCESS') {
          await loadVacancy()
          toast.success('Вакансия обновлена')
        } else if (['FAILURE', 'REVOKED'].includes(s.data?.status)) {
          toast.error('Ошибка обновления')
        } else {
          setTimeout(checkStatus, 2000)
        }
      }
      checkStatus()
    } else {
      await loadVacancy()
      toast.success('Вакансия обновлена')
    }
  } catch (e) {
    toast.error('Ошибка обновления вакансии')
  } finally {
    refreshing.value = false
  }
}

onMounted(loadVacancy)
</script>

<style lang="scss" scoped>
@import '../scss/main';

.vacancy-html-content {
  font-size: 0.9rem;
  line-height: 1.6;
  :deep(ul) { padding-left: 1.25rem; }
  :deep(p)  { margin-bottom: 0.5rem; }
}
</style>
