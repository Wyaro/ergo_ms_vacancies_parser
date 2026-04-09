import { apiClient } from '@/js/api/manager'
import { endpoints, getSourceEndpoints } from './endpoints'

export const tasksApi = {
  async list(params = {}) {
    return apiClient.get(endpoints.tasks.list, params)
  },
  async get(id) {
    return apiClient.get(endpoints.tasks.detail(id))
  },
  async create(data) {
    return apiClient.post(endpoints.tasks.create, data)
  },
  async update(id, data) {
    return apiClient.patch(endpoints.tasks.update(id), data)
  },
  async delete(id) {
    return apiClient.delete(endpoints.tasks.delete(id))
  },
  async getProgress(id) {
    return apiClient.get(endpoints.tasks.progress(id))
  },
  async pause(id) {
    return apiClient.post(endpoints.tasks.pause(id))
  },
  async resume(id) {
    return apiClient.post(endpoints.tasks.resume(id))
  },
  async stop(id) {
    return apiClient.post(endpoints.tasks.stop(id))
  },
  async getItems(id, params = {}) {
    return apiClient.get(endpoints.tasks.items(id), params)
  },
  async getStatistics(id) {
    return apiClient.get(endpoints.tasks.statistics(id))
  },
  async getSources() {
    return apiClient.get(endpoints.tasks.sources)
  }
}

export const vacanciesApi = {
  async list(params = {}) {
    return apiClient.get(endpoints.vacancies.list, params)
  },
  async get(id) {
    return apiClient.get(endpoints.vacancies.detail(id))
  },
  async getChanges(id, versionNumber = null) {
    const params = versionNumber ? { version: versionNumber } : {}
    return apiClient.get(endpoints.vacancies.changes(id), params)
  },
  async exportCsv(params = {}) {
    return apiClient.downloadFile(endpoints.vacancies.export, params)
  }
}

export const statisticsApi = {
  async list(params = {}) {
    return apiClient.get(endpoints.statistics.list, params)
  },
  async get(id) {
    return apiClient.get(endpoints.statistics.detail(id))
  }
}

export const sourceApi = {
  async getVacancies(source, params = {}) {
    return apiClient.get(getSourceEndpoints(source).vacancies.list, params)
  },
  async getVacancy(source, id) {
    return apiClient.get(getSourceEndpoints(source).vacancies.detail(id))
  },
  async getVersions(source, id) {
    return apiClient.get(getSourceEndpoints(source).vacancies.versions(id))
  },
  async getVersionDetail(source, id, versionNumber) {
    return apiClient.get(getSourceEndpoints(source).vacancies.versionDetail(id), { version: versionNumber })
  },
  async getStats(source, params = {}) {
    return apiClient.get(getSourceEndpoints(source).vacancies.stats, params)
  },
  async getTaskStatus(source, taskId) {
    return apiClient.get(getSourceEndpoints(source).vacancies.taskStatus, { task_id: taskId })
  },
  async parseSingle(source, data) {
    return apiClient.post(getSourceEndpoints(source).vacancies.parseSingle, data)
  },
  async getDetails(source, data) {
    return apiClient.post(getSourceEndpoints(source).parsing.getDetails, data)
  },
  async parseByText(source, data) {
    return apiClient.post(getSourceEndpoints(source).parsing.parseByText, data)
  },
  async parseAll(source, data) {
    return apiClient.post(getSourceEndpoints(source).parsing.parseAll, data)
  },
  async parseByConfig(source, data) {
    return apiClient.post(getSourceEndpoints(source).parsing.parseByConfig, data)
  },
  async parseByRoles(source, data) {
    return apiClient.post(getSourceEndpoints(source).parsing.parseByRoles, data)
  },
  async parseByTechnologies(source, data) {
    return apiClient.post(getSourceEndpoints(source).parsing.parseByTechnologies, data)
  },
  async parseByCatalogues(source, data) {
    return apiClient.post(getSourceEndpoints(source).parsing.parseByCatalogues, data)
  },
  async getCatalogues(source) {
    return apiClient.get(getSourceEndpoints(source).parsing.catalogues)
  }
}

export const monitoringApi = {
  async listTaskRuns(params = {}) {
    return apiClient.get(endpoints.taskRuns.list, params)
  },
  async getTaskRun(id) {
    return apiClient.get(endpoints.taskRuns.detail(id))
  },
  async listExternalApiEvents(params = {}) {
    return apiClient.get(endpoints.externalApiEvents.list, params)
  }
}

export const systemApi = {
  async listJobs() {
    return apiClient.get(endpoints.systemJobs.list)
  },
  async runJob(jobId, payload = {}) {
    return apiClient.post(endpoints.systemJobs.run(jobId), payload)
  }
}
