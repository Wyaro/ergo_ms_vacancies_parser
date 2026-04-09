/**
 * API endpoints для модуля vacancies_parser.
 *
 * Архитектура двухуровневая:
 *  1. Core (unified) — /api/vacancies_parser/...
 *     Работает с NormalizedVacancy, задачами, статистикой.
 *  2. Source-specific — /api/vacancies_parser/<source>/...
 *     Работает с моделями конкретного источника (HH, SJ, Habr).
 *
 * Для получения source-specific эндпоинтов используй
 * фабрику `getSourceEndpoints(source)`.
 */

export const endpoints = {
  // Задачи парсинга
  tasks: {
    list: 'vacancies_parser/tasks/',
    detail: id => `vacancies_parser/tasks/${id}/`,
    create: 'vacancies_parser/tasks/',
    update: id => `vacancies_parser/tasks/${id}/`,
    delete: id => `vacancies_parser/tasks/${id}/`,
    progress: id => `vacancies_parser/tasks/${id}/progress/`,
    pause: id => `vacancies_parser/tasks/${id}/pause/`,
    resume: id => `vacancies_parser/tasks/${id}/resume/`,
    stop: id => `vacancies_parser/tasks/${id}/stop/`,
    items: id => `vacancies_parser/tasks/${id}/items/`,
    statistics: id => `vacancies_parser/tasks/${id}/statistics/`,
    sources: 'vacancies_parser/tasks/sources/'
  },
  
  // Элементы задач
  items: {
    list: 'vacancies_parser/items/',
    detail: id => `vacancies_parser/items/${id}/`
  },
  
  // Вакансии
  vacancies: {
    list: 'vacancies_parser/vacancies/',
    detail: id => `vacancies_parser/vacancies/${id}/`,
    changes: id => `vacancies_parser/vacancies/${id}/changes/`,
    export: 'vacancies_parser/vacancies/export/'
  },
  
  // Статистика
  statistics: {
    list: 'vacancies_parser/statistics/',
    detail: id => `vacancies_parser/statistics/${id}/`
  },

  // Мониторинг системных/внешних задач
  taskRuns: {
    list: 'vacancies_parser/task-runs/',
    detail: id => `vacancies_parser/task-runs/${id}/`
  },
  externalApiEvents: {
    list: 'vacancies_parser/external-api-events/',
    detail: id => `vacancies_parser/external-api-events/${id}/`
  },
  systemJobs: {
    list: 'vacancies_parser/system-jobs/',
    run: id => `vacancies_parser/system-jobs/${id}/run/`
  }
}


export function getSourceEndpoints(source) {
  const prefix = `vacancies_parser/${source}`

  return {
    vacancies: {
      list: `${prefix}/vacancies/`,
      detail: id => `${prefix}/vacancies/${id}/`,
      versions: id => `${prefix}/vacancies/${id}/versions/`,
      versionDetail: id => `${prefix}/vacancies/${id}/version_detail/`,
      changes: id => `${prefix}/vacancies/${id}/changes/`,
      stats: `${prefix}/vacancies/stats/`,
      taskStatus: `${prefix}/vacancies/task_status/`,
      parseSingle: `${prefix}/vacancies/parse_single/`
    },
    parsing: {
      parseByText: `${prefix}/parsing/parse_by_text/`,
      parseAll: `${prefix}/parsing/parse_all/`,
      parseByConfig: `${prefix}/parsing/parse_by_config/`,
      parseByCatalogues: `${prefix}/parsing/parse_by_catalogues/`,
      parseByRoles: `${prefix}/parsing/parse_by_roles/`,
      parseByTechnologies: `${prefix}/parsing/parse_by_technologies/`,
      catalogues: `${prefix}/parsing/catalogues/`,
      getDetails: `${prefix}/parsing/get_details/`
    }
  }
}
