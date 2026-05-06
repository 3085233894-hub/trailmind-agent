import sys
from app.agent.graph import run_graph


def main():
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
    else:
        query = "我周末想在杭州西湖附近徒步，新手，3小时以内，帮我判断是否适合。"

    result = run_graph(query)

    print("\n========== LangGraph Agent 输出 ==========\n")
    print(result["answer"])

    print("\n========== 选中路线 ==========\n")
    print(result.get("selected_trail"))

    print("\n========== 风险报告 ==========\n")
    print(result.get("risk_report"))

    print("\n========== Plan B ==========\n")
    print(result.get("plan_b"))

    print("\n========== 工作流轨迹 ==========\n")
    for item in result["tool_trace"]:
        print(item)

    if result.get("errors"):
        print("\n========== 错误 / 兜底信息 ==========\n")
        for error in result["errors"]:
            print("-", error)


if __name__ == "__main__":
    main()