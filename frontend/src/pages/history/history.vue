<template>
  <view class="page">
    <!-- 城市筛选 -->
    <view class="filter-bar">
      <input
        v-model="cityFilter"
        class="filter-input"
        placeholder="按城市筛选，如: 北京"
        placeholder-class="filter-placeholder"
        confirm-type="search"
        @confirm="reload"
      />
      <button class="filter-btn" @tap="reload">搜索</button>
      <button v-if="cityFilter" class="filter-clear" @tap="clearFilter">清空</button>
    </view>

    <!-- 列表 -->
    <view v-if="records.length">
      <view
        v-for="r in records"
        :key="r.id"
        class="record-card glass-card"
        @tap="openDetail(r.id)"
      >
        <view class="record-main">
          <view class="record-city">📍 {{ r.city }}</view>
          <view class="record-dates">{{ r.start_date }} ~ {{ r.end_date }} · {{ r.travel_days }} 天</view>
          <view class="record-meta">
            <text class="tag tag-amap" v-if="r.attraction_count">{{ r.attraction_count }} 个景点</text>
            <text class="tag tag-kb" v-if="r.budget_total">预算 ¥{{ r.budget_total }}</text>
          </view>
          <view class="record-time">创建于 {{ r.created_at }}</view>
        </view>
        <view class="record-actions">
          <text class="action-view">查看 ›</text>
          <text class="action-delete" @tap.stop="confirmDelete(r)">🗑️</text>
        </view>
      </view>

      <!-- 加载更多 -->
      <view class="load-more" v-if="hasMore">
        <button class="load-btn" :loading="loading" @tap="loadMore">加载更多</button>
      </view>
      <view class="load-end" v-else>— 共 {{ total }} 条，已全部加载 —</view>
    </view>

    <!-- 空态 -->
    <view v-else-if="!loading" class="empty">
      <view class="empty-icon">📜</view>
      <view class="empty-text">暂无历史行程</view>
      <button class="btn-primary empty-btn" @tap="goHome">去规划一趟旅行</button>
    </view>
  </view>
</template>

<script setup lang="ts">
/**
 * 历史行程页 (迁移自 Web 版 History.vue)
 * - 分页加载 + 下拉刷新 + 触底加载更多
 * - 城市筛选
 * - 点击查看 → 拉取详情 → 写入 store → 跳结果页
 * - 删除 (二次确认)
 */
import { ref } from 'vue'
import { onShow, onPullDownRefresh, onReachBottom } from '@dcloudio/uni-app'
import { fetchHistory, fetchHistoryDetail, deleteHistory } from '@/services/api'
import { setHistoryTrip } from '@/store/trip'
import type { HistorySummary } from '@/types'

const PAGE_SIZE = 10

