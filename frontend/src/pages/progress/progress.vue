<template>
  <view class="page">
    <view class="progress-box">
      <!-- 动画图标 -->
      <view class="plane">✈️</view>

      <view class="progress-title">{{ title }}</view>
      <view class="progress-stage">{{ stageText }}</view>

      <!-- 进度条 -->
      <view class="bar-track">
        <view class="bar-fill" :style="{ width: progress + '%' }"></view>
      </view>
      <view class="progress-percent">{{ progress }}%</view>

      <!-- 阶段清单 (已到达的阶段打勾) -->
      <view class="stage-list">
        <view
          v-for="(s, i) in stages"
          :key="s.name"
          class="stage-item"
          :class="{ done: i < currentStageIndex, active: i === currentStageIndex }"
        >
          <text class="stage-dot">{{ i < currentStageIndex ? '✅' : '⏳' }}</text>
          <text class="stage-name">{{ s.name }}</text>
        </view>
      </view>

      <view class="tips">完整规划通常需要 30~90 秒，请耐心等待</view>

      <!-- 失败态 -->
      <view v-if="failed" class="fail-box">
        <view class="fail-title">😥 生成失败</view>
        <view class="fail-msg">{{ errorMsg }}</view>
        <button class="btn-primary retry-btn" @tap="goBack">返回重新规划</button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
/**
 * 规划进度页: 轮询后端异步任务 (每 2 秒一次)
 *
 * 生命周期:
 * - onLoad 拿 task_id → 开始轮询 GET /api/trip/tasks/{id}
 * - completed → 行程写入全局 store, redirectTo 结果页
 * - failed / 404(任务过期) / 超时5分钟 → 展示错误 + 返回按钮
 * - onUnload → 清理定时器 (用户中途返回时防止泄漏)
 */
import { ref, computed, onUnmounted } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { getTripTask } from '@/services/api'
import { setPlannedTrip } from '@/store/trip'

// 阶段清单 (与后端 task_service 的 _STAGE_PLAN 对应, 按 progress 阈值判断到达)
const stages = [
  { name: '搜索景点', threshold: 5 },
  { name: '查询天气', threshold: 30 },
  { name: '搜索酒店', threshold: 45 },
  { name: '搜索美食', threshold: 60 },
  { name: 'AI 生成行程', threshold: 70 },
]

const POLL_INTERVAL = 2000
// 前端兜底超时: 5 分钟 (后端 LLM 含重试最坏约 560s, 但通常远快于此)
const MAX_WAIT_MS = 5 * 60 * 1000

const taskId = ref('')
const progress = ref(0)
const stageText = ref('正在初始化...')
const failed = ref(false)
const errorMsg = ref('')
const finished = ref(false)

let timer: ReturnType<typeof setInterval> | null = null
let startTs = 0

const title = computed(() => (failed.value ? '任务失败' : finished.value ? '规划完成' : 'AI 正在规划你的旅行'))

// 当前进行到第几个阶段 (用于阶段清单打勾)
const currentStageIndex = computed(() => {
  let idx = 0
  for (let i = 0; i < stages.length; i++) {
    if (progress.value >= stages[i].threshold) idx = i + 1
  }
  return Math.min(idx, stages.length - 1)
})

function clearTimer() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

