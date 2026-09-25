<template>
  <view class="page" v-if="plan">
    <!-- 头部概览 -->
    <view class="header-card glass-card">
      <view class="header-city">📍 {{ plan.city }}</view>
      <view class="header-dates">{{ plan.start_date }} ~ {{ plan.end_date }} · {{ plan.days.length }} 天</view>
      <view class="header-budget" v-if="plan.budget">
        预计总花费 <text class="budget-num">¥{{ plan.budget.total }}</text>
      </view>
    </view>

    <!-- 降级警告横幅 (LLM 失败兜底时展示, 不伪装成功) -->
    <view v-if="plan.is_fallback" class="fallback-banner">
      ⚠️ 降级模式：AI 生成失败，当前行程由高德真实数据兜底生成{{ plan.fallback_reason ? '（' + plan.fallback_reason + '）' : '' }}
    </view>

    <!-- 行程地图 (小程序原生 map 组件, 替代 Web 版高德 JS API) -->
    <view class="glass-card" v-if="markers.length">
      <view class="section-title"><text class="icon">🗺️</text>行程地图</view>
      <map
        class="trip-map"
        :latitude="mapCenter.latitude"
        :longitude="mapCenter.longitude"
        :markers="markers"
        :include-points="includePoints"
        scale="12"
      ></map>
      <view class="map-tip">共 {{ markers.length }} 个地点，点击标记查看详情</view>
    </view>

    <!-- 每日行程 -->
    <view v-for="day in plan.days" :key="day.day_index" class="glass-card day-card">
      <view class="day-header">
        <view class="day-badge">第 {{ day.day_index + 1 }} 天</view>
        <view class="day-date">{{ day.date }}</view>
      </view>

      <!-- 当日天气 -->
      <view class="day-weather" v-if="weatherOf(day.date)">
        🌤️ {{ weatherOf(day.date)!.day_weather }} {{ weatherOf(day.date)!.night_temp }}~{{ weatherOf(day.date)!.day_temp }}℃
        · {{ weatherOf(day.date)!.wind_direction }}{{ weatherOf(day.date)!.wind_power }}
      </view>

      <view class="day-desc">{{ day.description }}</view>

      <!-- 景点列表 -->
      <view v-for="(item, idx) in day.attractions" :key="idx" class="spot-card">
        <image
          v-if="item.image_url"
          class="spot-img"
          :src="item.image_url"
          mode="aspectFill"
          lazy-load
          @error="(e: any) => onImgError(e)"
        />
        <view class="spot-info">
          <view class="spot-name">{{ idx + 1 }}. {{ item.name }}</view>
          <!-- 来源标签: 高德蓝 / 知识库绿 / AI橙 -->
          <view class="spot-tags">
            <text
              v-for="src in item.sources || []"
              :key="src"
              class="tag"
              :class="sourceClass(src)"
            >{{ src }}</text>
            <text v-if="item.ticket_price" class="tag tag-price">🎫 ¥{{ item.ticket_price }}</text>
            <text v-if="item.visit_duration" class="tag tag-duration">⏱️ {{ item.visit_duration }}分钟</text>
          </view>
          <view class="spot-addr" v-if="item.address">📍 {{ item.address }}</view>
          <view class="spot-desc" v-if="item.description">{{ item.description }}</view>
        </view>
      </view>

      <!-- 餐饮 -->
      <view v-if="day.meals?.length" class="meals-box">
        <view class="meals-title">🍜 餐饮推荐</view>
        <view v-for="(meal, mi) in day.meals" :key="mi" class="meal-item">
          <text class="meal-type">{{ mealLabel(meal.type) }}</text>
          <view class="meal-body">
            <view class="meal-name">{{ meal.name }}</view>
            <view class="meal-addr" v-if="meal.address">{{ meal.address }}</view>
          </view>
          <text class="meal-cost" v-if="meal.estimated_cost">¥{{ meal.estimated_cost }}</text>
        </view>
      </view>

      <!-- 酒店 -->
      <view v-if="day.hotel" class="hotel-box">
        <view class="meals-title">🏨 住宿推荐</view>
        <view class="hotel-name">{{ day.hotel.name }}</view>
        <view class="hotel-meta">
          <text v-if="day.hotel.price_range">{{ day.hotel.price_range }}</text>
          <text v-if="day.hotel.rating"> · {{ day.hotel.rating }}分</text>
          <text v-if="day.hotel.estimated_cost"> · ¥{{ day.hotel.estimated_cost }}/晚</text>
        </view>
        <view class="meal-addr" v-if="day.hotel.address">{{ day.hotel.address }}</view>
      </view>
    </view>

    <!-- 预算明细 -->
    <view class="glass-card" v-if="plan.budget">
      <view class="section-title"><text class="icon">💰</text>预算明细</view>
      <view class="budget-grid">
        <view class="budget-item">
          <view class="budget-label">景点门票</view>
          <view class="budget-value">¥{{ plan.budget.total_attractions }}</view>
        </view>
        <view class="budget-item">
          <view class="budget-label">酒店住宿</view>
          <view class="budget-value">¥{{ plan.budget.total_hotels }}</view>
        </view>
        <view class="budget-item">
          <view class="budget-label">餐饮费用</view>
          <view class="budget-value">¥{{ plan.budget.total_meals }}</view>
        </view>
        <view class="budget-item">
          <view class="budget-label">交通费用</view>
          <view class="budget-value">¥{{ plan.budget.total_transportation }}</view>
        </view>
      </view>
      <view class="budget-total">
        合计 <text class="budget-num">¥{{ plan.budget.total }}</text>
      </view>
    </view>

    <!-- 天气预报表 -->
    <view class="glass-card" v-if="plan.weather_info?.length">
      <view class="section-title"><text class="icon">🌤️</text>天气预报</view>
      <view v-for="w in plan.weather_info" :key="w.date" class="weather-row">
        <text class="weather-date">{{ w.date }}</text>
        <text class="weather-text">{{ w.day_weather }}转{{ w.night_weather }}</text>
        <text class="weather-temp">{{ w.night_temp }}~{{ w.day_temp }}℃</text>
      </view>
    </view>

    <!-- 总体建议 -->
    <view class="glass-card" v-if="plan.overall_suggestions">
      <view class="section-title"><text class="icon">💡</text>总体建议</view>
      <view class="suggestions">{{ plan.overall_suggestions }}</view>
    </view>

    <view class="footer">AI 生成内容仅供参考，出行前请核实门票与开放时间</view>
  </view>

  <!-- 空态: 直接访问/store 为空 -->
  <view v-else class="page empty-page">
    <view class="empty-icon">🧳</view>
    <view class="empty-text">暂无行程数据</view>
    <button class="btn-primary empty-btn" @tap="goHome">去规划一趟旅行</button>
  </view>
