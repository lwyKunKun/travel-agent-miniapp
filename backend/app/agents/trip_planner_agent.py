"""基于 LangGraph 的多智能体旅行规划系统"""

import json
import logging
import re
from datetime import datetime, timedelta
from typing import TypedDict, List
from langgraph.graph import StateGraph, START, END
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from ..services.llm_service import get_llm
from ..services.amap_service import get_amap_service
from ..models.schemas import (
    TripRequest,
    TripPlan,
    DayPlan,
    Attraction,
    Meal,
    Location,
    Hotel,
    Budget,
    WeatherInfo,
    POIInfo,
)

logger = logging.getLogger(__name__)

# ============ 行程规划提示词 ============

PLANNER_SYSTEM_PROMPT = """你是专业的行程规划专家。根据用户提供的景点、天气和酒店信息, 生成详细的旅行计划。

**输出要求:**
必须只输出一个 JSON 对象, 不要输出任何其他文字, JSON 结构严格如下:
{{
  "city": "城市名称",
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "days": [
    {{
      "date": "YYYY-MM-DD",
      "day_index": 0,
      "description": "第1天行程概述",
      "transportation": "交通方式",
      "accommodation": "住宿类型",
      "hotel": {{
        "name": "酒店名称",
        "address": "酒店地址",
        "location": {{"longitude": 116.397128, "latitude": 39.916527}},
        "price_range": "300-500元",
        "rating": "4.5",
        "distance": "距离景点2公里",
        "type": "经济型酒店",
        "estimated_cost": 400
      }},
      "attractions": [
        {{
          "name": "景点名称",
          "address": "详细地址",
          "location": {{"longitude": 116.397128, "latitude": 39.916527}},
          "visit_duration": 120,
          "description": "景点详细描述",
          "category": "景点类别",
          "ticket_price": 60
        }}
      ],
      "meals": [
        {{"type": "breakfast", "name": "早餐推荐", "description": "早餐描述", "estimated_cost": 30}},
        {{"type": "lunch", "name": "午餐推荐", "description": "午餐描述", "estimated_cost": 50}},
        {{"type": "dinner", "name": "晚餐推荐", "description": "晚餐描述", "estimated_cost": 80}}
      ]
    }}
  ],
  "weather_info": [
    {{
      "date": "YYYY-MM-DD",
      "day_weather": "晴",
      "night_weather": "多云",
      "day_temp": 25,
      "night_temp": 15,
      "wind_direction": "南风",
      "wind_power": "1-3级"
    }}
  ],
  "overall_suggestions": "总体建议",
  "budget": {{
    "total_attractions": 180,
    "total_hotels": 1200,
    "total_meals": 480,
    "total_transportation": 200,
    "total": 2060
  }}
}}

**规则:**
1. 每天安排2-3个景点, 考虑景点之间的距离和游览时间
2. 每天必须包含早中晚三餐(breakfast/lunch/dinner); 提供了"可选美食店铺"时, name 必须从中选择真实店铺名并填写 address, 禁止编造"第N天早餐"之类的占位名称
3. 每天推荐一个具体的酒店(从提供的酒店信息中选择)
4. weather_info 中按日期填入对应天气; 某天没有天气数据时, 字段留空
5. 景点/酒店的经纬度坐标必须使用提供的真实坐标; 本提示词示例中的北京坐标(116.397128, 39.916527)仅为格式演示, 严禁照抄到输出中
6. 所有费用字段填写合理估算值, budget 为各项费用汇总
7. overall_suggestions 必须具体详细(150字以上): 结合当地气候、交通、最佳游览时段、避坑提示等给出可执行建议, 禁止只写一句套话
"""


class GraphState(TypedDict, total=False):
    """LangGraph 工作流状态"""
    request: TripRequest               # 用户旅行请求
    attraction_pois: List[POIInfo]     # 景点搜索结果
    weather_info: List[WeatherInfo]    # 天气信息
    hotel_pois: List[POIInfo]          # 酒店搜索结果
    meal_pois: List[POIInfo]           # 美食搜索结果 (供兜底计划给真实店铺推荐)
    trip_plan: TripPlan                # 最终行程计划
    error: bool                        # 是否出错(用于条件路由)
    error_reason: str                  # 出错原因(用于兜底计划标记降级原因)