const records = ref<HistorySummary[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const cityFilter = ref('')

const hasMore = ref(false)

async function load(pageNum: number, append = false) {
  loading.value = true
  try {
    const res = await fetchHistory(pageNum, PAGE_SIZE, cityFilter.value || undefined)
    total.value = res.total
    page.value = res.page
    records.value = append ? [...records.value, ...res.data] : res.data
    hasMore.value = records.value.length < res.total
  } catch (e: any) {
    uni.showToast({ title: e.message || '加载失败', icon: 'none' })
  } finally {
    loading.value = false
  }
}

function reload() {
  load(1)
}

function clearFilter() {
  cityFilter.value = ''
  reload()
}

function loadMore() {
  if (!loading.value && hasMore.value) {
    load(page.value + 1, true)
  }
}

/** 查看详情: 拉完整行程 → store → 结果页 */
async function openDetail(id: number) {
  uni.showLoading({ title: '加载中...' })
  try {
    const res = await fetchHistoryDetail(id)
    setHistoryTrip(res.data.plan, res.data.id)
    uni.navigateTo({ url: '/pages/result/result' })
  } catch (e: any) {
    uni.showToast({ title: e.message || '加载详情失败', icon: 'none' })
  } finally {
    uni.hideLoading()
  }
}

/** 删除 (二次确认, 与 Web 版一致) */
function confirmDelete(r: HistorySummary) {
  uni.showModal({
    title: '删除确认',
    content: `确定删除「${r.city} ${r.start_date}」的行程吗？删除后不可恢复`,
    confirmColor: '#ef4444',
    success: async (res) => {
      if (!res.confirm) return
      try {
        await deleteHistory(r.id)
        uni.showToast({ title: '已删除', icon: 'success' })
        reload()
      } catch (e: any) {
        uni.showToast({ title: e.message || '删除失败', icon: 'none' })
      }
    },
  })
}

function goHome() {
  uni.switchTab({ url: '/pages/index/index' })
}

// 每次进入页面刷新 (从结果页返回时保持最新)
onShow(() => {
  load(1)
})

// 下拉刷新 (pages.json 已开启 enablePullDownRefresh)
onPullDownRefresh(async () => {
  await load(1)
  uni.stopPullDownRefresh()
})

// 触底自动加载更多
onReachBottom(() => {
  loadMore()
})
</script>

<style scoped>
.page {
  min-height: 100vh;
  padding: 24rpx 32rpx 60rpx;
  background: linear-gradient(180deg, #1e1b4b 0%, #0f172a 30%);
}

/* 筛选栏 */
.filter-bar {
  display: flex;
  align-items: center;
  gap: 16rpx;
  margin-bottom: 24rpx;
}

.filter-input {
  flex: 1;
  background: rgba(255, 255, 255, 0.06);
  border: 1rpx solid rgba(255, 255, 255, 0.15);
  border-radius: 40rpx;
  padding: 16rpx 28rpx;
  font-size: 26rpx;
  color: #e2e8f0;
}

.filter-placeholder {
  color: rgba(148, 163, 184, 0.6);
}

.filter-btn {
  background: linear-gradient(135deg, #667eea, #764ba2);
  color: #fff;
  font-size: 26rpx;
  border-radius: 40rpx;
  padding: 0 32rpx;
  height: 68rpx;
  line-height: 68rpx;
  margin: 0;
}

.filter-clear {
  background: rgba(255, 255, 255, 0.08);
  color: #cbd5e1;
  font-size: 26rpx;
  border-radius: 40rpx;
  padding: 0 24rpx;
  height: 68rpx;
  line-height: 68rpx;
  margin: 0;
}

/* 记录卡片 */
.record-card {
  display: flex;
  align-items: center;
}

.record-main {
  flex: 1;
  min-width: 0;
}

.record-city {
  font-size: 32rpx;
  font-weight: 700;
  color: #e0e7ff;
}

.record-dates {
  font-size: 24rpx;
  color: rgba(226, 232, 240, 0.75);
  margin: 6rpx 0;
}

.record-meta {
  display: flex;
  margin-bottom: 6rpx;
}

.record-time {
  font-size: 22rpx;
  color: rgba(148, 163, 184, 0.7);
}

.record-actions {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 20rpx;
  flex-shrink: 0;
  margin-left: 16rpx;
}

.action-view {
  font-size: 26rpx;
  color: #a5b4fc;
}

.action-delete {
  font-size: 32rpx;
  padding: 8rpx;
}

/* 加载更多 */
.load-more {
  margin-top: 16rpx;
}

.load-btn {
  background: rgba(255, 255, 255, 0.06);
  color: #a5b4fc;
  font-size: 26rpx;
  border-radius: 40rpx;
  height: 76rpx;
  line-height: 76rpx;
  border: 1rpx solid rgba(255, 255, 255, 0.12);
}

.load-end {
  text-align: center;
  margin-top: 24rpx;
  font-size: 22rpx;
  color: rgba(148, 163, 184, 0.6);
}

/* 空态 */
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 200rpx;
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
