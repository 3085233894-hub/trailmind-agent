from pydantic import BaseModel, Field


class PlanRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=2,
        description="用户自然语言徒步需求，例如：我周末想在武汉东湖附近徒步，新手，3小时以内，帮我判断是否适合。",
    )