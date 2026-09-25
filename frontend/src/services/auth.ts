/**
 * 微信静默登录 (无感, 不需要用户点授权按钮)
 *
 * 流程: uni.login 拿临时 code → POST /api/auth/login → 后端 code2session + 签发 JWT
 *      → token 存本地 storage, api.ts 自动附带 Authorization 头
 *
 * 平台差异:
 * - 微信小程序: uni.login 返回真实 wx code, 后端调微信接口换 openid
 * - H5 开发预览: 没有 uni.login 能力, 用本地持久化的设备码代替 code;
 *   后端未配置 WX_APPID 时走 mock 登录, 同一设备码始终映射同一用户, 开发体验一致
 */

import { login as apiLogin } from '@/services/api'

const TOKEN_KEY = 'auth_token'
const EXPIRES_KEY = 'auth_token_expires_at' // 毫秒时间戳
const DEVICE_CODE_KEY = 'auth_device_code'

// 提前 5 分钟视为过期, 避免边界时刻请求失败
const EXPIRE_BUFFER_MS = 5 * 60 * 1000

/** 读取本地 token (未过期才返回) */
export function getToken(): string | null {
  const token = uni.getStorageSync(TOKEN_KEY)
  const expiresAt = Number(uni.getStorageSync(EXPIRES_KEY) || 0)
  if (token && expiresAt > Date.now() + EXPIRE_BUFFER_MS) {
    return token
  }
  return null
}

/** 保存 token 与过期时间 */
function saveToken(token: string, expiresInSeconds: number) {
  uni.setStorageSync(TOKEN_KEY, token)
  uni.setStorageSync(EXPIRES_KEY, Date.now() + expiresInSeconds * 1000)
}

/** 清除登录态 (401 时调用) */
export function clearToken() {
  uni.removeStorageSync(TOKEN_KEY)
  uni.removeStorageSync(EXPIRES_KEY)
}

/** H5 设备码: 首次生成后持久化, 保证同一浏览器始终是同一用户 */
function getDeviceCode(): string {
  let code = uni.getStorageSync(DEVICE_CODE_KEY)
  if (!code) {
    code = 'h5_device_' + Math.random().toString(36).slice(2) + Date.now().toString(36)
    uni.setStorageSync(DEVICE_CODE_KEY, code)
  }
  return code
}

/** 获取登录 code: 小程序走 uni.login, H5 走设备码 */
function fetchLoginCode(): Promise<string> {
  return new Promise((resolve, reject) => {
    // #ifdef MP-WEIXIN
    uni.login({
      provider: 'weixin',
      success: (res) => {
        if (res.code) resolve(res.code)
        else reject(new Error('uni.login 未返回 code'))
      },
      fail: (err) => reject(new Error(err.errMsg || '微信登录失败')),
    })
    // #endif
    // #ifndef MP-WEIXIN
    resolve(getDeviceCode())
    // #endif
  })
}

// 并发登录去重: 多个请求同时 401 时只发一次登录
let loginPromise: Promise<string | null> | null = null

/**
 * 确保已登录, 返回可用 token
 * - 本地 token 未过期 → 直接返回
 * - 否则静默登录 (并发安全, 同时调用共享同一个登录请求)
 * - 登录失败返回 null (调用方降级为匿名访问)
 */
export function ensureLogin(): Promise<string | null> {
  const cached = getToken()
  if (cached) return Promise.resolve(cached)

  if (!loginPromise) {
    loginPromise = (async () => {
      try {
        const code = await fetchLoginCode()
        const res = await apiLogin(code)
        saveToken(res.token, res.expires_in)
        console.log(
          `🔐 静默登录成功: user_id=${res.user_id}, 新用户=${res.is_new_user}` +
            (res.mock_mode ? ' (mock模式)' : ''),
        )
        return res.token
      } catch (e) {
        console.warn('静默登录失败, 将以匿名模式访问:', (e as Error).message)
        return null
      } finally {
        loginPromise = null
      }
    })()
  }
  return loginPromise
}
