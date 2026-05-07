from __future__ import annotations

import json
import os
import signal
import sys
import time
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


DEFAULT_QUERY = "我想从清华大学徒步到颐和园，途经圆明园，新手，4小时以内，帮我规划。"
QUERY = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_QUERY
STEP_TIMEOUT_SECONDS = int(os.getenv("STEP_TIMEOUT_SECONDS", "120"))


class StepTimeout(Exception):
    pass


def _timeout_handler(signum, frame):
    raise StepTimeout("step timeout")


@contextmanager
def timeout_guard(seconds: int):
    old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(seconds)

    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


def preview(value: Any, limit: int = 1600) -> str:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    except Exception:
        text = str(value)

    if len(text) > limit:
        return text[:limit] + "\n... <truncated>"

    return text


def print_header(title: str) -> None:
    print("\n" + "=" * 100, flush=True)
    print(title, flush=True)
    print("=" * 100, flush=True)


def run_step(name: str, func, state: dict, timeout_seconds: int = STEP_TIMEOUT_SECONDS) -> bool:
    print_header(f"START STEP: {name}")
    print(f"timeout = {timeout_seconds}s", flush=True)

    t0 = time.perf_counter()

    try:
        with timeout_guard(timeout_seconds):
            result = func(state)

        elapsed = time.perf_counter() - t0

        print(f"[OK] {name} finished in {elapsed:.2f}s", flush=True)
        print("result keys:", list(result.keys()) if isinstance(result, dict) else type(result), flush=True)
        print(preview(result), flush=True)

        if isinstance(result, dict):
            state.update(result)

        last_trace = (state.get("tool_trace") or [])[-1:] or []
        if last_trace:
            print("\nlast tool_trace:", flush=True)
            print(preview(last_trace), flush=True)

        return True

    except StepTimeout:
        elapsed = time.perf_counter() - t0
        print(f"[TIMEOUT] {name} exceeded {timeout_seconds}s, elapsed={elapsed:.2f}s", flush=True)
        return False

    except Exception as exc:
        elapsed = time.perf_counter() - t0
        print(f"[ERROR] {name} failed after {elapsed:.2f}s: {exc}", flush=True)
        traceback.print_exc()
        return False


def main() -> None:
    print_header("IMPORT graph module")
    print(f"query = {QUERY}", flush=True)

    t0 = time.perf_counter()

    try:
        with timeout_guard(STEP_TIMEOUT_SECONDS):
            from app.agent import graph as graph_module

        print(f"[OK] import app.agent.graph finished in {time.perf_counter() - t0:.2f}s", flush=True)

    except StepTimeout:
        print(f"[TIMEOUT] import app.agent.graph exceeded {STEP_TIMEOUT_SECONDS}s", flush=True)
        return

    except Exception as exc:
        print(f"[ERROR] import app.agent.graph failed: {exc}", flush=True)
        traceback.print_exc()
        return

    print_header("RULE FALLBACK INTENT PARSE")

    try:
        t0 = time.perf_counter()
        parsed = graph_module._fallback_parse_intent(QUERY)
        print(f"[OK] _fallback_parse_intent finished in {time.perf_counter() - t0:.2f}s", flush=True)
        print(preview(parsed), flush=True)
    except Exception as exc:
        print(f"[ERROR] _fallback_parse_intent failed: {exc}", flush=True)
        traceback.print_exc()

    print_header("RUN GRAPH NODES STEP BY STEP")

    state = graph_module.initial_state(QUERY)

    steps = [
        ("parse_user_intent", graph_module.parse_user_intent, STEP_TIMEOUT_SECONDS),
        ("geocode_location", graph_module.geocode_location, STEP_TIMEOUT_SECONDS),
        ("search_candidate_trails", graph_module.search_candidate_trails, STEP_TIMEOUT_SECONDS),
        ("fetch_weather", graph_module.fetch_weather, STEP_TIMEOUT_SECONDS),
        ("assess_risk", graph_module.assess_risk, STEP_TIMEOUT_SECONDS),
        ("retrieve_safety_knowledge", graph_module.retrieve_safety_knowledge, STEP_TIMEOUT_SECONDS),
        ("generate_final_plan", graph_module.generate_final_plan, STEP_TIMEOUT_SECONDS),
        ("validate_output", graph_module.validate_output, STEP_TIMEOUT_SECONDS),
    ]

    for name, func, timeout_seconds in steps:
        ok = run_step(
            name=name,
            func=func,
            state=state,
            timeout_seconds=timeout_seconds,
        )

        if not ok:
            print_header("STOPPED")
            print(f"Stopped at step: {name}", flush=True)
            print("Current state summary:", flush=True)
            summary = {
                "route_mode": state.get("route_mode"),
                "location_text": state.get("location_text"),
                "start_location_text": state.get("start_location_text"),
                "end_location_text": state.get("end_location_text"),
                "waypoint_texts": state.get("waypoint_texts"),
                "location_name": state.get("location_name"),
                "start_location_name": state.get("start_location_name"),
                "end_location_name": state.get("end_location_name"),
                "candidate_trails_count": len(state.get("candidate_trails") or []),
                "selected_trail": state.get("selected_trail"),
                "errors": state.get("errors"),
            }
            print(preview(summary), flush=True)
            return

    print_header("DONE")
    print("All steps finished.", flush=True)
    print("Final state summary:", flush=True)

    summary = {
        "route_mode": state.get("route_mode"),
        "location_text": state.get("location_text"),
        "start_location_text": state.get("start_location_text"),
        "end_location_text": state.get("end_location_text"),
        "waypoint_texts": state.get("waypoint_texts"),
        "candidate_trails_count": len(state.get("candidate_trails") or []),
        "selected_trail": state.get("selected_trail"),
        "risk_report": state.get("risk_report"),
        "weather_ok": bool(state.get("weather")),
        "safety_knowledge_count": len(state.get("safety_knowledge") or []),
        "errors": state.get("errors"),
    }

    print(preview(summary), flush=True)


if __name__ == "__main__":
    main()
