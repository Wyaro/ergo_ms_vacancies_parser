<template>
  <div class="d-flex flex-column h-100">
    <div class="border-bottom bg-body sticky-top" style="z-index: 100;">
      <div class="container-fluid px-4">
        <div class="d-flex align-items-center gap-3 py-3">
          <div class="d-flex align-items-center gap-2 flex-shrink-0">
            <div class="rounded-2 d-flex align-items-center justify-content-center text-primary bg-primary bg-opacity-10" style="width:36px;height:36px;">
              <BarChart3 :size="18" />
            </div>
            <div class="d-none d-md-block">
              <div class="fw-semibold lh-1" style="font-size:0.9375rem;">Парсинг вакансий</div>
              <div class="text-secondary" style="font-size:0.75rem;">HH · SuperJob · Habr Career</div>
            </div>
          </div>

          <nav class="d-flex align-items-center gap-1 flex-wrap">
            <RouterLink
              v-for="item in navItems"
              :key="item.name"
              :to="{ name: item.name }"
              class="nav-btn d-flex align-items-center gap-1 px-3 py-2 rounded-2 text-decoration-none fw-medium"
              :class="isActive(item) ? 'nav-btn-active' : 'nav-btn-default'"
              style="font-size: 0.875rem;"
            >
              <component :is="item.icon" :size="15" />
              <span class="d-none d-sm-inline">{{ item.label }}</span>
            </RouterLink>
          </nav>
        </div>
      </div>
    </div>

    <div class="flex-grow-1 overflow-auto">
      <RouterView />
    </div>
  </div>
</template>

<script setup>
import { useRoute } from 'vue-router'
import {
  BarChart3, LayoutDashboard, ClipboardList, Database,
  BriefcaseBusiness, BarChart2, Settings2
} from 'lucide-vue-next'

const route = useRoute()

const navItems = [
  { name: 'VacanciesDashboard',    label: 'Дашборд',     icon: LayoutDashboard },
  { name: 'VacanciesParser',       label: 'Задачи',      icon: ClipboardList },
  { name: 'VacanciesParserResults',label: 'Результаты',  icon: Database },
  { name: 'VacanciesList',         label: 'Вакансии',    icon: BriefcaseBusiness },
  { name: 'VacancyStats',          label: 'Статистика',  icon: BarChart2 },
  { name: 'ParsingControl',        label: 'Управление',  icon: Settings2 }
]

function isActive(item) {
  return route.name === item.name || route.matched.some(r => r.name === item.name)
}
</script>

<style lang="scss" scoped>
.nav-btn {
  transition: background 0.15s ease, color 0.15s ease;
  white-space: nowrap;

  &-default {
    color: var(--bs-secondary-color);
    &:hover {
      background: var(--bs-secondary-bg);
      color: var(--bs-body-color);
    }
  }

  &-active {
    background: rgba(var(--bs-primary-rgb), 0.1);
    color: var(--bs-primary);
  }
}
</style>
