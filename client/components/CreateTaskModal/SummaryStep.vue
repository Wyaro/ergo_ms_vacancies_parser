<template>
  <div>
    <p class="text-secondary mb-4">Убедитесь, что все параметры настроены правильно</p>

    <div class="card border">
      <div class="card-body">
        <h6 class="card-subtitle mb-3 text-secondary text-uppercase" style="font-size: 0.7rem; letter-spacing: 0.08em;">Основная информация</h6>
        <dl class="row mb-0">
          <dt class="col-sm-4 text-secondary fw-normal">Название</dt>
          <dd class="col-sm-8 fw-semibold mb-2">{{ taskName || 'Будет сгенерировано автоматически' }}</dd>
          <dt class="col-sm-4 text-secondary fw-normal">Источник</dt>
          <dd class="col-sm-8 mb-2">
            <span class="vp-source-badge" :class="`source-${source}`">{{ getSourceLabel(source) }}</span>
          </dd>
          <dt class="col-sm-4 text-secondary fw-normal">Режим</dt>
          <dd class="col-sm-8 mb-0">
            <span class="badge bg-secondary bg-opacity-10 text-body">{{ getModeLabel(parsingMode) }}</span>
          </dd>
        </dl>
      </div>
    </div>

    <div class="card border mt-3" v-if="configEntries.length">
      <div class="card-body">
        <h6 class="card-subtitle mb-3 text-secondary text-uppercase" style="font-size: 0.7rem; letter-spacing: 0.08em;">Параметры поиска</h6>
        <dl class="row mb-0">
          <template v-for="[key, value] in configEntries" :key="key">
            <dt class="col-sm-4 text-secondary fw-normal">{{ getConfigLabel(key) }}</dt>
            <dd class="col-sm-8 mb-2">{{ formatConfigValue(key, value) }}</dd>
          </template>
        </dl>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  taskName:    { type: String, default: '' },
  source:      { type: String, required: true },
  parsingMode: { type: String, required: true },
  config:      { type: Object, required: true },
  sources:     { type: Array, required: true }
})

const configEntries = computed(() =>
  Object.entries(props.config).filter(([, v]) => v !== '' && v !== null && v !== undefined)
)

function getSourceLabel(source) {
  return props.sources.find(s => s.value === source)?.label || source
}
function getModeLabel(mode) {
  const src = props.sources.find(s => s.value === props.source)
  return src?.modes.find(m => m.value === mode)?.label || mode
}
function getConfigLabel(key) {
  const labels = {
    area: 'Регион', pages: 'Страниц', max_pages: 'Макс. страниц',
    per_page: 'На страницу', items_per_page: 'На страницу',
    delay: 'Задержка (сек)', text: 'Запрос', keyword: 'Запрос',
    keywords: 'Запрос', q: 'Запрос', town: 'Город',
    catalogues: 'Каталоги', experience: 'Опыт'
  }
  return labels[key] || key
}
function formatConfigValue(key, value) {
  if (key === 'area') {
    const map = { '1': 'Москва', '2': 'Санкт-Петербург', '113': 'Россия (все)', '66': 'Нижний Новгород', '88': 'Казань', '4': 'Новосибирск', '3': 'Екатеринбург' }
    return map[value] || value
  }
  if (key === 'experience') {
    const map = { noExperience: 'Без опыта', between1And3: '1-3 года', between3And6: '3-6 лет', moreThan6: '>6 лет' }
    return map[value] || value || 'Любой'
  }
  return value || '—'
}
</script>

<style lang="scss" scoped>
@import '../../scss/main';
</style>
