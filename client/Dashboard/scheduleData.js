/**
 * Расписание Celery Beat для модуля vacancies_parser
 * HeadHunter + SuperJob + сервисные задачи
 */

const SERVICE_TASKS = [
  {
    id: 'vacancies_parser-release-expired-leases',
    time: '*/5 мин',
    title: 'Crash recovery: освобождение зависших задач',
    description: 'Освобождает просроченные leases задач парсинга каждые 5 минут',
    queueLabel: 'VacanciesParser',
    queueVariant: 'info',
    frequency: 'Каждые 5 минут',
    frequencyVariant: 'info'
  },
  {
    id: 'vacancies_parser-monitor-tasks-progress',
    time: '*/10 мин',
    title: 'Мониторинг прогресса задач',
    description: 'Проверка состояния и прогресса задач парсинга каждые 10 минут',
    queueLabel: 'VacanciesParser',
    queueVariant: 'info',
    frequency: 'Каждые 10 минут',
    frequencyVariant: 'info'
  }
]

const HEADHUNTER_TASKS = [
  {
    id: 'hh-daily-yesterday-today',
    time: '02:00',
    title: 'Ежедневный парсинг за вчера и сегодня',
    description: 'Полный парсинг всех технологий за вчера и сегодня с максимальным покрытием',
    queueLabel: 'HeadHunter',
    queueVariant: 'danger',
    frequency: 'Ежедневно',
    frequencyVariant: 'info'
  },
  {
    id: 'hh-monthly-recursive',
    time: '01:00 (1 число)',
    title: 'Месячный рекурсивный парсинг',
    description: 'Глубокий парсинг за прошедший месяц с рекурсивной сегментацией по дням',
    queueLabel: 'HeadHunter',
    queueVariant: 'danger',
    frequency: 'Раз в месяц',
    frequencyVariant: 'info'
  },
  {
    id: 'hh-languages-workdays-morning',
    time: '06:15 (будни)',
    title: 'Языки программирования - утро',
    description: 'Категория LANG, до 2 страниц, рабочие дни утром',
    queueLabel: 'HeadHunter',
    queueVariant: 'danger',
    frequency: 'Пн-Пт, 06:15',
    frequencyVariant: 'info'
  },
  {
    id: 'hh-languages-workdays-noon',
    time: '12:15 (будни)',
    title: 'Языки программирования - день',
    description: 'Категория LANG, до 2 страниц, рабочие дни в обед',
    queueLabel: 'HeadHunter',
    queueVariant: 'danger',
    frequency: 'Пн-Пт, 12:15',
    frequencyVariant: 'info'
  },
  {
    id: 'hh-languages-workdays-evening',
    time: '18:15 (будни)',
    title: 'Языки программирования - вечер',
    description: 'Категория LANG, до 2 страниц, рабочие дни вечером',
    queueLabel: 'HeadHunter',
    queueVariant: 'danger',
    frequency: 'Пн-Пт, 18:15',
    frequencyVariant: 'info'
  },
  {
    id: 'hh-languages-weekend-morning',
    time: '10:15 (выходные)',
    title: 'Языки программирования - утро (выходные)',
    description: 'Категория LANG, до 2 страниц, суббота и воскресенье утром',
    queueLabel: 'HeadHunter',
    queueVariant: 'danger',
    frequency: 'Сб-Вс, 10:15',
    frequencyVariant: 'info'
  },
  {
    id: 'hh-languages-weekend-evening',
    time: '18:15 (выходные)',
    title: 'Языки программирования - вечер (выходные)',
    description: 'Категория LANG, до 2 страниц, суббота и воскресенье вечером',
    queueLabel: 'HeadHunter',
    queueVariant: 'danger',
    frequency: 'Сб-Вс, 18:15',
    frequencyVariant: 'info'
  },
  {
    id: 'hh-frameworks-workdays-morning',
    time: '07:30 (будни)',
    title: 'Фреймворки - утро',
    description: 'Категория FRAMEWORK, до 2 страниц, рабочие дни утром',
    queueLabel: 'HeadHunter',
    queueVariant: 'danger',
    frequency: 'Пн-Пт, 07:30',
    frequencyVariant: 'info'
  },
  {
    id: 'hh-frameworks-workdays-noon',
    time: '13:30 (будни)',
    title: 'Фреймворки - день',
    description: 'Категория FRAMEWORK, до 2 страниц, рабочие дни в обед',
    queueLabel: 'HeadHunter',
    queueVariant: 'danger',
    frequency: 'Пн-Пт, 13:30',
    frequencyVariant: 'info'
  },
  {
    id: 'hh-frameworks-workdays-evening',
    time: '19:30 (будни)',
    title: 'Фреймворки - вечер',
    description: 'Категория FRAMEWORK, до 2 страниц, рабочие дни вечером',
    queueLabel: 'HeadHunter',
    queueVariant: 'danger',
    frequency: 'Пн-Пт, 19:30',
    frequencyVariant: 'info'
  },
  {
    id: 'hh-frameworks-weekend-morning',
    time: '11:30 (выходные)',
    title: 'Фреймворки - утро (выходные)',
    description: 'Категория FRAMEWORK, до 2 страниц, суббота и воскресенье утром',
    queueLabel: 'HeadHunter',
    queueVariant: 'danger',
    frequency: 'Сб-Вс, 11:30',
    frequencyVariant: 'info'
  },
  {
    id: 'hh-frameworks-weekend-evening',
    time: '19:30 (выходные)',
    title: 'Фреймворки - вечер (выходные)',
    description: 'Категория FRAMEWORK, до 2 страниц, суббота и воскресенье вечером',
    queueLabel: 'HeadHunter',
    queueVariant: 'danger',
    frequency: 'Сб-Вс, 19:30',
    frequencyVariant: 'info'
  },
  {
    id: 'hh-databases-morning',
    time: '08:45',
    title: 'Базы данных - утро',
    description: 'Категория DB, 2 страницы, акцент на популярные СУБД',
    queueLabel: 'HeadHunter',
    queueVariant: 'danger',
    frequency: 'Ежедневно, 08:45',
    frequencyVariant: 'info'
  },
  {
    id: 'hh-databases-evening',
    time: '20:45',
    title: 'Базы данных - вечер',
    description: 'Категория DB, 2 страницы, вечерний прогон',
    queueLabel: 'HeadHunter',
    queueVariant: 'danger',
    frequency: 'Ежедневно, 20:45',
    frequencyVariant: 'info'
  },
  {
    id: 'hh-tools-daily',
    time: '14:00',
    title: 'Инструменты разработчика',
    description: 'Категория TOOL, дневной прогон по инструментам',
    queueLabel: 'HeadHunter',
    queueVariant: 'danger',
    frequency: 'Ежедневно, 14:00',
    frequencyVariant: 'info'
  },
  {
    id: 'hh-platforms-nightly',
    time: '23:30',
    title: 'Облачные платформы - ночной парсинг',
    description: 'Категория PLATFORM, углубленный ночной прогон по облачным платформам',
    queueLabel: 'HeadHunter',
    queueVariant: 'danger',
    frequency: 'Ежедневно, 23:30',
    frequencyVariant: 'info'
  },
  {
    id: 'hh-top20-pulse-09',
    time: '09:00 (будни)',
    title: 'Пульс ТОП-20 - утро',
    description: 'Топ-20 технологий, легкий прогон без деталей',
    queueLabel: 'HeadHunter',
    queueVariant: 'danger',
    frequency: 'Пн-Пт, 09:00',
    frequencyVariant: 'info'
  },
  {
    id: 'hh-top20-pulse-12',
    time: '12:00 (будни)',
    title: 'Пульс ТОП-20 - день',
    description: 'Топ-20 технологий, дневной прогон',
    queueLabel: 'HeadHunter',
    queueVariant: 'danger',
    frequency: 'Пн-Пт, 12:00',
    frequencyVariant: 'info'
  },
  {
    id: 'hh-top20-pulse-15',
    time: '15:00 (будни)',
    title: 'Пульс ТОП-20 - после обеда',
    description: 'Топ-20 технологий, послеобеденный прогон',
    queueLabel: 'HeadHunter',
    queueVariant: 'danger',
    frequency: 'Пн-Пт, 15:00',
    frequencyVariant: 'info'
  },
  {
    id: 'hh-top20-pulse-18',
    time: '18:00 (будни)',
    title: 'Пульс ТОП-20 - вечер',
    description: 'Топ-20 технологий, вечерний прогон',
    queueLabel: 'HeadHunter',
    queueVariant: 'danger',
    frequency: 'Пн-Пт, 18:00',
    frequencyVariant: 'info'
  },
  {
    id: 'hh-top20-pulse-21',
    time: '21:00 (будни)',
    title: 'Пульс ТОП-20 - поздний вечер',
    description: 'Топ-20 технологий, финальный прогон дня',
    queueLabel: 'HeadHunter',
    queueVariant: 'danger',
    frequency: 'Пн-Пт, 21:00',
    frequencyVariant: 'info'
  },
  {
    id: 'hh-top40-deep-scan',
    time: '03:00',
    title: 'Глубокое сканирование ТОП-40',
    description: 'Топ-40 технологий по языкам и фреймворкам, ночной глубокий прогон',
    queueLabel: 'HeadHunter',
    queueVariant: 'danger',
    frequency: 'Ежедневно, 03:00',
    frequencyVariant: 'info'
  },
  {
    id: 'hh-weekly-comprehensive',
    time: '04:00 (вс)',
    title: 'Еженедельный полный парсинг',
    description: 'Полный парсинг по основным категориям ночью в воскресенье',
    queueLabel: 'HeadHunter',
    queueVariant: 'danger',
    frequency: 'Каждое воскресенье, 04:00',
    frequencyVariant: 'info'
  },
  {
    id: 'hh-check-vacancies-status',
    time: '05:00',
    title: 'Проверка статуса вакансий',
    description: 'Проверка актуальности существующих вакансий (batch-обновление статусов)',
    queueLabel: 'HeadHunter',
    queueVariant: 'danger',
    frequency: 'Ежедневно, 05:00',
    frequencyVariant: 'info'
  },
  {
    id: 'hh-update-professional-roles',
    time: '06:30 (вс)',
    title: 'Актуализация профессиональных ролей',
    description: 'Обновление справочника профессиональных ролей раз в неделю',
    queueLabel: 'HeadHunter',
    queueVariant: 'danger',
    frequency: 'Каждое воскресенье, 06:30',
    frequencyVariant: 'info'
  },
  {
    id: 'hh-professional-roles-comprehensive',
    time: '03:00 (пн)',
    title: 'Роли IT - полный прогон',
    description: 'Глубокий парсинг по всем IT-ролям, понедельник ночью',
    queueLabel: 'HeadHunter',
    queueVariant: 'danger',
    frequency: 'Каждый понедельник, 03:00',
    frequencyVariant: 'info'
  },
  {
    id: 'hh-professional-roles-daily',
    time: '09:00 (вт-пт)',
    title: 'Роли IT - ежедневный прогон',
    description: 'Быстрый ежедневный прогон по IT-ролям во вторник-пятницу утром',
    queueLabel: 'HeadHunter',
    queueVariant: 'danger',
    frequency: 'Вт-Пт, 09:00',
    frequencyVariant: 'info'
  },
  {
    id: 'hh-professional-roles-quick-scan',
    time: '14:30 (сб)',
    title: 'Роли IT - быстрый скан',
    description: 'Легкий субботний прогон по IT-ролям без полного углубления',
    queueLabel: 'HeadHunter',
    queueVariant: 'danger',
    frequency: 'Каждая суббота, 14:30',
    frequencyVariant: 'info'
  }
]