</template>

<script setup lang="ts">
/**
 * 行程结果页 (迁移自 Web 版 Result.vue, 移动端重构)
 *
 * 数据来源: 全局 store (progress 页规划完成写入 / history 页查看详情写入)
 * 地图: 小程序原生 <map> 组件替代 Web 版高德 JS API,
 *       markers 汇总所有天景点+酒店坐标, include-points 自动缩放到全览
 */
import { computed } from 'vue'
import { tripStore } from '@/store/trip'

const plan = computed(() => tripStore.plan)

/** 来源标签样式映射 (与 Web 版三色一致) */
function sourceClass(src: string): string {
  if (src.includes('高德')) return 'tag-amap'
  if (src.includes('知识库')) return 'tag-kb'
  return 'tag-ai'
}

const mealLabels: Record<string, string> = {
  breakfast: '🌅 早餐',
  lunch: '☀️ 午餐',
  dinner: '🌙 晚餐',
  snack: '🍡 小吃',
}
function mealLabel(type: string): string {
  return mealLabels[type] || type
}

/** 按日期取天气 */
function weatherOf(date: string) {
  return plan.value?.weather_info?.find((w) => w.date === date)
}

// ============ 地图 ============

interface Marker {
  id: number
  latitude: number
  longitude: number
  title: string
  width: number
  height: number
  callout?: any
}

