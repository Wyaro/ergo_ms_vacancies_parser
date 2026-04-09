<template>
  <div class="vp-page p-4">
    <div class="vp-page-header">
      <div class="vp-page-title">
        <div class="vp-page-icon">
          <Settings2 :size="20" />
        </div>
        <div>
          <h1>Управление парсингом</h1>
          <p>Ручной запуск парсинга по ролям и технологиям</p>
        </div>
      </div>
    </div>

    <!-- Вкладки -->
    <ul class="nav nav-tabs vp-nav-tabs mb-4">
      <li class="nav-item">
        <button class="nav-link" :class="{ active: activeTab === 'roles' }" @click="activeTab = 'roles'">
          <Users :size="14" />
          По ролям
        </button>
      </li>
      <li class="nav-item">
        <button class="nav-link" :class="{ active: activeTab === 'tech' }" @click="activeTab = 'tech'">
          <Code2 :size="14" />
          По технологиям
        </button>
      </li>
    </ul>

    <!-- Статус Celery задачи -->
    <div v-if="taskId" class="alert d-flex align-items-center gap-2 mb-4" :class="taskStatusAlertClass" role="alert">
      <span v-if="taskStatus?.status === 'PENDING' || taskStatus?.status === 'STARTED'" class="spinner-border spinner-border-sm flex-shrink-0"></span>
      <CheckCircle2 v-else-if="taskStatus?.status === 'SUCCESS'" :size="18" class="flex-shrink-0" />
      <AlertCircle v-else-if="taskStatus?.status === 'FAILURE'" :size="18" class="flex-shrink-0" />
      <div>
        <div class="fw-semibold">
          {{ taskStatusLabel }}
        </div>
        <small v-if="taskId">Task ID: <code>{{ taskId }}</code></small>
      </div>
      <button class="btn btn-link btn-sm p-0 ms-auto text-decoration-none" @click="resetTask">
        <X :size="16" />
      </button>
    </div>

    <!-- По ролям -->
    <div v-if="activeTab === 'roles'" class="vp-card p-4">
      <h6 class="fw-semibold mb-3 d-flex align-items-center gap-2">
        <Users :size="16" class="text-primary" />
        Парсинг HeadHunter по ролям
      </h6>
      <div class="row g-3">
        <div class="col-sm-6 col-lg-4">
          <label class="form-label fw-medium">Регион</label>
          <select v-model.number="rolesForm.area" class="form-select">
            <option value="1">Москва</option>
            <option value="2">Санкт-Петербург</option>
            <option value="113">Россия (все)</option>
            <option value="66">Нижний Новгород</option>
            <option value="88">Казань</option>
          </select>
        </div>
        <div class="col-sm-6 col-lg-4">
          <label class="form-label fw-medium">Страниц на роль</label>
          <input v-model.number="rolesForm.pages" type="number" class="form-control" min="1" max="20" />
          <div class="form-text">Максимум 20 страниц</div>
        </div>
        <div class="col-sm-6 col-lg-4">
          <label class="form-label fw-medium">Задержка (сек)</label>
          <input v-model.number="rolesForm.delay" type="number" class="form-control" min="0.1" max="5" step="0.1" />
        </div>
        <div class="col-sm-6 col-lg-4">
          <label class="form-label fw-medium">Макс. одновременных ролей</label>
          <input v-model.number="rolesForm.max_concurrent_roles" type="number" class="form-control" min="1" max="10" />
        </div>
        <div class="col-sm-6 col-lg-4">
          <label class="form-label fw-medium">Размер батча</label>
          <input v-model.number="rolesForm.batch_size" type="number" class="form-control" min="1" max="50" />
        </div>
      </div>
      <div class="mt-3 d-flex flex-wrap gap-3">
        <div class="form-check">
          <input class="form-check-input" type="checkbox" v-model="rolesForm.get_details" id="getRolesDetails" />
          <label class="form-check-label" for="getRolesDetails" style="font-size:0.875rem;">Загружать детали</label>
        </div>
        <div class="form-check">
          <input class="form-check-input" type="checkbox" v-model="rolesForm.update_existing" id="updateExisting" />
          <label class="form-check-label" for="updateExisting" style="font-size:0.875rem;">Обновлять существующие</label>
        </div>
        <div class="form-check">
          <input class="form-check-input" type="checkbox" v-model="rolesForm.skip_existing" id="skipExisting" />
          <label class="form-check-label" for="skipExisting" style="font-size:0.875rem;">Пропускать дубли</label>
        </div>
      </div>
      <div class="mt-4">
        <button
          class="btn btn-primary d-flex align-items-center gap-2"
          @click="launchRolesParsing"
          :disabled="parsing"
        >
          <span v-if="parsing" class="spinner-border spinner-border-sm"></span>
          <Play v-else :size="16" />
          Запустить парсинг по ролям
        </button>
      </div>
    </div>

    <!-- По технологиям -->
    <div v-if="activeTab === 'tech'" class="vp-card p-4">
      <h6 class="fw-semibold mb-3 d-flex align-items-center gap-2">
        <Code2 :size="16" class="text-primary" />
        Парсинг HeadHunter по технологиям
      </h6>
      <div class="mb-3">
        <label class="form-label fw-medium">
          Список технологий <span class="text-danger">*</span>
        </label>
        <textarea
          v-model="techForm.technologies"
          class="form-control"
          rows="4"
          placeholder="Python, JavaScript, React, Django..."
          style="font-size:0.875rem;"
        ></textarea>
        <div class="form-text">Введите технологии через запятую или с новой строки</div>
      </div>
      <div class="row g-3">
        <div class="col-sm-6 col-lg-4">
          <label class="form-label fw-medium">Регион</label>
          <select v-model.number="techForm.area" class="form-select">
            <option value="1">Москва</option>
            <option value="2">Санкт-Петербург</option>
            <option value="113">Россия (все)</option>
            <option value="66">Нижний Новгород</option>
            <option value="88">Казань</option>
          </select>
        </div>
        <div class="col-sm-6 col-lg-4">
          <label class="form-label fw-medium">Страниц на технологию</label>
          <input v-model.number="techForm.pages" type="number" class="form-control" min="1" max="20" />
        </div>
        <div class="col-sm-6 col-lg-4">
          <label class="form-label fw-medium">Задержка (сек)</label>
          <input v-model.number="techForm.delay" type="number" class="form-control" min="0.1" max="5" step="0.1" />
        </div>
      </div>
      <div class="mt-4">
        <button
          class="btn btn-primary d-flex align-items-center gap-2"
          @click="launchTechParsing"
          :disabled="parsing || !techForm.technologies.trim()"
        >
          <span v-if="parsing" class="spinner-border spinner-border-sm"></span>
          <Play v-else :size="16" />
          Запустить парсинг по технологиям
        </button>
      </div>
    </div>

    <ConfirmDialog ref="confirmDialogRef" />
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { Settings2, Users, Code2, Play, X, CheckCircle2, AlertCircle } from 'lucide-vue-next'
import { useToast } from 'vue-toastification'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { useParsing } from '../composables/useParsing'

