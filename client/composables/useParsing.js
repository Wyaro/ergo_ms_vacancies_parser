import { ref } from 'vue'
import { sourceApi } from '../js/api'
import { useToast } from 'vue-toastification'

export function useParsing() {
  const toast = useToast()
  const parsing = ref(false)
  const taskId = ref(null)
  const taskStatus = ref(null)

  const _wrapParsing = async (label, fn) => {
    parsing.value = true
    taskId.value = null
    taskStatus.value = null

    try {
      const response = await fn()
      const data = response.data || response
      taskId.value = data.task_id || data.id
      toast.success(`${label} запущен`)
      return data
    } catch (err) {
      toast.error(`Ошибка при запуске: ${label}`)
      throw err
    } finally {
      parsing.value = false
    }
  }

  const parseByText = (source, config = {}) =>
    _wrapParsing('Парсинг по тексту', () => sourceApi.parseByText(source, config))

  const parseByRoles = (source, config = {}) =>
    _wrapParsing('Парсинг по ролям', () => sourceApi.parseByRoles(source, config))

  const parseByTechnologies = (source, config = {}) =>
    _wrapParsing('Парсинг по технологиям', () => sourceApi.parseByTechnologies(source, config))

  const parseByCatalogues = (source, config = {}) =>
    _wrapParsing('Парсинг по каталогам', () => sourceApi.parseByCatalogues(source, config))

  const parseAll = (source, config = {}) =>
    _wrapParsing('Универсальный парсинг', () => sourceApi.parseAll(source, config))

  const checkTaskStatus = async (source, taskIdToCheck = null) => {
    const id = taskIdToCheck || taskId.value
    if (!id) return null

    try {
      const response = await sourceApi.getTaskStatus(source, id)
      taskStatus.value = response.data
      return response.data
    } catch (err) {
      toast.error('Ошибка при проверке статуса задачи')
      throw err
    }
  }

  const reset = () => {
    parsing.value = false
    taskId.value = null
    taskStatus.value = null
  }

  return {
    parsing,
    taskId,
    taskStatus,
    parseByText,
    parseByRoles,
    parseByTechnologies,
    parseByCatalogues,
    parseAll,
    checkTaskStatus,
    reset
  }
}
