import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("API_KEY")
BASE_URL = os.getenv("BASE_URL")
MODEL = os.getenv("MODEL", "MiniMax-M2.7")
ORS_API_KEY = os.getenv("ORS_API_KEY")

def get_anthropic_api_url() -> str | None:
    """
    将类似 https://xxx/api/v1 的接口转换成 Anthropic 兼容接口地址。
    你之前的写法 BASE_URL.rstrip("/api/v1") 有潜在问题：
    rstrip 不是移除固定字符串，而是移除字符集合。
    """
    if not BASE_URL:
        return None

    url = BASE_URL.rstrip("/")

    if url.endswith("/api/v1"):
        return url[: -len("/api/v1")] + "/api"

    return url