class MultiAgentTripPlanner:
    """基于 LangGraph 的多智能体旅行规划系统

    工作流: 搜索景点 → 查询天气 → 搜索酒店 → LLM生成行程 → (LLM失败)备用计划
    数据获取节点直接调用高德服务(不走LLM), 仅行程规划调用LLM, 高效且省成本。
    """

    def __init__(self):
        """初始化多智能体系统"""
        logger.info("🔄 开始初始化多智能体旅行规划系统...")
        self.llm = get_llm()
        self.amap_service = get_amap_service()
        self.graph = self._build_graph()
        logger.info("✅ 多智能体系统初始化成功")

    # ============ LangGraph 节点 ============

    def _search_attractions(self, state: GraphState) -> dict:
        """节点1: 搜索景点 (服务直调, 不走LLM)

        1. 按用户首个偏好用高德搜索景点
        2. 用 RAG 知识库补充当地必打卡景点 (按名搜索拿真实坐标),
           让 LLM 能真正采用知识库推荐的景点, 而不只是"参考"
        """
        request = state["request"]
        logger.info("📍 步骤1: 搜索景点...")
        try:
            keywords = request.preferences[0] if request.preferences else "景点"
            pois = self.amap_service.search_poi(keywords, request.city)
            logger.info(f"   找到 {len(pois)} 个景点")

            # RAG 知识库景点补充 (失败/未启用时静默跳过, 不影响主流程)
            try:
                from ..services.rag_service import get_rag_service

                known_names = {p.name for p in pois if p.name}
                for name in get_rag_service().get_knowledge_attractions(request.city):
                    if any(name in n for n in known_names):
                        continue
                    kb_pois = self.amap_service.search_poi(name, request.city)
                    if kb_pois:
                        pois.append(kb_pois[0])
                        known_names.add(kb_pois[0].name or "")
                        logger.info(f"   + 知识库补充景点: {name}")
            except Exception as e:
                logger.warning(f"   ⚠️ 知识库景点补充失败(不影响主流程): {e}")

            return {"attraction_pois": pois}
        except Exception as e:
            logger.warning(f"   ⚠️ 景点搜索失败: {e}")
            return {"attraction_pois": []}

    def _get_weather(self, state: GraphState) -> dict:
        """节点2: 查询天气 (服务直调, 不走LLM)

        双数据源合并: 高德提供今起4天预报(国内官方源, 优先),
        行程日期超出部分用 Open-Meteo(免费, 16天预报窗口)补齐。
        """
        request = state["request"]
        logger.info("🌤️  步骤2: 查询天气...")
        weather = []
        try:
            weather = self.amap_service.get_weather(request.city)
            logger.info(f"   获取 {len(weather)} 天高德天气数据")
        except Exception as e:
            logger.warning(f"   ⚠️ 高德天气查询失败: {e}")

        # Open-Meteo 补齐行程日期中高德未覆盖的部分 (失败静默跳过)
        try:
            from ..services.open_meteo_service import get_open_meteo_service

            city_center = self._get_city_center(request.city)
            weather = get_open_meteo_service().supplement_weather(
                city_center, request.start_date, request.end_date, weather
            )
            logger.info(f"   合并后共 {len(weather)} 天天气数据")
        except Exception as e:
            logger.warning(f"   ⚠️ Open-Meteo 天气补充失败(不影响主流程): {e}")

        return {"weather_info": weather}

    def _search_hotels(self, state: GraphState) -> dict:
        """节点3: 搜索酒店 (服务直调, 不走LLM)"""
        request = state["request"]
        logger.info("🏨 步骤3: 搜索酒店...")
        try:
            hotels = self.amap_service.search_poi(request.accommodation, request.city)
            logger.info(f"   找到 {len(hotels)} 个酒店")
            return {"hotel_pois": hotels}
        except Exception as e:
            logger.warning(f"   ⚠️ 酒店搜索失败: {e}")
            return {"hotel_pois": []}

    def _search_meals(self, state: GraphState) -> dict:
        """节点3.5: 搜索美食店铺 (服务直调, 不走LLM)

        给 LLM 提供真实餐厅候选, 让早中晚三餐能落到具体店铺;
        同时也是兜底计划的餐饮数据来源。失败不影响主流程。
        """
        request = state["request"]
        logger.info("🍜 步骤3.5: 搜索美食店铺...")
        try:
            meals = self.amap_service.search_poi("特色美食餐厅", request.city)
            logger.info(f"   找到 {len(meals)} 个美食店铺")
            return {"meal_pois": meals}
        except Exception as e:
            logger.warning(f"   ⚠️ 美食搜索失败: {e}")
            return {"meal_pois": []}

    def _generate_trip_plan(self, state: GraphState) -> dict:
        """节点4: LLM 生成行程计划

        采用「文本生成 + JSON提取 + Pydantic校验」的通用方案, 兼容任何模型
        (包括不支持 function calling / json_schema 的 thinking 模型)。
        解析失败时携带错误信息自纠错重试一次, 仍失败则走备用计划。
        """
        request = state["request"]
        logger.info("📋 步骤4: LLM 生成行程计划...")
        try:
            planner_query = self._build_planner_query(request, state)
            prompt_template = ChatPromptTemplate.from_messages([
                ("system", PLANNER_SYSTEM_PROMPT),
                ("human", "{query}"),
            ])
            chain = prompt_template | self.llm 

            for attempt in range(2):
                response = chain.invoke({"query": planner_query})
                content = response.content if hasattr(response, "content") else str(response)
                try:
                    trip_plan = self._parse_json_response(content)
                    logger.info("   ✅ 行程计划生成成功")
                    return {"trip_plan": trip_plan, "error": False}
                except Exception as e:
                    logger.warning(f"   ⚠️ 第{attempt + 1}次解析失败: {str(e)[:100]}")
                    # 自纠错: 把校验错误反馈给LLM, 要求重新生成
                    planner_query = (
                        f"你上一次输出的 JSON 不符合结构要求, 错误信息: {e}\n"
                        f"你上一次的输出是: {content[:2000]}\n"
                        f"请严格按照 system 中定义的 JSON 结构重新输出完整 JSON。\n\n"
                        f"原始需求:\n{planner_query}"
                    )

            raise ValueError("两次尝试均未能生成合法行程计划")
        except Exception as e:
            logger.error(f"   ❌ LLM 生成行程失败(将走兜底计划): {e}")
            return {"error": True, "error_reason": str(e)[:200]}

    def _fallback_plan(self, state: GraphState) -> dict:
        """节点5: 备用计划 (LLM失败时兜底)

        不再返回占位符假数据: 优先使用前面节点已从高德拿到的真实
        景点/酒店/美食 POI 编排行程, 并打上 is_fallback 降级标记。
        """
        logger.info("   🛟 使用备用计划 (基于高德真实POI编排)")
        plan = self._create_fallback_plan(
            state["request"],
            attraction_pois=state.get("attraction_pois") or [],
            hotel_pois=state.get("hotel_pois") or [],
            meal_pois=state.get("meal_pois") or [],
            weather_info=state.get("weather_info") or [],
            reason=state.get("error_reason") or "LLM 生成失败",
        )
        return {"trip_plan": plan, "error": False}

    def _should_fallback(self, state: GraphState) -> str:
        """条件路由: LLM生成失败则走备用计划, 否则结束"""
        return "fallback_plan" if state.get("error") else "end"

    # ============ 图构建 ============

    def _build_graph(self):
        """构建 LangGraph 工作流"""
        # 1. 实例化图，指定全局数据结构
        graph = StateGraph(GraphState)
        # 2. 注册所有节点 (把工人拉进厂)
        graph.add_node("search_attractions", self._search_attractions)
        graph.add_node("get_weather", self._get_weather)
        graph.add_node("search_hotels", self._search_hotels)
        graph.add_node("search_meals", self._search_meals)
        graph.add_node("generate_trip_plan", self._generate_trip_plan)
        graph.add_node("fallback_plan", self._fallback_plan)

        # 3. 铺设传送带 (普通边: 顺次执行)
        graph.add_edge(START, "search_attractions")
        graph.add_edge("search_attractions", "get_weather")
        graph.add_edge("get_weather", "search_hotels")
        graph.add_edge("search_hotels", "search_meals")
        graph.add_edge("search_meals", "generate_trip_plan")
        # 4. 铺设智能分拣闸门 (条件边: 失败走兜底，成功则结束)
        graph.add_conditional_edges(
            "generate_trip_plan",
            self._should_fallback,
            {"fallback_plan": "fallback_plan", "end": END},
        )
        graph.add_edge("fallback_plan", END)
        return graph.compile()

    # ============ 对外接口 ============

    def plan_trip(self, request: TripRequest) -> TripPlan:
        """使用 LangGraph 工作流生成旅行计划

        Args:
            request: 旅行请求

        Returns:
            旅行计划
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"🚀 开始 LangGraph 工作流规划旅行...")
        logger.info(f"目的地: {request.city} | 日期: {request.start_date} 至 {request.end_date} | {request.travel_days}天")
        logger.info(f"偏好: {', '.join(request.preferences) if request.preferences else '无'}")
        logger.info(f"{'='*60}\n")

        result = self.graph.invoke({"request": request})
        trip_plan = result["trip_plan"]

        # 天气: 用高德真实天气覆盖LLM生成的天气。
        # LLM 常因日期不足而把天气字段输出 null/0, 导致前端温度全显示0;
        # 数据节点已拿到高德真实天气(含温度), 直接回填即可, 也符合"服务直调"架构。
        # 注意: 高德预报仅覆盖"今天起未来4天", 必须过滤掉不在行程日期范围内的条目,
        # 否则会出现"10月的行程展示9月天气"的日期错位问题(旧版bug)。
        real_weather = result.get("weather_info") or []
        if real_weather:
            in_range = [
                w for w in real_weather
                if request.start_date <= w.date <= request.end_date
            ]
            trip_plan.weather_info = in_range
            if len(in_range) < len(real_weather):
                logger.info(
                    f"   ℹ️ 天气过滤: 高德预报{len(real_weather)}天, "
                    f"其中{len(in_range)}天落在行程日期范围内"
                )

        # 兜底: 若LLM未返回预算, 前端预算页会异常, 这里自动补齐
        trip_plan = self._ensure_budget(trip_plan, request)

        # 来源标注 + 知识库增强:
        # 1. 景点名能在高德候选POI里匹配到 → 标"高德地图"(坐标/地址真实可靠)
        # 2. 知识库精确匹配到详情 → 标"知识库"并追加门票/交通/避坑信息
        # 3. 两者都没有 → 标"AI推荐·需核实"(LLM可能编造, 提醒用户自行确认)
        # 失败/未启用时静默跳过, 不影响主流程。
        try:
            from ..services.rag_service import get_rag_service

            rag = get_rag_service()
            candidate_names = [
                p.name for p in (result.get("attraction_pois") or []) if p.name
            ]
            for day in trip_plan.days:
                for attr in day.attractions:
                    sources: List[str] = []
                    if self._match_candidate(attr.name, candidate_names):
                        sources.append("高德地图")
                    detail = rag.get_attraction_rag_text(attr.name, trip_plan.city)
                    if detail:
                        sources.append("知识库")
                        attr.description = f"{attr.description}\n\n——知识库参考——\n{detail}"
                    if not sources:
                        sources.append("AI推荐·需核实")
                    attr.sources = sources
        except Exception as e:
            logger.warning(f"⚠️  来源标注/知识库增强失败(不影响主流程): {e}")

        logger.info(f"\n{'='*60}")
        logger.info(f"✅ 旅行计划生成完成! 天数: {len(trip_plan.days)}")
        logger.info(f"{'='*60}\n")
        return trip_plan

    def get_agent_info(self) -> dict:
        """Agent 信息 (供健康检查使用)"""
        return {
            "name": "LangGraph 多智能体旅行规划系统",
            "framework": "langgraph",
            "nodes": ["search_attractions", "get_weather", "search_hotels", "search_meals", "generate_trip_plan", "fallback_plan"],
        }

    # ============ 内部工具方法 ============

    @staticmethod
    def _match_candidate(name: str, candidates: List[str]) -> bool:
        """判断景点名能否在高德候选POI列表中匹配到 (双向子串模糊匹配)

        LLM 输出的名称与高德 POI 名常有出入 (如"故宫"vs"故宫博物院"、
        "北京环球影城"vs"环球影城度假区"), 任一方向包含即视为同一景点。
        """
        name = (name or "").strip()
        if len(name) < 2:
            return False
        return any(name in c or c in name for c in candidates if c)

    @staticmethod
    def _parse_json_response(content: str) -> TripPlan:
        """从LLM响应中提取JSON并用Pydantic校验

        Args:
            content: LLM原始输出

        Returns:
            校验通过的 TripPlan

        Raises:
            ValueError: JSON提取失败或结构校验失败
        """
        # 1. 提取代码块中的JSON (支持 ```json 包裹)
        if "```" in content:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
            if match:
                content = match.group(1)

        # 2. 截取首尾花括号之间的内容
        start, end = content.find("{"), content.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("LLM响应中未找到JSON对象")

        # 3. 解析JSON并通过Pydantic校验
        data = json.loads(content[start:end + 1])
        return TripPlan.model_validate(data)

    def _build_planner_query(self, request: TripRequest, state: GraphState) -> str:
        """构建行程规划 prompt (将结构化数据转为文本供LLM参考)"""
        attraction_text = self._pois_to_text(state.get("attraction_pois", []))
        hotel_text = self._pois_to_text(state.get("hotel_pois", []))
        meal_text = self._pois_to_text(state.get("meal_pois", []))
        weather_text = self._weather_to_text(state.get("weather_info", []))

        query = f"""请为以下旅行需求生成{request.city}的{request.travel_days}天行程计划:

