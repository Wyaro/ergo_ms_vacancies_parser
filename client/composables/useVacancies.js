import { ref, computed } from 'vue'
import { vacanciesApi } from '../js/api'
import { useToast } from 'vue-toastification'

export function useVacancies() {
  const toast = useToast()
  const vacancies = ref([])
  const loading = ref(false)
  const error = ref(null)
  const pagination = ref({
    count: 0,
    next: null,
    previous: null,
    page: 1,
    pageSize: 20
  })

  const loadVacancies = async (params = {}) => {
    loading.value = true
    error.value = null
    
    try {
      const response = await vacanciesApi.list({
        page: pagination.value.page,
        page_size: pagination.value.pageSize,
        ...params
      })
      
      vacancies.value = response.data.results || response.data
      
      if (response.data.count !== undefined) {
        pagination.value = {
          count: response.data.count,
          next: response.data.next,
          previous: response.data.previous,
          page: params.page || pagination.value.page,
          pageSize: params.page_size || pagination.value.pageSize
        }
      }
      
      return response.data
    } catch (err) {
      error.value = err
      toast.error('Ошибка при загрузке вакансий')
      throw err
    } finally {
      loading.value = false
    }
  }

  const loadVacancy = async (id) => {
    loading.value = true
    error.value = null
    
    try {
      const response = await vacanciesApi.get(id)
      return response.data
    } catch (err) {
      error.value = err
      toast.error('Ошибка при загрузке вакансии')
      throw err
    } finally {
      loading.value = false
    }
  }

  const hasNextPage = computed(() => !!pagination.value.next)
  const hasPreviousPage = computed(() => !!pagination.value.previous)
  const totalPages = computed(() => 
    Math.ceil(pagination.value.count / pagination.value.pageSize)
  )

  return {
    vacancies,
    loading,
    error,
    pagination,
    loadVacancies,
    loadVacancy,
    hasNextPage,
    hasPreviousPage,
    totalPages
  }
}
