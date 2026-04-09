<template>
  <div>
    <p class="text-secondary mb-4">Настройте параметры поиска для выбранного источника</p>

    <!-- HeadHunter API -->
    <template v-if="source === 'headhunter' && parsingMode === 'api'">
      <div class="mb-3">
        <label class="form-label fw-medium">Регион <span class="text-danger">*</span></label>
        <select v-model="localConfig.area" class="form-select" :class="{ 'is-invalid': errors.area }">
          <option value="">Выберите регион</option>
          <option v-for="r in regionOptions" :key="r.value" :value="r.value">{{ r.label }}</option>
        </select>
        <div class="invalid-feedback">{{ errors.area }}</div>
      </div>
      <div class="row g-3 mb-3">
        <div class="col-sm-6">
          <label class="form-label fw-medium">Страниц <span class="text-danger">*</span></label>
          <input v-model.number="localConfig.pages" type="number" class="form-control" :class="{ 'is-invalid': errors.pages }" min="1" max="20" />
          <div class="invalid-feedback">{{ errors.pages }}</div>
          <div class="form-text">Максимум 20 страниц (лимит API HH)</div>
        </div>
        <div class="col-sm-6">
          <label class="form-label fw-medium">Вакансий на страницу</label>
          <select v-model.number="localConfig.per_page" class="form-select">
            <option v-for="o in perPageOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
          </select>
        </div>
      </div>
      <div class="row g-3 mb-3">
        <div class="col-sm-6">
          <label class="form-label fw-medium">Задержка (сек)</label>
          <input v-model.number="localConfig.delay" type="number" class="form-control" min="0.1" max="5" step="0.1" />
        </div>
        <div class="col-sm-6">
          <label class="form-label fw-medium">Поисковый запрос</label>
          <input v-model="localConfig.text" type="text" class="form-control" placeholder="python developer" />
        </div>
      </div>
    </template>

    <!-- HeadHunter HTML -->
    <template v-else-if="source === 'headhunter' && parsingMode === 'html'">
      <div class="alert alert-warning d-flex align-items-center gap-2 mb-3" role="alert">
        <AlertTriangle :size="16" />
        <small>HTML режим медленнее и может блокироваться. Рекомендуется API режим.</small>
      </div>
      <div class="row g-3 mb-3">
        <div class="col-sm-6">
          <label class="form-label fw-medium">Регион <span class="text-danger">*</span></label>
          <select v-model="localConfig.area" class="form-select">
            <option value="">Выберите регион</option>
            <option v-for="r in regionOptionsHtml" :key="r.value" :value="r.value">{{ r.label }}</option>
          </select>
        </div>
        <div class="col-sm-6">
          <label class="form-label fw-medium">Макс. страниц <span class="text-danger">*</span></label>
          <input v-model.number="localConfig.max_pages" type="number" class="form-control" :class="{ 'is-invalid': errors.max_pages }" min="1" max="50" />
          <div class="invalid-feedback">{{ errors.max_pages }}</div>
        </div>
      </div>
      <div class="row g-3 mb-3">
        <div class="col-sm-6">
          <label class="form-label fw-medium">Вакансий на страницу</label>
          <select v-model.number="localConfig.items_per_page" class="form-select">
            <option v-for="o in itemsPerPageOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
          </select>
        </div>
        <div class="col-sm-6">
          <label class="form-label fw-medium">Опыт работы</label>
          <select v-model="localConfig.experience" class="form-select">
            <option v-for="o in experienceOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
          </select>
        </div>
      </div>
      <div class="mb-3">
        <label class="form-label fw-medium">Поисковый запрос</label>
        <input v-model="localConfig.text" type="text" class="form-control" placeholder="python developer" />
      </div>
    </template>

    <!-- Habr Career API -->
    <template v-else-if="source === 'habr_career' && parsingMode === 'api'">
      <div class="row g-3 mb-3">
        <div class="col-sm-6">
          <label class="form-label fw-medium">Макс. страниц <span class="text-danger">*</span></label>
          <input v-model.number="localConfig.max_pages" type="number" class="form-control" :class="{ 'is-invalid': errors.max_pages }" min="1" max="50" />
          <div class="invalid-feedback">{{ errors.max_pages }}</div>
        </div>
        <div class="col-sm-6">
          <label class="form-label fw-medium">Задержка (сек)</label>
          <input v-model.number="localConfig.delay" type="number" class="form-control" min="0.1" max="5" step="0.1" />
        </div>
      </div>
      <div class="mb-3">
        <label class="form-label fw-medium">Поисковый запрос</label>
        <input v-model="localConfig.q" type="text" class="form-control" placeholder="python" />
      </div>
    </template>

    <!-- Habr Career HTML -->
    <template v-else-if="source === 'habr_career' && parsingMode === 'html'">
      <div class="mb-3">
        <label class="form-label fw-medium">Макс. страниц <span class="text-danger">*</span></label>
        <input v-model.number="localConfig.max_pages" type="number" class="form-control" :class="{ 'is-invalid': errors.max_pages }" min="1" max="30" />
        <div class="invalid-feedback">{{ errors.max_pages }}</div>
      </div>
      <div class="mb-3">
        <label class="form-label fw-medium">Поисковый запрос</label>
        <input v-model="localConfig.q" type="text" class="form-control" placeholder="python" />
      </div>
    </template>

    <!-- SuperJob API -->
    <template v-else-if="source === 'superjob' && parsingMode === 'api'">
      <div class="row g-3 mb-3">
        <div class="col-sm-6">
          <label class="form-label fw-medium">Страниц <span class="text-danger">*</span></label>
          <input v-model.number="localConfig.pages" type="number" class="form-control" :class="{ 'is-invalid': errors.pages }" min="1" max="500" />
          <div class="invalid-feedback">{{ errors.pages }}</div>
          <div class="form-text">Максимум 500 страниц</div>
        </div>
        <div class="col-sm-6">
          <label class="form-label fw-medium">Задержка (сек)</label>
          <input v-model.number="localConfig.delay" type="number" class="form-control" min="0.1" max="5" step="0.1" />
        </div>
      </div>
      <div class="row g-3 mb-3">
        <div class="col-sm-6">
          <label class="form-label fw-medium">Поисковый запрос</label>
          <input v-model="localConfig.keyword" type="text" class="form-control" placeholder="python developer" />
        </div>
        <div class="col-sm-6">
          <label class="form-label fw-medium">Город</label>
          <input v-model="localConfig.town" type="text" class="form-control" placeholder="Москва" />
        </div>
      </div>
      <div class="mb-3">
        <label class="form-label fw-medium">ID каталогов (через запятую)</label>
        <input v-model="localConfig.catalogues" type="text" class="form-control" placeholder="33 — IT, по умолчанию все" />
        <div class="form-text">33 = IT, 48 = Маркетинг. Пусто — поиск по всем</div>
      </div>
    </template>

    <!-- SuperJob HTML -->
    <template v-else-if="source === 'superjob' && parsingMode === 'html'">
      <div class="row g-3 mb-3">
        <div class="col-sm-6">
          <label class="form-label fw-medium">Макс. страниц <span class="text-danger">*</span></label>
          <input v-model.number="localConfig.max_pages" type="number" class="form-control" :class="{ 'is-invalid': errors.max_pages }" min="1" max="30" />
          <div class="invalid-feedback">{{ errors.max_pages }}</div>
        </div>
        <div class="col-sm-6">
          <label class="form-label fw-medium">Город</label>
          <input v-model="localConfig.town" type="text" class="form-control" placeholder="Москва" />
        </div>
      </div>
      <div class="mb-3">
        <label class="form-label fw-medium">Поисковый запрос</label>
        <input v-model="localConfig.keywords" type="text" class="form-control" placeholder="python developer" />
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { AlertTriangle } from 'lucide-vue-next'

