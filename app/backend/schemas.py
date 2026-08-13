"""app/backend 전용 FE 응답 스키마. app/api_models.py의 ChatSource/ChatImage를 그대로 재사용한다.

FE가 실제로 쓰는 필드만 남긴 축소판 — question_language/meta(캐시·소요시간 등 디버그 정보)는
지금 FE 화면에 안 쓰여서 뺐다. 나중에 필요해지면 다시 추가하면 된다.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..api_models import ChatImage, ChatSource


class BackendChatData(BaseModel):
    answer: str
    sources: list[ChatSource] = Field(default_factory=list)
    images: list[ChatImage] = Field(default_factory=list)


class BackendErrorDetail(BaseModel):
    message: str