const SUPERJOB_TASKS = [
  {
    id: 'sj-it-catalogues-morning',
    time: '07:00 (будни)',
    title: 'IT каталоги - утренний парсинг',
    description: 'Парсинг IT вакансий по каталогу 33 (Информационные технологии), до 50 страниц',
    queueLabel: 'SuperJob',
    queueVariant: 'success',
    frequency: 'Пн-Пт, 07:00',
    frequencyVariant: 'info'
  },
  {
    id: 'sj-it-catalogues-evening',
    time: '19:00 (будни)',
    title: 'IT каталоги - вечерний парсинг',
    description: 'Парсинг IT вакансий по каталогу 33, вечерний прогон',
    queueLabel: 'SuperJob',
    queueVariant: 'success',
    frequency: 'Пн-Пт, 19:00',
    frequencyVariant: 'info'
  },
  {
    id: 'sj-it-catalogues-weekend',
    time: '12:00 (выходные)',
    title: 'IT каталоги - выходной парсинг',
    description: 'Парсинг IT вакансий по каталогу 33 в выходные',
    queueLabel: 'SuperJob',
    queueVariant: 'success',
    frequency: 'Сб-Вс, 12:00',
    frequencyVariant: 'info'
  },
  {
    id: 'sj-text-pulse-python',
    time: '08:30',
    title: 'Текстовый пульс: Python',
    description: 'Парсинг вакансий по ключевому слову Python, до 10 страниц',
    queueLabel: 'SuperJob',
    queueVariant: 'success',
    frequency: 'Ежедневно, 08:30',
    frequencyVariant: 'info'
  },
  {
    id: 'sj-text-pulse-javascript',
    time: '09:30',
    title: 'Текстовый пульс: JavaScript',
    description: 'Парсинг вакансий по ключевому слову JavaScript, до 10 страниц',
    queueLabel: 'SuperJob',
    queueVariant: 'success',
    frequency: 'Ежедневно, 09:30',
    frequencyVariant: 'info'
  },
  {
    id: 'sj-text-pulse-java',
    time: '10:30',
    title: 'Текстовый пульс: Java',
    description: 'Парсинг вакансий по ключевому слову Java, до 10 страниц',
    queueLabel: 'SuperJob',
    queueVariant: 'success',
    frequency: 'Ежедневно, 10:30',
    frequencyVariant: 'info'
  },
  {
    id: 'sj-deep-it-scan',
    time: '02:30 (вс)',
    title: 'Глубокий скан IT вакансий',
    description: 'Полный парсинг IT каталога с максимальным покрытием (до 500 страниц)',
    queueLabel: 'SuperJob',
    queueVariant: 'success',
    frequency: 'Каждое воскресенье, 02:30',
    frequencyVariant: 'info'
  },
  {
    id: 'sj-universal-parsing',
    time: '04:30',
    title: 'Универсальный парсинг SuperJob',
    description: 'Парсинг по списку IT-ключевых слов (Python, Java, C#, DevOps и др.)',
    queueLabel: 'SuperJob',
    queueVariant: 'success',
    frequency: 'Ежедневно, 04:30',
    frequencyVariant: 'info'
  },
  {
    id: 'sj-check-vacancies-status',
    time: '06:00',
    title: 'Проверка статуса вакансий SuperJob',
    description: 'Асинхронная проверка актуальности вакансий, деактивация закрытых',
    queueLabel: 'SuperJob',
    queueVariant: 'success',
    frequency: 'Ежедневно, 06:00',
    frequencyVariant: 'info'
  }
]

export const scheduleItems = [
  ...SERVICE_TASKS,
  ...HEADHUNTER_TASKS,
  ...SUPERJOB_TASKS
]
