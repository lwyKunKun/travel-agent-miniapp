/**
 * 全局行程状态 (替代 Web 版的 sessionStorage)
 *
 * 小程序页面间跳转不便传大对象, 用模块级响应式 store 中转行程数据:
 * - 规划完成: progress 页写入 plan → result 页读取
 * - 查看历史: history 页写入 plan + planId → result 页读取
 */
import { reactive } from 'vue'
import type { TripPlan } from '@/types'

interface TripState {
  plan: TripPlan | null
  // 历史记录 ID: 从历史页进入时有值, 新规划为 null
  planId: number | null
}

export const tripStore = reactive<TripState>({
  plan: null,
  planId: null,
})

/** 写入新规划结果 (清除历史标识, 与 Web 版逻辑一致) */
export function setPlannedTrip(plan: TripPlan) {
  tripStore.plan = plan
  tripStore.planId = null
}

/** 写入历史行程 (带 ID) */
export function setHistoryTrip(plan: TripPlan, planId: number) {
  tripStore.plan = plan
  tripStore.planId = planId
}

export function clearTrip() {
  tripStore.plan = null
  tripStore.planId = null
}
