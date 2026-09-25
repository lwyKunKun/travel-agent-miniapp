<template>
  <view class="page">
    <!-- 页头 -->
    <view class="hero">
      <view class="brand-badge">⚡ LangChain AI 驱动</view>
      <view class="hero-icon">✈️</view>
      <view class="hero-title">智能旅行助手</view>
      <view class="hero-subtitle">输入目的地，AI 为你规划每一天的吃、住、行、玩</view>

      <!-- 热门目的地快捷选择 (迁移自 Web 版 Home.vue) -->
      <view class="hot-cities">
        <text class="hot-label">热门目的地</text>
        <view class="hot-tags">
          <text
            v-for="city in hotCities"
            :key="city"
            class="hot-tag"
            :class="{ active: formData.city === city }"
            @tap="formData.city = city"
          >{{ city }}</text>
        </view>
      </view>
    </view>

    <!-- 目的地与日期 -->
    <view class="glass-card form-section">
      <view class="section-title"><text class="icon">📍</text>目的地与日期</view>

      <view class="field">
        <text class="field-label">目的地城市</text>
        <input
          v-model="formData.city"
          class="field-input"
          placeholder="例如: 北京"
          placeholder-class="field-placeholder"
        />
      </view>

      <view class="field-row">
        <view class="field field-half">
          <text class="field-label">开始日期</text>
          <picker mode="date" :value="formData.start_date" :start="today" @change="onStartChange">
            <view class="field-picker" :class="{ empty: !formData.start_date }">
              {{ formData.start_date || '选择日期' }}
            </view>
          </picker>
        </view>
        <view class="field field-half">
          <text class="field-label">结束日期</text>
          <picker mode="date" :value="formData.end_date" :start="minEndDate" @change="onEndChange">
            <view class="field-picker" :class="{ empty: !formData.end_date }">
              {{ formData.end_date || '选择日期' }}
            </view>
          </picker>
        </view>
      </view>

      <view class="days-banner">
        <text class="days-value">{{ formData.travel_days }}</text>
        <text class="days-unit">天行程</text>
      </view>
    </view>

    <!-- 偏好设置 -->
    <view class="glass-card form-section">
      <view class="section-title"><text class="icon">⚙️</text>偏好设置</view>

      <view class="field">
        <text class="field-label">交通方式</text>
        <picker :range="transportOptions" :value="transportIndex" @change="onTransportChange">
          <view class="field-picker">{{ transportOptions[transportIndex] }}</view>
        </picker>
      </view>

      <view class="field">
        <text class="field-label">住宿偏好</text>
        <picker :range="accommodationOptions" :value="accommodationIndex" @change="onAccommodationChange">
          <view class="field-picker">{{ accommodationOptions[accommodationIndex] }}</view>
        </picker>
      </view>

      <view class="field">
        <text class="field-label">旅行偏好 (可多选)</text>
        <view class="pref-tags">
          <text
            v-for="p in preferenceOptions"
            :key="p.value"
            class="pref-tag"
            :class="{ active: formData.preferences.includes(p.value) }"
            @tap="togglePreference(p.value)"
          >{{ p.label }}</text>
        </view>
      </view>
    </view>

    <!-- 额外要求 -->
    <view class="glass-card form-section">
      <view class="section-title"><text class="icon">💬</text>额外要求</view>
      <textarea
        v-model="formData.free_text_input"
        class="field-textarea"
        placeholder="例如: 想去看升旗、需要无障碍设施、对海鲜过敏等..."
        placeholder-class="field-placeholder"
        :maxlength="500"
      />
    </view>

    <!-- 提交 -->
    <button class="btn-primary submit-btn" :loading="submitting" :disabled="submitting" @tap="handleSubmit">
      {{ submitting ? '任务创建中...' : '🚀 开始规划我的旅行' }}
    </button>

    <view class="footer">Powered by LangChain · LangGraph · FastAPI · 高德地图</view>
  </view>
</template>

<script setup lang="ts">
import { reactive, ref, computed } from 'vue'
import { createTripTask } from '@/services/api'

