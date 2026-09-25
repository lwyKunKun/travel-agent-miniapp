// 类型定义 (迁移自 Web 版 + 小程序异步任务类型)

export interface Location {
  longitude: number
  latitude: number
}

export interface Attraction {
  name: string
  address: string
  location: Location
  visit_duration: number
  description: string
  category?: string
  rating?: number
  image_url?: string
  ticket_price?: number
  // 信息来源标签: 高德地图 / 知识库 / AI推荐·需核实 (旧历史记录无此字段)
  sources?: string[]
}

export interface Meal {
  type: 'breakfast' | 'lunch' | 'dinner' | 'snack'
  name: string
  address?: string
  location?: Location
  description?: string
  estimated_cost?: number
}

export interface Hotel {
  name: string
  address: string
  location?: Location
  price_range: string
  rating: string
  distance: string
  type: string
  estimated_cost?: number
}

export interface Budget {
  total_attractions: number
  total_hotels: number
  total_meals: number
  total_transportation: number
  total: number
}

export interface DayPlan {
  date: string
  day_index: number
  description: string
  transportation: string
  accommodation: string
  hotel?: Hotel
  attractions: Attraction[]
  meals: Meal[]
}

export interface WeatherInfo {
  date: string
  day_weather: string
  night_weather: string
  day_temp: number
  night_temp: number
  wind_direction: string
  wind_power: string
}

export interface TripPlan {
  city: string
  start_date: string
  end_date: string
  days: DayPlan[]
  weather_info: WeatherInfo[]
  overall_suggestions: string
  budget?: Budget
  // 降级标记: LLM 生成失败时为 true, 前端展示警告横幅
  is_fallback?: boolean
  fallback_reason?: string
}

export interface TripFormData {
  city: string
  start_date: string
  end_date: string
  travel_days: number
  transportation: string
  accommodation: string
  preferences: string[]
  free_text_input: string
}

// ============ 认证 ============

export interface LoginResponse {
  success: boolean
  token: string
  expires_in: number
  user_id: number
  is_new_user: boolean
  mock_mode: boolean
}

// ============ 异步任务 (小程序专用) ============

export interface TaskCreatedResponse {
  success: boolean
  task_id: string
  status: 'pending' | 'running' | 'completed' | 'failed'
}

export interface TaskStatusResponse {
  success: boolean
  task_id: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  stage: string
  progress: number
  created_at: string
  finished_at?: string | null
  error?: string | null
  data?: TripPlan | null
}

// ============ 历史记录 ============

export interface HistorySummary {
  id: number
  city: string
  start_date: string
  end_date: string
  travel_days: number
  transportation: string
  accommodation: string
  preferences: string[]
  created_at: string
  attraction_count: number
  budget_total: number
}

export interface HistoryListResponse {
  success: boolean
  data: HistorySummary[]
  total: number
  page: number
  page_size: number
}

export interface HistoryDetailResponse {
  success: boolean
  data: {
    id: number
    city: string
    start_date: string
    end_date: string
    travel_days: number
    transportation: string
    accommodation: string
    preferences: string[]
    free_text_input: string
    plan: TripPlan
    created_at: string
  }
}