const toast = useToast()
const { parsing, taskId, taskStatus, parseByRoles, parseByTechnologies, checkTaskStatus, reset } = useParsing()
const confirmDialogRef = ref(null)
const activeTab = ref('roles')

const rolesForm = ref({
  area: 1,
  pages: 2,
  delay: 0.5,
  max_concurrent_roles: 3,
  batch_size: 10,
  get_details: true,
  update_existing: false,
  skip_existing: true
})

const techForm = ref({
  technologies: '',
  area: 1,
  pages: 2,
  delay: 0.5
})

const taskStatusAlertClass = computed(() => {
  const s = taskStatus.value?.status
  if (!s || s === 'PENDING' || s === 'STARTED') return 'alert-info'
  if (s === 'SUCCESS') return 'alert-success'
  if (s === 'FAILURE') return 'alert-danger'
  return 'alert-secondary'
})

const taskStatusLabel = computed(() => {
  const s = taskStatus.value?.status
  const map = { PENDING: 'Задача поставлена в очередь...', STARTED: 'Парсинг выполняется...', SUCCESS: 'Парсинг завершён успешно', FAILURE: 'Ошибка парсинга', REVOKED: 'Задача отменена' }
  return map[s] || 'Задача запущена'
})

let pollTimer = null
function startPolling() {
  pollTimer = setInterval(async () => {
    if (!taskId.value) { clearInterval(pollTimer); return }
    await checkTaskStatus('headhunter')
    const s = taskStatus.value?.status
    if (s === 'SUCCESS' || s === 'FAILURE' || s === 'REVOKED') clearInterval(pollTimer)
  }, 3000)
}
function resetTask() { reset(); clearInterval(pollTimer) }

async function launchRolesParsing() {
  const ok = await confirmDialogRef.value?.open({
    title: 'Запустить парсинг по ролям?',
    message: `Будет запущен парсинг HeadHunter по всем IT-ролям. Регион: ${rolesForm.value.area}, страниц: ${rolesForm.value.pages}.`,
    confirmText: 'Запустить',
    confirmVariant: 'primary'
  })
  if (!ok) return
  try {
    await parseByRoles('headhunter', { ...rolesForm.value })
    startPolling()
  } catch (e) {
    // Ошибка обработана в useParsing
  }
}

async function launchTechParsing() {
  if (!techForm.value.technologies.trim()) { toast.warning('Введите список технологий'); return }
  const technologies = techForm.value.technologies
    .split(/[,\n]+/)
    .map(t => t.trim())
    .filter(Boolean)

  const ok = await confirmDialogRef.value?.open({
    title: 'Запустить парсинг по технологиям?',
    message: `Будет запущен парсинг по ${technologies.length} технологиям.`,
    confirmText: 'Запустить',
    confirmVariant: 'primary'
  })
  if (!ok) return
  try {
    await parseByTechnologies('headhunter', { technologies, area: techForm.value.area, pages: techForm.value.pages, delay: techForm.value.delay })
    startPolling()
  } catch (e) {
    // Ошибка обработана в useParsing
  }
}
</script>

<style lang="scss" scoped>
@import '../scss/main';
</style>