const markers = computed<Marker[]>(() => {
  if (!plan.value) return []
  const list: Marker[] = []
  let id = 1
  for (const day of plan.value.days) {
    for (const a of day.attractions || []) {
      if (a.location?.latitude && a.location?.longitude) {
        list.push({
          id: id++,
          latitude: a.location.latitude,
          longitude: a.location.longitude,
          title: a.name,
          width: 28,
          height: 28,
          callout: {
            content: `D${day.day_index + 1} · ${a.name}`,
            color: '#ffffff',
            bgColor: '#667eea',
            padding: 8,
            borderRadius: 8,
            display: 'BYCLICK',
          },
        })
      }
    }
    if (day.hotel?.location?.latitude) {
      list.push({
        id: id++,
        latitude: day.hotel.location.latitude,
        longitude: day.hotel.location.longitude,
        title: day.hotel.name,
        width: 28,
        height: 28,
        callout: {
          content: `🏨 ${day.hotel.name}`,
          color: '#ffffff',
          bgColor: '#764ba2',
          padding: 8,
          borderRadius: 8,
          display: 'BYCLICK',
        },
      })
    }
  }
  return list
})

// include-points: 让地图自动缩放到包含所有标记
const includePoints = computed(() =>
  markers.value.map((m) => ({ latitude: m.latitude, longitude: m.longitude })),
)

// 地图初始中心: 所有标记的均值 (include-points 生效后会自动调整)
const mapCenter = computed(() => {
  const ms = markers.value
  if (!ms.length) return { latitude: 39.9042, longitude: 116.4074 } // 默认北京
  return {
    latitude: ms.reduce((s, m) => s + m.latitude, 0) / ms.length,
    longitude: ms.reduce((s, m) => s + m.longitude, 0) / ms.length,
  }
})

function onImgError(e: any) {
  // 图片加载失败静默处理 (v-if 已保证无图不渲染, 此处防 403 等运行时错误刷屏)
  console.warn('景点图片加载失败', e?.detail?.errMsg || '')
}

function goHome() {
  uni.switchTab({ url: '/pages/index/index' })
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  padding: 24rpx 32rpx 60rpx;
  background: linear-gradient(180deg, #1e1b4b 0%, #0f172a 30%);
}

/* 头部 */
.header-card {
  text-align: center;
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.25), rgba(118, 75, 162, 0.25));
}

.header-city {
  font-size: 44rpx;
  font-weight: 800;
  color: #e0e7ff;
}

.header-dates {
  font-size: 26rpx;
  color: rgba(226, 232, 255, 0.75);
  margin-top: 8rpx;
}

.header-budget {
  margin-top: 16rpx;
  font-size: 26rpx;
  color: #99f6e4;
}

.budget-num {
  font-size: 40rpx;
  font-weight: 700;
}

/* 降级横幅 */
.fallback-banner {
  background: rgba(245, 158, 11, 0.15);
  border: 1rpx solid rgba(245, 158, 11, 0.4);
  color: #fcd34d;
  border-radius: 16rpx;
  padding: 20rpx 24rpx;
  font-size: 24rpx;
  margin-bottom: 24rpx;
}

/* 地图 */
.trip-map {
  width: 100%;
  height: 420rpx;
  border-radius: 16rpx;
}

.map-tip {
  margin-top: 12rpx;
  font-size: 22rpx;
  color: rgba(148, 163, 184, 0.7);
  text-align: center;
}

/* 每日行程 */
.day-header {
  display: flex;
  align-items: center;
  margin-bottom: 16rpx;
}