**基本信息:**
- 城市: {request.city}
- 日期: {request.start_date} 至 {request.end_date}
- 天数: {request.travel_days}天
- 交通方式: {request.transportation}
- 住宿偏好: {request.accommodation}
- 旅行偏好: {', '.join(request.preferences) if request.preferences else '无'}

**可选景点:**
{attraction_text or '无'}

**天气信息:**
{weather_text or '无'}

**可选酒店:**
{hotel_text or '无'}

**可选美食店铺(早中晚三餐请优先从中选择真实店铺):**
{meal_text or '无'}
"""
        if request.free_text_input:
            query += f"\n**额外要求:** {request.free_text_input}\n"

        # RAG 增强: 检索城市旅游知识 + 相似历史行程, 注入 prompt 作为参考。
        # 知识库让行程更贴合当地实际(门票/交通/避坑), 历史行程让风格更稳定。
        # RAG 未启用或检索失败时跳过, 不影响正常生成。
        try:
            from ..services.rag_service import get_rag_service

            rag_context = get_rag_service().build_rag_context(request)
            if rag_context:
                query += f"\n\n{rag_context}\n"
        except Exception as e:
            logger.warning(f"⚠️ RAG 上下文注入失败(不影响生成): {e}")

        query += "\n请严格按照 system 中定义的 JSON 结构输出完整 JSON。"
        return query

    @staticmethod
    def _pois_to_text(pois: List[POIInfo]) -> str:
        """POI列表转为可读文本"""
        lines = []
        for i, poi in enumerate(pois, 1):
            coord = f"{poi.location.longitude},{poi.location.latitude}" if poi.location else ""
            lines.append(f"{i}. {poi.name} | 地址: {poi.address} | 坐标: {coord}")
        return "\n".join(lines)

    @staticmethod
    def _weather_to_text(weather_list: List[WeatherInfo]) -> str:
        """天气信息列表转为可读文本"""
        lines = []
        for w in weather_list:
            lines.append(
                f"{w.date}: 白天{w.day_weather} {w.day_temp}°C / 夜间{w.night_weather} {w.night_temp}°C, 风向{w.wind_direction} {w.wind_power}"
            )
        return "\n".join(lines)

    def _ensure_budget(self, trip_plan: TripPlan, request: TripRequest) -> TripPlan:
        """若行程计划缺少预算, 按实际费用自动计算补齐"""
        if trip_plan.budget is not None:
            return trip_plan

        total_attractions = sum(a.ticket_price for day in trip_plan.days for a in day.attractions)
        total_meals = sum(m.estimated_cost for day in trip_plan.days for m in day.meals)
        total_hotels = sum(day.hotel.estimated_cost for day in trip_plan.days if day.hotel and day.hotel.estimated_cost)
        total_transportation = 50 * request.travel_days

        total_attractions = total_attractions or 200
        total_meals = total_meals or 150 * request.travel_days
        total_hotels = total_hotels or 400 * request.travel_days

        trip_plan.budget = Budget(
            total_attractions=total_attractions,
            total_hotels=total_hotels,
            total_meals=total_meals,
            total_transportation=total_transportation,
            total=total_attractions + total_hotels + total_meals + total_transportation,
        )
        return trip_plan

    def _create_fallback_plan(
        self,
        request: TripRequest,
        attraction_pois: List[POIInfo] = None,
        hotel_pois: List[POIInfo] = None,
        meal_pois: List[POIInfo] = None,
        weather_info: List[WeatherInfo] = None,
        reason: str = "",
    ) -> TripPlan:
        """创建备用计划(当LLM失败时兜底)

        修复要点(旧版bug: 硬编码北京坐标116.4/39.9, 导致成都行程地图显示北京;
        且完全丢弃已搜到的真实POI, 生成"成都景点1"等占位假数据):
        1. 景点: 用高德真实搜索结果(真实名称+真实坐标), 按天轮流分配
        2. 酒店: 取真实酒店POI, 无结果时按住宿偏好重试搜索一次
        3. 餐饮: 用高德"美食"真实店铺, 早中晚轮流分配具体店名
        4. 坐标兜底: 连景点都搜不到时, 用高德地理编码取该城市中心坐标, 绝不硬编码北京
        5. 打上 is_fallback 标记, 前端可提示用户这是降级数据
        """
        attraction_pois = attraction_pois or []
        hotel_pois = hotel_pois or []
        meal_pois = meal_pois or []
        weather_info = weather_info or []

        start_date = datetime.strptime(request.start_date, "%Y-%m-%d")

        # ---- 城市中心坐标兜底 (替代旧版硬编码的北京 116.4/39.9) ----
        city_center = self._get_city_center(request.city)

        # ---- 景点为空时再兜底搜一次通用"景点"关键词 ----
        if not attraction_pois:
            try:
                attraction_pois = self.amap_service.search_poi("景点", request.city)
            except Exception as e:
                logger.warning(f"   ⚠️ 兜底景点搜索失败: {e}")

        # ---- 酒店为空时再兜底搜一次 ----
        if not hotel_pois:
            try:
                hotel_pois = self.amap_service.search_poi(request.accommodation or "酒店", request.city)
            except Exception as e:
                logger.warning(f"   ⚠️ 兜底酒店搜索失败: {e}")

        # ---- 餐饮为空时再兜底搜一次 ----
        if not meal_pois:
            try:
                meal_pois = self.amap_service.search_poi("特色美食餐厅", request.city)
            except Exception as e:
                logger.warning(f"   ⚠️ 兜底美食搜索失败: {e}")

        hotel = self._poi_to_hotel(hotel_pois[0]) if hotel_pois else None

        days = []
        for i in range(request.travel_days):
            current_date = start_date + timedelta(days=i)

            # 每天分配2-3个真实景点(轮流取, 保证天数多时不重复)
            day_attractions = []
            if attraction_pois:
                per_day = 3 if request.travel_days <= 3 else 2
                for j in range(per_day):
                    idx = (i * per_day + j) % len(attraction_pois)
                    poi = attraction_pois[idx]
                    day_attractions.append(Attraction(
                        name=poi.name,
                        address=poi.address or f"{request.city}市",
                        location=poi.location if poi.location and (poi.location.longitude or poi.location.latitude) else city_center,
                        visit_duration=120,
                        description=f"{poi.name}是{request.city}的热门地点(高德真实POI数据, 类型: {poi.type or '未分类'})。",
                        category=(poi.type.split(";")[0] if poi.type else "景点"),
                        poi_id=poi.id,
                    ))
            else:
                # 极端情况: 高德也搜不到任何POI, 用城市中心坐标放占位景点(不再用北京坐标)
                for j in range(2):
                    day_attractions.append(Attraction(
                        name=f"{request.city}景点{j+1}",
                        address=f"{request.city}市",
                        location=Location(
                            longitude=city_center.longitude + j * 0.005,
                            latitude=city_center.latitude + j * 0.005,
                        ),
                        visit_duration=120,
                        description=f"这是{request.city}的著名景点",
                        category="景点",
                    ))

            # 三餐: 轮流分配真实美食店铺
            day_meals = []
            meal_specs = [("breakfast", "早餐", 30), ("lunch", "午餐", 50), ("dinner", "晚餐", 80)]
            for k, (mtype, label, cost) in enumerate(meal_specs):
                if meal_pois:
                    poi = meal_pois[(i * 3 + k) % len(meal_pois)]
                    day_meals.append(Meal(
                        type=mtype,
                        name=poi.name,
                        address=poi.address or None,
                        location=poi.location,
                        description=f"{request.city}当地{label}推荐店铺(高德真实POI, 类型: {poi.type or '餐饮'})",
                        estimated_cost=cost,
                    ))
                else:
                    day_meals.append(Meal(
                        type=mtype, name=f"第{i+1}天{label}",
                        description=f"{request.city}当地特色{label}", estimated_cost=cost,
                    ))

            days.append(DayPlan(
                date=current_date.strftime("%Y-%m-%d"),
                day_index=i,
                description=f"第{i+1}天: " + " → ".join(a.name for a in day_attractions),
                transportation=request.transportation,
                accommodation=request.accommodation,
                hotel=hotel,
                attractions=day_attractions,
                meals=day_meals,
            ))

        total_attractions = sum(attr.ticket_price for day in days for attr in day.attractions) or 200
        total_meals = sum(meal.estimated_cost for day in days for meal in day.meals) or 150 * request.travel_days
        total_hotels = (hotel.estimated_cost or 400) * request.travel_days if hotel else 400 * request.travel_days
        total_transportation = 50 * request.travel_days

        return TripPlan(
            city=request.city,
            start_date=request.start_date,
            end_date=request.end_date,
            days=days,
            weather_info=[],  # 由 plan_trip 统一按行程日期过滤后回填真实天气
            overall_suggestions=(
                f"这是为您规划的{request.city}{request.travel_days}日游行程(基于高德真实POI数据自动编排)。"
                f"建议提前查看各景点的开放时间与门票预约要求, {request.transportation}出行请预留高峰期时间; "
                f"用餐店铺为当地热门选择, 饭点可能排队, 建议错峰前往。"
            ),
            budget=Budget(
                total_attractions=total_attractions,
                total_hotels=total_hotels,
                total_meals=total_meals,
                total_transportation=total_transportation,
                total=total_attractions + total_hotels + total_meals + total_transportation,
            ),
            is_fallback=True,
            fallback_reason=f"LLM 生成失败({reason}), 当前行程由高德真实POI数据自动编排, 缺少AI个性化建议。请检查后端 LLM_API_KEY 配置后重新生成。",
        )

    def _get_city_center(self, city: str) -> Location:
        """地理编码获取城市中心坐标 (失败时返回经纬度0, 前端会跳过无效标记)"""
        try:
            geocodes = self.amap_service.geocode(city)
            if geocodes and geocodes[0].get("location"):
                return self.amap_service._parse_location(geocodes[0]["location"])
        except Exception as e:
            logger.warning(f"   ⚠️ 城市中心坐标获取失败: {e}")
        return Location(longitude=0, latitude=0)

    @staticmethod
    def _poi_to_hotel(poi: POIInfo) -> Hotel:
        """POI 转酒店模型 (兜底计划用)"""
        return Hotel(
            name=poi.name,
            address=poi.address or "",
            location=poi.location,
            price_range="以实际预订价格为准",
            rating="",
            distance="",
            type=(poi.type.split(";")[0] if poi.type else "酒店"),
            estimated_cost=400,
        )


# 全局多智能体系统实例
_multi_agent_planner = None


def get_trip_planner_agent() -> MultiAgentTripPlanner:
    """获取多智能体旅行规划系统实例(单例模式)"""
    global _multi_agent_planner

    if _multi_agent_planner is None:
        _multi_agent_planner = MultiAgentTripPlanner()

    return _multi_agent_planner