// 热门目的地 (与 Web 版一致)
const hotCities = ['北京', '上海', '杭州', '成都', '西安', '桂林', '丽江', '重庆']

const transportOptions = ['🚇 公共交通', '🚗 自驾', '🚶 步行', '🔀 混合']
const transportValues = ['公共交通', '自驾', '步行', '混合']
const accommodationOptions = ['💰 经济型酒店', '🏨 舒适型酒店', '⭐ 豪华酒店', '🏡 民宿']
const accommodationValues = ['经济型酒店', '舒适型酒店', '豪华酒店', '民宿']
const preferenceOptions = [
  { label: '🏛️ 历史文化', value: '历史文化' },
  { label: '🏞️ 自然风光', value: '自然风光' },
  { label: '🍜 美食', value: '美食' },
  { label: '🛍️ 购物', value: '购物' },
  { label: '🎨 艺术', value: '艺术' },
  { label: '☕ 休闲', value: '休闲' },
]

const transportIndex = ref(0)
const accommodationIndex = ref(0)
const submitting = ref(false)

const formData = reactive({
  city: '',
  start_date: '',
  end_date: '',
  travel_days: 1,
  transportation: transportValues[0],
  accommodation: accommodationValues[0],
  preferences: [] as string[],
  free_text_input: '',
})

// 今天 (日期选择器最小值)
const today = new Date().toISOString().slice(0, 10)
// 结束日期最小值 = 开始日期 (未选则为今天)
const minEndDate = computed(() => formData.start_date || today)

/** 日期字符串差值天数 (含首尾, 与 Web 版 dayjs diff+1 逻辑一致) */
function diffDays(start: string, end: string): number {
  const s = new Date(start.replace(/-/g, '/')).getTime()
  const e = new Date(end.replace(/-/g, '/')).getTime()
  return Math.round((e - s) / 86400000) + 1
}

function onStartChange(e: any) {
  formData.start_date = e.detail.value
  // 开始日期变化后重新校验已选的结束日期
  if (formData.end_date) {
    validateRange()
  }
}

function onEndChange(e: any) {
  formData.end_date = e.detail.value
  validateRange()
}

/** 校验日期范围并同步天数 (结束早于开始 / 超30天 → 清空结束日期) */
function validateRange() {
  const days = diffDays(formData.start_date, formData.end_date)
  if (days < 1) {
    uni.showToast({ title: '结束日期不能早于开始日期', icon: 'none' })
    formData.end_date = ''
    formData.travel_days = 1
  } else if (days > 30) {
    uni.showToast({ title: '旅行天数不能超过30天', icon: 'none' })
    formData.end_date = ''
    formData.travel_days = 1
  } else {
    formData.travel_days = days
  }
}

function onTransportChange(e: any) {
  transportIndex.value = Number(e.detail.value)
  formData.transportation = transportValues[transportIndex.value]
}

function onAccommodationChange(e: any) {
  accommodationIndex.value = Number(e.detail.value)
  formData.accommodation = accommodationValues[accommodationIndex.value]
}

function togglePreference(value: string) {
  const idx = formData.preferences.indexOf(value)
  if (idx >= 0) formData.preferences.splice(idx, 1)
  else formData.preferences.push(value)
}

/**
 * 提交: 创建异步任务 → 跳转进度页轮询
 * (Web 版是同步等待 + 前端模拟进度; 小程序版走后端真实任务进度)
 */