const props = defineProps({
  source:      { type: String, required: true },
  parsingMode: { type: String, required: true },
  config:      { type: Object, required: true },
  errors:      { type: Object, default: () => ({}) }
})
const emit = defineEmits(['update:config'])

const localConfig = computed({
  get: () => props.config,
  set: v => emit('update:config', v)
})

const regionOptions = [
  { value: '1',   label: 'Москва' },
  { value: '2',   label: 'Санкт-Петербург' },
  { value: '113', label: 'Россия (все регионы)' },
  { value: '66',  label: 'Нижний Новгород' },
  { value: '88',  label: 'Казань' },
  { value: '4',   label: 'Новосибирск' },
  { value: '3',   label: 'Екатеринбург' }
]
const regionOptionsHtml = [
  { value: '1',   label: 'Москва' },
  { value: '2',   label: 'Санкт-Петербург' },
  { value: '113', label: 'Россия (все регионы)' }
]
const perPageOptions = [
  { value: 20,  label: '20' },
  { value: 50,  label: '50' },
  { value: 100, label: '100 (рекомендуется)' }
]
const itemsPerPageOptions = [
  { value: 20,  label: '20' },
  { value: 50,  label: '50 (рекомендуется)' },
  { value: 100, label: '100' }
]
const experienceOptions = [
  { value: '',              label: 'Любой' },
  { value: 'noExperience',  label: 'Без опыта' },
  { value: 'between1And3',  label: '1-3 года' },
  { value: 'between3And6',  label: '3-6 лет' },
  { value: 'moreThan6',     label: 'Более 6 лет' }
]
</script>
