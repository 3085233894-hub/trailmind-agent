from langchain_core.tools import tool


def _level_from_score(score: float) -> str:
    if score < 35:
        return "低风险"
    if score < 65:
        return "中等风险"
    return "高风险"


@tool
def assess_hiking_risk(
    temperature_max_c: float,
    precipitation_probability_max: float,
    wind_speed_max_kmh: float,
    uv_index_max: float = 0,
    user_level: str = "新手",
    duration_hours: float = 3.0,
    distance_km: float | None = None,
    elevation_gain_m: float = 100.0,
) -> dict:
    """
    根据天气、用户水平和预计时长评估徒步风险。
    这是确定性规则模型，不依赖 LLM 主观打分。
    """

    if distance_km is None:
        # MVP 阶段没有真实路线，按新手徒步均速约 3km/h 粗估
        distance_km = duration_hours * 3.0

    risks = []
    gear = [
        "舒适防滑徒步鞋",
        "饮用水",
        "能量补给",
        "手机与充电宝",
        "简易急救包",
        "离线地图或导航 App",
    ]

    score = 0.0

    # 降雨风险
    if precipitation_probability_max >= 70:
        score += 35
        risks.append("降水概率较高，路面湿滑风险明显")
        gear.extend(["雨衣", "防水袋", "登山杖"])
    elif precipitation_probability_max >= 40:
        score += 20
        risks.append("存在一定降水概率，建议准备雨具")
        gear.extend(["轻便雨衣", "防水袋"])
    else:
        score += 5

    # 风速风险
    if wind_speed_max_kmh >= 35:
        score += 25
        risks.append("风速较大，湖边、山脊或空旷区域体感风险增加")
        gear.append("防风外套")
    elif wind_speed_max_kmh >= 20:
        score += 12
        risks.append("有一定风力，建议携带防风外套")
        gear.append("防风外套")
    else:
        score += 3

    # 温度风险
    if temperature_max_c >= 35:
        score += 25
        risks.append("最高气温较高，有中暑风险")
        gear.extend(["遮阳帽", "防晒霜", "电解质饮料"])
    elif temperature_max_c >= 30:
        score += 15
        risks.append("气温偏高，需要注意补水和防晒")
        gear.extend(["遮阳帽", "防晒霜"])
    elif temperature_max_c <= 5:
        score += 20
        risks.append("气温较低，有失温风险")
        gear.extend(["保暖层", "手套", "防风外套"])
    else:
        score += 5

    # 紫外线风险
    if uv_index_max >= 7:
        score += 10
        risks.append("紫外线较强，需要防晒")
        gear.extend(["防晒霜", "太阳镜", "遮阳帽"])
    elif uv_index_max >= 4:
        score += 5
        risks.append("紫外线中等，建议基础防晒")

    # 距离/时长风险
    if user_level in ["新手", "初学者", "beginner"]:
        if duration_hours > 4 or distance_km > 10:
            score += 20
            risks.append("预计路线对新手略长，建议缩短距离或选择成熟景区步道")
        elif duration_hours > 3:
            score += 10
            risks.append("时长接近新手舒适上限，建议控制节奏")
        else:
            score += 3
    else:
        score += 5

    # 爬升风险
    if elevation_gain_m >= 800:
        score += 25
        risks.append("累计爬升较大，不适合新手")
    elif elevation_gain_m >= 300:
        score += 12
        risks.append("存在一定爬升，需要注意体力分配")
    else:
        score += 3

    score = min(round(score), 100)
    risk_level = _level_from_score(score)

    if risk_level == "高风险":
        recommendation = "不推荐按原计划出行，建议改期或选择城市公园、景区短线。"
        recommend_go = False
    elif risk_level == "中等风险":
        recommendation = "可以出行，但建议选择成熟短线，控制在3小时以内，并根据天气准备装备。"
        recommend_go = True
    else:
        recommendation = "整体适合新手短途徒步，仍需携带基础装备并关注临近天气变化。"
        recommend_go = True

    # 去重，同时保持顺序
    gear = list(dict.fromkeys(gear))

    return {
        "risk_level": risk_level,
        "risk_score": score,
        "main_risks": risks if risks else ["未发现明显天气或强度风险"],
        "recommendation": recommendation,
        "recommend_go": recommend_go,
        "estimated_distance_km": round(distance_km, 1),
        "duration_hours": duration_hours,
        "gear_advice": gear,
    }