async function poll() {
  // 前端超时兜底
  if (Date.now() - startTs > MAX_WAIT_MS) {
    clearTimer()
    failed.value = true
    errorMsg.value = '生成超时，请稍后在「历史行程」中查看，或返回重新规划'
    return
  }

  try {
    const res = await getTripTask(taskId.value)
    progress.value = res.progress
    stageText.value = res.stage || '规划中...'

    if (res.status === 'completed' && res.data) {
      clearTimer()
      finished.value = true
      progress.value = 100
      // 降级模式提示 (LLM 失败用高德数据兜底, 不伪装成功)
      if (res.data.is_fallback) {
        uni.showToast({ title: '已生成(降级模式)', icon: 'none', duration: 2500 })
      }
      setPlannedTrip(res.data)
      // 稍作停留让用户看到 100%, 再跳结果页 (redirect: 返回时不回到进度页)
      setTimeout(() => {
        uni.redirectTo({ url: '/pages/result/result' })
      }, 600)
    } else if (res.status === 'failed') {
      clearTimer()
      failed.value = true
      errorMsg.value = res.error || '未知错误，请重试'
    }
  } catch (e: any) {
    // 404 = 任务过期/不存在 (后端保留 30 分钟); 网络抖动则继续重试
    const msg = e?.message || ''
    if (msg.includes('404') || msg.includes('不存在') || msg.includes('过期')) {
      clearTimer()
      failed.value = true
      errorMsg.value = '任务已过期，请返回重新规划'
    }
    // 其他错误 (网络抖动等) 不中断轮询, 下个周期重试
  }
}

onLoad((options) => {
  taskId.value = options?.task_id || ''
  if (!taskId.value) {
    failed.value = true
    errorMsg.value = '缺少任务 ID，请返回重新规划'
    return
  }
  startTs = Date.now()
  poll() // 立即查一次
  timer = setInterval(poll, POLL_INTERVAL)
})

onUnmounted(clearTimer)

function goBack() {
  // 表单页是 tabBar 页, 用 switchTab 返回
  uni.switchTab({ url: '/pages/index/index' })
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  background: linear-gradient(180deg, #1e1b4b 0%, #0f172a 40%);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40rpx;
}

.progress-box {
  width: 100%;
  text-align: center;
  padding: 60rpx 40rpx;
  background: rgba(255, 255, 255, 0.06);
  border: 1rpx solid rgba(255, 255, 255, 0.12);
  border-radius: 32rpx;
}

.plane {
  font-size: 100rpx;
  animation: float 2s ease-in-out infinite;
}

@keyframes float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-20rpx); }
}

.progress-title {
  font-size: 40rpx;
  font-weight: 700;
  color: #e0e7ff;
  margin: 24rpx 0 12rpx;
}

.progress-stage {
  font-size: 28rpx;
  color: #a5b4fc;
  margin-bottom: 40rpx;
}

/* 进度条 */
.bar-track {
  height: 20rpx;
  border-radius: 10rpx;
  background: rgba(255, 255, 255, 0.1);
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  border-radius: 10rpx;
  background: linear-gradient(90deg, #667eea, #764ba2, #99f6e4);
  transition: width 0.6s ease;
}

.progress-percent {
  margin-top: 16rpx;
  font-size: 32rpx;
  font-weight: 700;
  color: #99f6e4;
}

/* 阶段清单 */
.stage-list {
  margin-top: 48rpx;
  text-align: left;
}

.stage-item {
  display: flex;
  align-items: center;
  padding: 14rpx 20rpx;
  border-radius: 12rpx;
  opacity: 0.4;
}

.stage-item.done {
  opacity: 0.85;
}

.stage-item.active {
  opacity: 1;
  background: rgba(102, 126, 234, 0.15);
}

.stage-dot {
  margin-right: 16rpx;
  font-size: 26rpx;
}

.stage-name {
  font-size: 28rpx;
  color: #e2e8f0;
}

.tips {
  margin-top: 32rpx;
  font-size: 22rpx;
  color: rgba(148, 163, 184, 0.7);
}

/* 失败态 */
.fail-box {
  margin-top: 40rpx;
  padding-top: 32rpx;
  border-top: 1rpx solid rgba(255, 255, 255, 0.1);
}

.fail-title {
  font-size: 34rpx;
  font-weight: 600;
  color: #fca5a5;
  margin-bottom: 12rpx;
}

.fail-msg {
  font-size: 26rpx;
  color: rgba(226, 232, 240, 0.8);
  margin-bottom: 32rpx;
}

.retry-btn {
  height: 88rpx;
  line-height: 88rpx;
}
</style>
