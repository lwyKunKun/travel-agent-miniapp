/**
 * API 服务层 (uniapp 版)
 *
 * 用 uni.request 替代 axios —— 小程序环境不支持 axios/XHR。
 * 核心变化: 旅行规划改为「创建异步任务 → 轮询进度 → 取结果」三段式,
 * 规避小程序 wx.request 的超时限制 (完整规划通常 30~90 秒)。
 */

import type {
  TripFormData,
  TaskCreatedResponse,
  TaskStatusResponse,
  HistoryListResponse,
  HistoryDetailResponse,
} from '@/types'

// API 基地址: 开发期用本地, 上线改小程序后台配置的 HTTPS 合法域名
// 也可通过 vite 定义的环境变量覆盖
const API_BASE_URL =
  (import.meta as any).env?.VITE_API_BASE_URL || 'http://localhost:8000'

// 单个请求超时 (毫秒)。轮询接口本身很快, 给 15s 足够; 不再需要 Web 版的 10 分钟长超时
const REQUEST_TIMEOUT = 15000

interface RequestOptions {
  url: string
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  data?: any
  header?: Record<string, string>
}

/**
 * 统一请求封装: 把 uni.request 的回调风格包装成 Promise
 * 非 2xx 或网络错误统一 reject(Error), 错误信息优先取后端 detail
 */
function request<T = any>(options: RequestOptions): Promise<T> {
  return new Promise((resolve, reject) => {
    uni.request({
      url: API_BASE_URL + options.url,
      method: options.method || 'GET',
      data: options.data,
      timeout: REQUEST_TIMEOUT,
      header: {
        'Content-Type': 'application/json',
        ...(options.header || {}),
      },
      success: (res) => {
        const status = res.statusCode
        if (status >= 200 && status < 300) {
          resolve(res.data as T)
        } else {
          // FastAPI 校验错误 detail 可能是数组, 业务异常是字符串
          const body: any = res.data
          let msg = `请求失败 (${status})`
          if (body?.detail) {
            msg =
              typeof body.detail === 'string'
                ? body.detail
                : JSON.stringify(body.detail)
          } else if (body?.message) {
            msg = body.message
          }
          reject(new Error(msg))
        }
      },
      fail: (err) => {
        reject(new Error(err.errMsg || '网络请求失败, 请检查网络连接'))
      },
    })
  })
}

// ============ 异步任务 (小程序核心链路) ============

/**
 * 创建异步规划任务, 立即返回 task_id (不等待生成完成)
 */
export function createTripTask(formData: TripFormData): Promise<TaskCreatedResponse> {
  return request<TaskCreatedResponse>({
    url: '/api/trip/tasks',
    method: 'POST',
    data: formData,
  })
}

/**
 * 查询任务状态/进度/结果 (建议前端每 2 秒轮询一次)
 * 任务不存在或已过期时后端返回 404 → 这里 reject, 调用方提示用户重新生成
 */
export function getTripTask(taskId: string): Promise<TaskStatusResponse> {
  return request<TaskStatusResponse>({
    url: `/api/trip/tasks/${taskId}`,
    method: 'GET',
  })
}

// ============ 历史记录 ============

/**
 * 查询历史行程列表 (分页)
 */
export function fetchHistory(
  page = 1,
  pageSize = 10,
  city?: string,
): Promise<HistoryListResponse> {
  // 手动拼接查询串: 小程序环境没有 URLSearchParams
  let query = `page=${page}&page_size=${pageSize}`
  if (city) query += `&city=${encodeURIComponent(city)}`
  return request<HistoryListResponse>({
    url: `/api/history?${query}`,
    method: 'GET',
  })
}

/**
 * 查询历史行程详情 (含完整计划)
 */
export function fetchHistoryDetail(id: number): Promise<HistoryDetailResponse> {
  return request<HistoryDetailResponse>({
    url: `/api/history/${id}`,
    method: 'GET',
  })
}

/**
 * 删除历史行程
 */
export function deleteHistory(id: number): Promise<{ success: boolean; message: string }> {
  return request({
    url: `/api/history/${id}`,
    method: 'DELETE',
  })
}

// ============ 健康检查 ============

export function healthCheck(): Promise<any> {
  return request({ url: '/health', method: 'GET' })
}

export default request
