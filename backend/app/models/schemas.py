"""
Pydantic 요청/응답 스키마.

검증을 여기서 하는 이유:
  Firestore 는 스키마가 없는 NoSQL 이라 잘못된 값도 그대로 저장된다.
  따라서 '앱 경계'에서 막아야 하고, FastAPI 는 Pydantic 모델로 선언만 하면
  형식 오류를 자동으로 422 로 돌려준다. 검증 규칙이 한 곳에 모이고
  Swagger 문서도 이 선언에서 자동 생성된다.
"""

from __future__ import annotations

from datetime import date as _date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_MESSAGE_LEN = 2000


# ---------------------------------------------------------------- data
class DataCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {"date": "2026-09-07", "value": 4820, "memo": "전어"}
        }
    )

    date: _date = Field(..., description="측정 날짜 (YYYY-MM-DD)")
    value: float = Field(..., ge=0, le=10_000_000, description="제철 식재료 kg당 평균가(원)")
    memo: str = Field("", max_length=200, description="대표 제철 품목명 등 메모")

    @field_validator("memo")
    @classmethod
    def strip_memo(cls, v: str) -> str:
        return v.strip()


class DataUpdate(BaseModel):
    """부분 수정(PUT). 보낸 필드만 반영된다."""

    date: Optional[_date] = None
    value: Optional[float] = Field(None, ge=0, le=10_000_000)
    memo: Optional[str] = Field(None, max_length=200)

    @field_validator("memo")
    @classmethod
    def strip_memo(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if v is not None else None


class DataOut(BaseModel):
    id: str
    date: str
    value: float
    memo: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class DataListOut(BaseModel):
    count: int
    items: list[DataOut]


# ---------------------------------------------------------------- summary
class ItemVerdict(BaseModel):
    """품목 하나의 두 축과 판정. 이 서비스의 핵심 단위."""

    item: str
    count: int
    latest: Optional[float] = None
    latest_date: Optional[str] = None

    recent_avg: Optional[float] = Field(None, description="최근 7일 평균")
    prev_avg: Optional[float] = Field(None, description="직전 7일 평균")
    normal_avg: Optional[float] = Field(None, description="같은 시기 평년 평균")

    vs_normal_pct: Optional[float] = Field(None, description="평년 대비 등락률(%)")
    change_rate_pct: Optional[float] = Field(None, description="전주 대비 등락률(%)")

    verdict: str
    verdict_short: str = ""
    verdict_tone: Literal["good", "mid", "warn", "bad"] = "mid"
    verdict_reason: str

    min: Optional[float] = None
    max: Optional[float] = None
    average: Optional[float] = None
    cheapest_month: Optional[int] = Field(None, description="1년 중 평균가가 가장 낮은 달")
    normal_peers: int = 0


class BasketOut(BaseModel):
    today: Optional[float] = None
    recent_avg: Optional[float] = None
    prev_avg: Optional[float] = None
    change_rate_pct: Optional[float] = None
    note: str = ""


class SummaryMetrics(BaseModel):
    """전체 레코드에 대한 기본 통계. 품목별 지표는 ItemVerdict 에 있다."""

    total: float
    average: float
    max: float
    min: float
    std_dev: Optional[float] = Field(None, description="표준편차(변동성)")


class ItemStat(BaseModel):
    item: str
    avg: float
    count: int


class SummaryOut(BaseModel):
    period: str
    count: int
    item_count: int = 0

    # 이 값이 '무엇'에 대한 것인지. 숫자만 뜨면 해석이 불가능하다.
    subject: str = Field("", description="측정 대상")
    subject_detail: str = Field("", description="대상의 정확한 정의")
    unit: str = "원/kg"

    # ── 핵심: 품목별 판정 ────────────────────────────────
    items: list[ItemVerdict] = Field(default_factory=list,
                                     description="평년 대비가 낮은(사기 좋은) 순")
    buy_now: list[str] = Field(default_factory=list, description="지금 사기 좋은 품목")
    avoid: list[str] = Field(default_factory=list, description="미루는 편이 나은 품목")
    basket: BasketOut = Field(default_factory=BasketOut)

    # ── 전체 판정 (헤드라인) ─────────────────────────────
    trend: str = Field("", description="장바구니 합계의 전주 대비 추세")
    verdict: str = Field(..., description="5단계 판정")
    verdict_short: str = Field("", description="표에 넣을 짧은 판정")
    verdict_tone: Literal["good", "mid", "warn", "bad"] = "mid"
    verdict_reason: str = Field(..., description="판정 근거 — 프롬프트에 그대로 주입된다")
    vs_normal_median_pct: Optional[float] = Field(
        None, description="품목별 평년 대비의 중앙값. 평균은 값이 큰 품목에 끌려간다.")
    normal_basis: str = Field("", description="평년을 어떻게 구했는지")

    # ── 전체 통계 ────────────────────────────────────────
    metrics: SummaryMetrics
    monthly_average: dict[str, float] = Field(default_factory=dict)
    peak_date: Optional[str] = None
    trough_date: Optional[str] = None


# ---------------------------------------------------------------- recommend
class RecommendRequest(BaseModel):
    """화면의 조건 손잡이. 전부 선택 사항이며, 안 주면 '상관없음'으로 본다."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "prep": ["국·찌개"], "purpose": ["밥반찬"],
                "season_weight": 0.8, "difficulty": 2, "convenience": 4,
            }
        }
    )

    prep: list[str] = Field(default_factory=list, description="조리법")
    purpose: list[str] = Field(default_factory=list, description="식사 목적")
    season_weight: float = Field(0.7, ge=0, le=1, description="계절감을 얼마나 중시할지")
    freshness_weight: float = Field(0.5, ge=0, le=1, description="신선도를 얼마나 중시할지")
    difficulty: Optional[int] = Field(None, ge=1, le=5, description="원하는 난이도")
    convenience: Optional[int] = Field(None, ge=1, le=5, description="원하는 편의성")
    limit: int = Field(5, ge=1, le=12)


# ---------------------------------------------------------------- chat
class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "message": "요즘 제철 식재료 값이 어때?",
                "conversation_id": None,
                "use_tools": True,
            }
        }
    )

    message: str = Field(..., min_length=1, max_length=MAX_MESSAGE_LEN)
    conversation_id: Optional[str] = Field(
        None, description="이어서 대화할 기존 대화 ID. 없으면 새 대화를 만든다."
    )
    use_tools: bool = Field(
        True, description="보너스 기능: GPT 가 내부 API 를 도구로 직접 호출하게 할지 여부"
    )
    conditions: Optional[RecommendRequest] = Field(
        None, description="화면의 조건 손잡이. 주면 그 조건을 프롬프트에 함께 넣는다."
    )

    @field_validator("message")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("message 는 공백일 수 없습니다.")
        return v


class ToolCallTrace(BaseModel):
    """보너스: '어떤 근거로 어떤 도구를 호출했는지' 추적 기록"""

    name: str
    arguments: dict
    result_preview: str


class ChatResponse(BaseModel):
    conversation_id: str
    reply: str
    summary_used: SummaryOut
    tool_calls: list[ToolCallTrace] = Field(default_factory=list)

    # 이 대화에서 필요한 식재료. 화면이 이 품목을 시세판 맨 위로 올린다.
    mentioned_items: list[str] = Field(default_factory=list,
                                       description="대화에서 뽑아낸 품목")
    mention_reason: str = Field("", description="왜 그 품목이 뽑혔는지 (예: 김치찌개 → 배추, 대파)")


# ---------------------------------------------------------------- conversations
class ConversationCreate(BaseModel):
    title: Optional[str] = Field(None, max_length=120)
    messages: list[ChatMessage] = Field(..., min_length=1)


class ConversationSummaryOut(BaseModel):
    """목록 조회용. messages 는 포함하지 않는다 (요구사항 6-B 를 A 방식으로 보완)."""

    id: str
    title: str
    message_count: int
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    preview: str = ""


class ConversationDetailOut(ConversationSummaryOut):
    """단건 조회용. 전체 messages 를 포함한다 (요구사항 6-A)."""

    messages: list[ChatMessage] = Field(default_factory=list)


class ConversationListOut(BaseModel):
    count: int
    items: list[ConversationSummaryOut]


# ---------------------------------------------------------------- 공통
class MessageOut(BaseModel):
    ok: bool = True
    message: str