.day-badge {
  background: linear-gradient(135deg, #667eea, #764ba2);
  color: #fff;
  font-size: 26rpx;
  font-weight: 700;
  padding: 8rpx 24rpx;
  border-radius: 28rpx;
  margin-right: 16rpx;
}

.day-date {
  font-size: 26rpx;
  color: rgba(226, 232, 240, 0.7);
}

.day-weather {
  font-size: 24rpx;
  color: #93c5fd;
  background: rgba(59, 130, 246, 0.1);
  border-radius: 12rpx;
  padding: 12rpx 20rpx;
  margin-bottom: 16rpx;
}

.day-desc {
  font-size: 26rpx;
  color: rgba(226, 232, 240, 0.85);
  margin-bottom: 24rpx;
}

/* 景点卡片 */
.spot-card {
  display: flex;
  background: rgba(15, 23, 42, 0.5);
  border: 1rpx solid rgba(255, 255, 255, 0.08);
  border-radius: 16rpx;
  padding: 20rpx;
  margin-bottom: 16rpx;
}

.spot-img {
  width: 160rpx;
  height: 160rpx;
  border-radius: 12rpx;
  flex-shrink: 0;
  margin-right: 20rpx;
  background: rgba(255, 255, 255, 0.05);
}

.spot-info {
  flex: 1;
  min-width: 0;
}

.spot-name {
  font-size: 28rpx;
  font-weight: 600;
  color: #e0e7ff;
  margin-bottom: 8rpx;
}

.spot-tags {
  display: flex;
  flex-wrap: wrap;
  margin-bottom: 8rpx;
}

.tag-price {
  background: rgba(239, 68, 68, 0.15);
  color: #fca5a5;
  border: 1rpx solid rgba(239, 68, 68, 0.35);
}

.tag-duration {
  background: rgba(148, 163, 184, 0.15);
  color: #cbd5e1;
  border: 1rpx solid rgba(148, 163, 184, 0.3);
}

.spot-addr {
  font-size: 22rpx;
  color: rgba(148, 163, 184, 0.9);
  margin-bottom: 6rpx;
}

.spot-desc {
  font-size: 24rpx;
  color: rgba(226, 232, 240, 0.75);
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  overflow: hidden;
}

/* 餐饮/酒店 */
.meals-box,
.hotel-box {
  background: rgba(15, 23, 42, 0.5);
  border: 1rpx solid rgba(255, 255, 255, 0.08);
  border-radius: 16rpx;
  padding: 20rpx;
  margin-bottom: 16rpx;
}

.meals-title {
  font-size: 26rpx;
  font-weight: 600;
  color: #e0e7ff;
  margin-bottom: 12rpx;
}

.meal-item {
  display: flex;
  align-items: center;
  padding: 10rpx 0;
  border-bottom: 1rpx solid rgba(255, 255, 255, 0.05);
}

.meal-item:last-child {
  border-bottom: none;
}

.meal-type {
  font-size: 24rpx;
  color: #a5b4fc;
  width: 130rpx;
  flex-shrink: 0;
}

.meal-body {
  flex: 1;
  min-width: 0;
}

.meal-name {
  font-size: 26rpx;
  color: #e2e8f0;
}

.meal-addr {
  font-size: 22rpx;
  color: rgba(148, 163, 184, 0.8);
}

.meal-cost {
  font-size: 24rpx;
  color: #99f6e4;
  flex-shrink: 0;
  margin-left: 12rpx;
}

.hotel-name {
  font-size: 28rpx;
  font-weight: 600;
  color: #e0e7ff;
}

.hotel-meta {
  font-size: 24rpx;
  color: #99f6e4;
  margin: 6rpx 0;
}

/* 预算 */
.budget-grid {
  display: flex;
  flex-wrap: wrap;
}

.budget-item {
  width: 50%;
  padding: 16rpx 0;
}

.budget-label {
  font-size: 24rpx;
  color: rgba(148, 163, 184, 0.9);
}

.budget-value {
  font-size: 32rpx;
  font-weight: 700;
  color: #e0e7ff;
  margin-top: 4rpx;
}

.budget-total {
  text-align: right;
  padding-top: 16rpx;
  border-top: 1rpx solid rgba(255, 255, 255, 0.1);
  font-size: 26rpx;
  color: rgba(226, 232, 240, 0.8);
}

/* 天气表 */
.weather-row {
  display: flex;
  justify-content: space-between;
  padding: 14rpx 0;
  border-bottom: 1rpx solid rgba(255, 255, 255, 0.05);
  font-size: 24rpx;
}

.weather-row:last-child {
  border-bottom: none;
}

.weather-date {
  color: rgba(226, 232, 240, 0.8);
}

.weather-text {
  color: #93c5fd;
}

.weather-temp {
  color: #99f6e4;
}

/* 建议 */
.suggestions {
  font-size: 26rpx;
  color: rgba(226, 232, 240, 0.85);
  white-space: pre-wrap;
}

.footer {
  text-align: center;
  margin-top: 32rpx;
  font-size: 22rpx;
  color: rgba(148, 163, 184, 0.6);
}

/* 空态 */
.empty-page {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

.empty-icon {
  font-size: 120rpx;
  margin-bottom: 24rpx;
}

.empty-text {
  font-size: 30rpx;
  color: rgba(226, 232, 240, 0.7);
  margin-bottom: 40rpx;
}

.empty-btn {
  width: 400rpx;
  height: 88rpx;
  line-height: 88rpx;
}
</style>
