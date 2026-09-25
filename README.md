# 智能旅行助手 · 小程序版 🌍✈️

基于 **LangChain + LangGraph + FastAPI** 的智能旅行规划助手**小程序版本**（uniapp），后端复用自 [langchain-travel-agent](https://github.com/lwyKunKun/travel-agent)，并针对微信小程序的请求超时限制做了**异步任务化改造**。

## ✨ 项目定位

- 🎯 **前端**：uniapp（Vue3 + TypeScript），一套代码编译到微信小程序 / H5
- 🔌 **后端**：FastAPI + LangGraph 智能规划流水线 + RAG 知识库 + 高德地图直调（与 Web 版同源）
- ⚡ **小程序适配核心改造**：长耗时规划（30~90 秒）由同步等待改为「**创建任务 → 轮询进度 → 取结果**」异步模式

## 🏗️ 后端能力（继承自主项目）

- 🤖 **LangGraph 工作流编排**：搜景点 → 查天气 → 搜酒店 → 搜美食 → LLM 生成行程 →（失败）兜底计划
- 🧠 **RAG 知识库检索增强**：4 城市旅游知识库（深圳/北京/上海/广州），千问 `text-embedding-v4` + ChromaDB
- 🌤️ **双源天气合并**：高德 4 天官方预报 + Open-Meteo 免费补齐 16 天窗口
- 📜 **行程历史持久化**：SQLAlchemy + SQLite，支持分页/筛选/编辑/删除
- 🛡️ **优雅降级**：数据节点失败返回空列表、LLM 失败走兜底、RAG 未配置自动禁用
- 🔌 **兼容任意模型**：换 LLM 只需改 `.env` 三个参数

## ⚡ 小程序端新增：异步任务接口

微信小程序 `wx.request` 不适合长时间同步等待，因此新增两个接口（原同步接口 `POST /api/trip/plan` 保留，Web 端不受影响）：

### 1. 创建任务

```
POST /api/trip/tasks
```

请求体与 `/api/trip/plan` 完全一致，**立即返回**：

```json
{ "success": true, "task_id": "ff776517...", "status": "pending" }
```

### 2. 轮询任务状态/结果

```
GET /api/trip/tasks/{task_id}
```

```json
{
  "success": true,
  "task_id": "ff776517...",
  "status": "running", // pending / running / completed / failed
  "stage": "正在搜索景点…", // 当前阶段描述, 可直接展示给用户
  "progress": 25, // 进度百分比 0~100
  "created_at": "2026-09-25T04:30:00+00:00",
  "finished_at": null,
  "error": null, // failed 时返回失败原因
  "data": null // completed 时返回完整行程 (TripPlan)
}
```

- 建议前端**每 2 秒轮询一次**，用 `stage` + `progress` 渲染进度条
- 任务结果保留 **30 分钟**，过期后返回 404，前端提示用户重新生成即可
- 任务状态存内存（线程安全 dict + 线程池，默认 4 并发），无 Redis/Celery 外部依赖，保持单机可跑

### 实现说明

| 文件                                   | 说明                                                       |
| -------------------------------------- | ---------------------------------------------------------- |
| `backend/app/services/task_service.py` | 任务管理器：内存任务表、线程池执行、阶段进度插值、TTL 清理 |
| `backend/app/api/routes/trip.py`       | 新增 `POST /tasks`、`GET /tasks/{task_id}` 两个路由        |
| `backend/app/models/schemas.py`        | 新增 `TaskCreatedResponse`、`TaskStatusResponse` 模型      |
| `backend/tests/test_trip_tasks.py`     | 异步任务全生命周期测试（mock LLM，不发真实请求）           |

> 进度按「阶段计划 + 时间插值」估算：LangGraph 节点内部无回调可挂，按各节点经验耗时推进 progress，真实完成前置 95%，完成时置 100。

## 📁 项目结构

```
travel-agent-miniapp/
├── backend/                    # FastAPI 后端 (复用主项目 + 异步任务改造)
│   ├── app/
│   │   ├── agents/             # LangGraph 智能体编排
│   │   ├── api/routes/         # trip(含异步任务)/map/poi/history/rag
│   │   ├── services/           # amap/open_meteo/llm/rag/history/task(新增)
│   │   ├── db/                 # SQLAlchemy + SQLite
│   │   ├── models/schemas.py   # Pydantic 模型
│   │   └── core/               # 日志/异常处理
│   ├── data/knowledge/         # RAG 知识库文档 (4 城市)
│   ├── tests/                  # pytest (23 个测试, 隔离真实网络)
│   ├── Dockerfile / docker-compose.yml
│   └── requirements.txt
└── frontend/                   # uniapp 小程序前端 (Vue3 + TS + Vite)
    ├── src/
    │   ├── pages/
    │   │   ├── index/          # 需求表单页 (目的地/日期/偏好)
    │   │   ├── progress/       # 规划进度页 (轮询异步任务, 2秒/次)
    │   │   ├── result/         # 行程结果页 (原生map组件+每日卡片+预算+天气)
    │   │   └── history/        # 历史行程页 (分页/筛选/删除)
    │   ├── services/api.ts     # uni.request 封装 + 异步任务/历史 API
    │   ├── store/trip.ts       # 全局行程状态 (页面间中转)
    │   └── types/index.ts      # TS 类型 (与后端 Pydantic 模型对齐)
    └── .env.development        # 开发环境 API 地址
```

## 🚀 快速开始（后端）

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # 填入高德 Key / LLM Key / (可选)DashScope Key
python run.py                   # 启动后访问 http://localhost:8000/docs
```

运行测试：

```bash
cd backend && pytest tests -q
```

## 🚀 快速开始（前端 · 小程序）

```bash
cd frontend
npm install
npm run dev:mp-weixin     # 产物在 dist/dev/mp-weixin, 用微信开发者工具导入该目录
```

- 微信开发者工具需勾选「**不校验合法域名**」才能请求本地 `http://localhost:8000`（见 `.env.development`）
- H5 预览: `npm run dev:h5`
- 生产构建: `npm run build:mp-weixin`
- `manifest.json` 的 `mp-weixin.appid` 需填入你自己的小程序 AppID

## 🗺️ 前端已实现

- ✅ **需求表单页**：热门城市快选、日期选择（自动算天数、30天上限校验）、交通/住宿/偏好选择
- ✅ **规划进度页**：每 2 秒轮询异步任务，真实进度条 + 阶段清单（搜景点→查天气→搜酒店→搜美食→AI生成），5 分钟超时兜底
- ✅ **行程结果页**：原生 `<map>` 组件全览打点（景点+酒店 callout）、每日卡片（景点图/来源三色标签/门票/餐饮/酒店）、预算明细、天气预报表、降级警告横幅
- ✅ **历史行程页**：分页加载 + 触底加载更多 + 下拉刷新 + 城市筛选 + 删除二次确认

## 🗺️ 后续规划（待开发）

- **登录**：微信登录（`wx.login` → 后端 code2session → JWT），历史记录按用户隔离
- **分享**：canvas 绘制行程卡片 → 保存相册/转发好友

## ⚠️ 小程序上线注意事项

1. 正式版只能请求**已备案的 HTTPS 域名**，需在小程序后台配置 request 合法域名
2. 景点图片走高德 POI 国内 CDN，需将图片域名加入 **downloadFile 合法域名**
3. 类目建议选择「工具 > 信息查询」，纯规划工具定位可规避旅行社资质要求
