import json

from langchain_anthropic import ChatAnthropic
from langchain.agents import create_agent

from app.config import API_KEY, MODEL, get_anthropic_api_url
from app.tools.geocode_tool import geocode_place
from app.tools.weather_tool import get_weather_forecast
from app.tools.risk_tool import assess_hiking_risk
from app.tools.trail_search_tool import search_hiking_trails


SYSTEM_PROMPT = """
你是 TrailMind，一个户外徒步规划 Agent。

你的任务是根据用户的自然语言需求，完成：
1. 识别徒步地点
2. 调用 geocode_place 获取经纬度
3. 调用 search_hiking_trails 查询附近候选徒步路线
4. 调用 get_weather_forecast 查询天气
5. 选择一条最适合用户条件的候选路线
6. 调用 assess_hiking_risk 评估风险
7. 给出路线建议、装备建议和是否推荐出行

工具调用顺序必须严格遵守：
1. 先调用 geocode_place
2. 等 geocode_place 返回 ok=true 后，使用返回的 latitude、longitude 和 name 调用 search_hiking_trails
3. 再调用 get_weather_forecast
4. 最后调用 assess_hiking_risk

每一轮只能调用一个工具。
禁止在同一轮同时调用 geocode_place、search_hiking_trails 和 get_weather_forecast。
禁止自己猜测经纬度。
禁止编造路线名称。
禁止编造天气结果。
禁止编造风险等级。

路线检索规则：
- search_hiking_trails 返回 trails 后，优先选择 score 最高且 estimated_duration_hours 不超过用户时长限制的路线。
- 如果所有路线都超过时长限制，选择距离最短的一条，并说明“仅作为候选，不建议完整走完”。
- 如果 query_mode 是 fallback_highway，必须说明“附近未查到标准 route=hiking，当前展示的是城市步行路径候选”。
- 如果路线名称包含“未命名步道”，不要润色成虚构景点名。
- 如果 distance_km 是 None，不要编造距离。

参数提取规则：
- 如果用户说“周末”，优先使用 get_weather_forecast 返回的 selected_dates。
- 如果用户说“新手”“初学者”“没经验”，user_level 传入“新手”。
- 如果用户说“3小时以内”，duration_hours 传入 3。
- 如果用户表达“湖边 / 森林 / 山景 / 亲子 / 新手”等偏好，将其作为 preference 传给 search_hiking_trails。
- 如果没有明确偏好，但地点是西湖，可以把 preference 设为“湖边 新手”。
- assess_hiking_risk 的 distance_km 应使用所选路线的 distance_km；如果路线 distance_km 为 None，则可以不传。
- MVP 阶段暂时没有真实爬升数据，elevation_gain_m 可以传入 100。

最终回答必须严格使用以下 Markdown 标题，不允许新增一级或二级标题，不允许使用表格：

## 地点识别
- 识别地点：
- 经纬度：

## 候选路线
- 推荐路线：
- 路线来源：
- 预计距离：
- 预计耗时：
- 难度：
- 说明：

## 天气概况
- 查询日期：
- 最高温：
- 最低温：
- 最大降水概率：
- 最大风速：
- 紫外线指数：

## 风险评估
- 风险等级：
- 风险分数：
- 主要风险：

## 装备建议
- ...

## 是否推荐出行
- 推荐/不推荐：
- 原因：
"""


def normalize_content(content) -> str:
    """
    兼容不同模型的返回格式。

    常见情况：
    1. content 是 str
    2. content 是 list[dict]，例如：
       [
           {"type": "thinking", ...},
           {"type": "text", "text": "..."}
       ]
    """
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        texts = []

        for block in content:
            if isinstance(block, dict):
                text = block.get("text")
                if text:
                    texts.append(text)
            else:
                texts.append(str(block))

        return "\n".join(texts).strip()

    return str(content)


def _try_parse_json(text: str):
    try:
        return json.loads(text)
    except Exception:
        return {"raw": text}


def build_agent():
    if not API_KEY:
        raise ValueError("API_KEY 未配置，请检查 .env 文件")

    llm_kwargs = {
        "model": MODEL,
        "anthropic_api_key": API_KEY,
        "max_tokens": 1800,
        "temperature": 0.2,
    }

    api_url = get_anthropic_api_url()
    if api_url:
        llm_kwargs["anthropic_api_url"] = api_url

    llm = ChatAnthropic(**llm_kwargs)

    tools = [
        geocode_place,
        search_hiking_trails,
        get_weather_forecast,
        assess_hiking_risk,
    ]

    return create_agent(
        model=llm,
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
    )


agent = build_agent()


def extract_tool_trace(messages) -> list[dict]:
    trace = []

    for msg in messages:
        tool_calls = getattr(msg, "tool_calls", None)

        if tool_calls:
            for call in tool_calls:
                trace.append(
                    {
                        "type": "tool_call",
                        "tool": call.get("name"),
                        "input": call.get("args"),
                    }
                )

        if getattr(msg, "type", None) == "tool":
            trace.append(
                {
                    "type": "tool_result",
                    "tool": getattr(msg, "name", "unknown"),
                    "output_preview": normalize_content(msg.content)[:1000],
                }
            )

    return trace


def extract_tool_outputs(messages) -> dict:
    """
    提取完整工具输出，方便 Streamlit 展示候选路线列表。
    """
    outputs: dict[str, list] = {}

    for msg in messages:
        if getattr(msg, "type", None) != "tool":
            continue

        name = getattr(msg, "name", "unknown")
        content = normalize_content(msg.content)
        parsed = _try_parse_json(content)

        outputs.setdefault(name, []).append(parsed)

    return outputs


def _extract_candidate_trails(tool_outputs: dict) -> list[dict]:
    search_outputs = tool_outputs.get("search_hiking_trails", [])

    if not search_outputs:
        return []

    latest = search_outputs[-1]

    if not isinstance(latest, dict):
        return []

    trails = latest.get("trails", [])

    if isinstance(trails, list):
        return trails

    return []


def run_agent(query: str) -> dict:
    if not query or not query.strip():
        raise ValueError("用户输入不能为空")

    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": query.strip(),
                }
            ]
        }
    )

    messages = result["messages"]

    final_answer = normalize_content(messages[-1].content)
    tool_trace = extract_tool_trace(messages)
    tool_outputs = extract_tool_outputs(messages)
    candidate_trails = _extract_candidate_trails(tool_outputs)

    return {
        "answer": final_answer,
        "tool_trace": tool_trace,
        "tool_outputs": tool_outputs,
        "candidate_trails": candidate_trails,
        "raw_messages": messages,
    }