async function handleSubmit() {
  if (!formData.city.trim()) {
    uni.showToast({ title: '请输入目的地城市', icon: 'none' })
    return
  }
  if (!formData.start_date || !formData.end_date) {
    uni.showToast({ title: '请选择出行日期', icon: 'none' })
    return
  }

  submitting.value = true
  try {
    const res = await createTripTask({ ...formData, city: formData.city.trim() })
    uni.navigateTo({ url: `/pages/progress/progress?task_id=${res.task_id}` })
  } catch (e: any) {
    uni.showModal({
      title: '创建任务失败',
      content: e.message || '请稍后重试',
      showCancel: false,
    })
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  padding: 0 32rpx 60rpx;
  background: linear-gradient(180deg, #1e1b4b 0%, #0f172a 40%);
}

/* 页头 */
.hero {
  padding: 100rpx 0 48rpx;
  text-align: center;
}

.brand-badge {
  display: inline-block;
  padding: 8rpx 28rpx;
  border-radius: 32rpx;
  font-size: 24rpx;
  font-weight: 600;
  color: #a5b4fc;
  background: rgba(255, 255, 255, 0.08);
  border: 1rpx solid rgba(165, 180, 252, 0.3);
  margin-bottom: 32rpx;
}

.hero-icon {
  font-size: 120rpx;
  margin-bottom: 16rpx;
}

.hero-title {
  font-size: 64rpx;
  font-weight: 800;
  letter-spacing: 4rpx;
  background: linear-gradient(135deg, #a5b4fc 0%, #e0e7ff 40%, #c4b5fd 70%, #99f6e4 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  margin-bottom: 12rpx;
}

.hero-subtitle {
  font-size: 26rpx;
  color: rgba(226, 232, 255, 0.7);
  font-weight: 300;
}

/* 热门城市 */
.hot-cities {
  margin-top: 40rpx;
}

.hot-label {
  font-size: 24rpx;
  color: rgba(255, 255, 255, 0.6);
}

.hot-tags {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 16rpx;
  margin-top: 16rpx;
}

.hot-tag {
  padding: 8rpx 28rpx;
  border-radius: 32rpx;
  font-size: 26rpx;
  background: rgba(255, 255, 255, 0.08);
  color: #e2e8f0;
  border: 1rpx solid rgba(255, 255, 255, 0.2);
}

.hot-tag.active {
  background: linear-gradient(135deg, #667eea, #764ba2);
  color: #fff;
  font-weight: 600;
  border-color: transparent;
}

/* 表单 */
.form-section {
  margin-top: 24rpx;
}

.field {
  margin-bottom: 28rpx;
}

.field-row {
  display: flex;
  gap: 20rpx;
}

.field-half {
  flex: 1;
}

.field-label {
  display: block;
  font-size: 26rpx;
  color: rgba(226, 232, 240, 0.8);
  margin-bottom: 12rpx;
}

.field-input,
.field-picker,
.field-textarea {
  background: rgba(15, 23, 42, 0.6);
  border: 2rpx solid rgba(255, 255, 255, 0.15);
  border-radius: 16rpx;
  padding: 20rpx 24rpx;
  font-size: 28rpx;
  color: #e2e8f0;
  width: auto;
}

.field-picker.empty {
  color: rgba(148, 163, 184, 0.6);
}

.field-placeholder {
  color: rgba(148, 163, 184, 0.6);
}

.field-textarea {
  width: auto;
  height: 160rpx;
}

/* 天数横幅 */
.days-banner {
  display: flex;
  align-items: baseline;
  justify-content: center;
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.3), rgba(118, 75, 162, 0.3));
  border: 1rpx solid rgba(165, 180, 252, 0.35);
  border-radius: 16rpx;
  padding: 16rpx;
}

.days-value {
  font-size: 48rpx;
  font-weight: 700;
  color: #a5b4fc;
  margin-right: 8rpx;
}

.days-unit {
  font-size: 26rpx;
  color: rgba(226, 232, 240, 0.8);
}

/* 偏好标签 */
.pref-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 16rpx;
}

.pref-tag {
  padding: 12rpx 24rpx;
  border-radius: 32rpx;
  font-size: 26rpx;
  background: rgba(15, 23, 42, 0.6);
  color: #cbd5e1;
  border: 2rpx solid rgba(255, 255, 255, 0.15);
}

.pref-tag.active {
  background: linear-gradient(135deg, #667eea, #764ba2);
  color: #fff;
  border-color: transparent;
  font-weight: 600;
}

/* 提交按钮 */
.submit-btn {
  margin-top: 40rpx;
  height: 96rpx;
  line-height: 96rpx;
}

.footer {
  text-align: center;
  margin-top: 40rpx;
  font-size: 22rpx;
  color: rgba(148, 163, 184, 0.6);
}
</style>
