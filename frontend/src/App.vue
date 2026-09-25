<script setup lang="ts">
import { onLaunch, onShow } from "@dcloudio/uni-app";

onLaunch(() => {
  console.log("App Launch");
});
onShow(() => {
  console.log("App Show");
});
</script>

<style>
/* 全局样式: 深空霓虹主题 (与 Web 版视觉风格一致) */
page {
  background: #0f172a;
  color: #e2e8f0;
  font-size: 28rpx;
  line-height: 1.6;
}

/* 玻璃拟态卡片 */
.glass-card {
  background: rgba(255, 255, 255, 0.06);
  border: 1rpx solid rgba(255, 255, 255, 0.12);
  border-radius: 24rpx;
  padding: 32rpx;
  margin-bottom: 24rpx;
}

/* 主渐变按钮 */
.btn-primary {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #fff;
  border-radius: 48rpx;
  font-size: 32rpx;
  font-weight: 600;
  border: none;
  box-shadow: 0 8rpx 24rpx rgba(102, 126, 234, 0.4);
}

.btn-primary[disabled] {
  opacity: 0.5;
  box-shadow: none;
}

/* 区块标题 */
.section-title {
  display: flex;
  align-items: center;
  font-size: 30rpx;
  font-weight: 600;
  color: #e2e8f0;
  margin-bottom: 24rpx;
}

.section-title .icon {
  margin-right: 12rpx;
}

/* 信息来源标签 (与 Web 版配色一致: 高德蓝/知识库绿/AI橙) */
.tag {
  display: inline-block;
  padding: 4rpx 16rpx;
  border-radius: 20rpx;
  font-size: 22rpx;
  margin-right: 8rpx;
}

.tag-amap {
  background: rgba(59, 130, 246, 0.2);
  color: #93c5fd;
  border: 1rpx solid rgba(59, 130, 246, 0.4);
}

.tag-kb {
  background: rgba(16, 185, 129, 0.2);
  color: #6ee7b7;
  border: 1rpx solid rgba(16, 185, 129, 0.4);
}

.tag-ai {
  background: rgba(245, 158, 11, 0.2);
  color: #fcd34d;
  border: 1rpx solid rgba(245, 158, 11, 0.4);
}
</style>
