export default {
  VacanciesParserMain: {
    path: '/vacancies-parser',
    component: '@/modules/vacancies_parser/client/ParentLayout.vue',
    redirect: 'VacanciesDashboard',
    meta: { title: 'Парсинг вакансий', requiresAuth: true }
  },

  VacanciesDashboard: {
    path: '/vacancies-parser/dashboard',
    component: '@/modules/vacancies_parser/client/Dashboard/DashboardView.vue',
    meta: { title: 'Дашборд', requiresAuth: true }
  },

  VacanciesParser: {
    path: '/vacancies-parser/tasks',
    component: '@/modules/vacancies_parser/client/components/TasksList.vue',
    meta: { title: 'Задачи парсинга', requiresAuth: true }
  },

  VacanciesParserTaskDetail: {
    path: '/vacancies-parser/tasks/:id',
    component: '@/modules/vacancies_parser/client/components/TaskDetailView.vue',
    meta: { title: 'Детали задачи', requiresAuth: true }
  },

  VacanciesParserResults: {
    path: '/vacancies-parser/results',
    component: '@/modules/vacancies_parser/client/components/VacanciesResults.vue',
    meta: { title: 'Результаты парсинга', requiresAuth: true }
  },

  VacanciesList: {
    path: '/vacancies-parser/vacancies',
    component: '@/modules/vacancies_parser/client/VacanciesList/VacanciesListView.vue',
    meta: { title: 'Вакансии', requiresAuth: true }
  },

  VacancyDetail: {
    path: '/vacancies-parser/vacancies/:id',
    component: '@/modules/vacancies_parser/client/VacancyDetail/VacancyDetailView.vue',
    meta: { title: 'Детали вакансии', requiresAuth: true }
  },

  VacancyStats: {
    path: '/vacancies-parser/stats',
    component: '@/modules/vacancies_parser/client/Stats/VacancyStatsView.vue',
    meta: { title: 'Статистика вакансий', requiresAuth: true }
  },

  ParsingControl: {
    path: '/vacancies-parser/control',
    component: '@/modules/vacancies_parser/client/ParsingControl/ParsingControlView.vue',
    meta: { title: 'Управление парсингом', requiresAuth: true }
  }
}
