"""Open-Meteo 天气补充服务 (免费开源预报API, 无需key, 支持未来16天)

用途: 高德免费天气预报仅覆盖"今天起未来4天", 行程日期超出时前端无天气可展示。
本服务作为补充数据源, 为行程日期中未被高德覆盖的部分提供预报。

数据合并策略(由 supplement_weather 实现):
1. 高德已有的日期 → 保留高德数据(国内官方源, 优先)
2. 高德没有、但在 Open-Meteo 16天窗口内的日期 → 用 Open-Meteo 补齐
3. 两者都覆盖不到的日期(>16天) → 留空, 由前端提示出行前自查

失败降级: Open-Meteo 请求失败时静默跳过, 不影响主流程(与高德失败的处理一致)。
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import httpx

from ..models.schemas import Location, WeatherInfo

logger = logging.getLogger(__name__)

# Open-Meteo 预报接口 (免费, 无需API key)
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# Open-Meteo 预报窗口: 今天起未来16天
_FORECAST_WINDOW_DAYS = 15

# WMO 天气代码 → 中文天气描述 (Open-Meteo daily.weather_code)
_WMO_CODE_MAP: Dict[int, str] = {
    0: "晴", 1: "晴间多云", 2: "多云", 3: "阴",
    45: "雾", 48: "冻雾",
    51: "毛毛雨", 53: "毛毛雨", 55: "浓毛毛雨",
    56: "冻毛毛雨", 57: "冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "强冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "米雪",
    80: "小阵雨", 81: "阵雨", 82: "强阵雨",
    85: "小阵雪", 86: "大阵雪",
    95: "雷阵雨", 96: "雷阵雨伴冰雹", 99: "强雷阵雨伴冰雹",
}

# 风向方位 (16方位简化为8方位)
_WIND_DIRECTIONS = ["北风", "东北风", "东风", "东南风", "南风", "西南风", "西风", "西北风"]

# 风速(km/h)上限 → 蒲福风力等级
_WIND_SCALE = [(1, 0), (5, 1), (11, 2), (19, 3), (28, 4), (38, 5), (49, 6),
               (61, 7), (74, 8), (88, 9), (102, 10), (117, 11)]


class OpenMeteoService:
    """Open-Meteo 天气查询封装"""

    def __init__(self):
        self.client = httpx.Client(timeout=10)

    @staticmethod
    def _wind_direction(degrees: Optional[float]) -> str:
        """风向角度转中文方位"""
        if degrees is None:
            return ""
        idx = int((degrees + 22.5) % 360 // 45)
        return _WIND_DIRECTIONS[idx]

    @staticmethod
    def _wind_power(speed_kmh: Optional[float]) -> str:
        """风速(km/h)转蒲福风力等级"""
        if speed_kmh is None:
            return ""
        for limit, level in _WIND_SCALE:
            if speed_kmh < limit:
                return f"{level}级"
        return "12级"

    def fetch_forecast(
        self, location: Location, start_date: str, end_date: str
    ) -> List[WeatherInfo]:
        """查询指定经纬度、日期范围的逐日预报

        Args:
            location: 城市中心坐标
            start_date: 开始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD (超出16天窗口的部分自动截断)

        Returns:
            WeatherInfo 列表 (day_weather/night_weather 为全天天气码, 温度取当日最高/最低)
        """
        if not location.longitude and not location.latitude:
            return []

        # 截断到 Open-Meteo 的预报窗口内 (今天 ~ 今天+15天)
        today = datetime.now().date()
        window_end = today + timedelta(days=_FORECAST_WINDOW_DAYS)
        try:
            sd = datetime.strptime(start_date, "%Y-%m-%d").date()
            ed = datetime.strptime(end_date, "%Y-%m-%d").date()
        except ValueError:
            return []
        sd = max(sd, today)
        ed = min(ed, window_end)
        if sd > ed:
            return []

        resp = self.client.get(OPEN_METEO_URL, params={
            "latitude": location.latitude,
            "longitude": location.longitude,
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                     "wind_direction_10m_dominant,wind_speed_10m_max",
            "start_date": sd.strftime("%Y-%m-%d"),
            "end_date": ed.strftime("%Y-%m-%d"),
            "timezone": "Asia/Shanghai",
        })
        resp.raise_for_status()
        daily = resp.json().get("daily") or {}
        dates = daily.get("time") or []

        weather_list: List[WeatherInfo] = []
        for i, d in enumerate(dates):
            code = (daily.get("weather_code") or [None])[i]
            weather_text = _WMO_CODE_MAP.get(code, "未知") if code is not None else ""
            weather_list.append(WeatherInfo(
                date=d,
                day_weather=weather_text,
                night_weather=weather_text,
                day_temp=round((daily.get("temperature_2m_max") or [0])[i] or 0),
                night_temp=round((daily.get("temperature_2m_min") or [0])[i] or 0),
                wind_direction=self._wind_direction((daily.get("wind_direction_10m_dominant") or [None])[i]),
                wind_power=self._wind_power((daily.get("wind_speed_10m_max") or [None])[i]),
            ))
        return weather_list

    def supplement_weather(
        self,
        location: Location,
        start_date: str,
        end_date: str,
        existing: List[WeatherInfo],
    ) -> List[WeatherInfo]:
        """用 Open-Meteo 补齐行程日期中已有天气源未覆盖的部分

        Args:
            location: 城市中心坐标
            start_date/end_date: 行程日期范围
            existing: 已有天气数据(如高德4天预报)

        Returns:
            合并后的天气列表 (按日期升序; 高德数据优先保留)
        """
        existing_dates = {w.date for w in existing if w.date}

        # 行程中缺天气、且落在16天预报窗口内的日期
        today = datetime.now().date()
        window_end = today + timedelta(days=_FORECAST_WINDOW_DAYS)
        try:
            sd = datetime.strptime(start_date, "%Y-%m-%d").date()
            ed = datetime.strptime(end_date, "%Y-%m-%d").date()
        except ValueError:
            return existing
        missing = [
            (sd + timedelta(days=i)).strftime("%Y-%m-%d")
            for i in range((ed - sd).days + 1)
            if (sd + timedelta(days=i)).strftime("%Y-%m-%d") not in existing_dates
            and today <= sd + timedelta(days=i) <= window_end
        ]
        if not missing:
            return existing

        try:
            extra = self.fetch_forecast(location, missing[0], missing[-1])
            # 只补缺失日期, 不覆盖高德已有数据
            extra = [w for w in extra if w.date in set(missing)]
            merged = sorted(existing + extra, key=lambda w: w.date)
            logger.info(f"   + Open-Meteo 补充 {len(extra)} 天天气 (行程缺失日期)")
            return merged
        except Exception as e:
            logger.warning(f"   ⚠️ Open-Meteo 天气补充失败(不影响主流程): {e}")
            return existing


# 全局单例
_open_meteo_service: Optional[OpenMeteoService] = None


def get_open_meteo_service() -> OpenMeteoService:
    """获取 Open-Meteo 服务实例(单例模式)"""
    global _open_meteo_service
    if _open_meteo_service is None:
        _open_meteo_service = OpenMeteoService()
    return _open_meteo_service
