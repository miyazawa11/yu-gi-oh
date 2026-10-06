from __future__ import annotations

from enum import StrEnum
from typing import Generic, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

T = TypeVar("T")


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Observation(Model, Generic[T]):
    value: T | None = None
    confidence: float = Field(default=0, ge=0, le=1)
    source: str = "unknown"
    observed_at: float = Field(default=0, ge=0)

    @model_validator(mode="after")
    def unknown_has_no_confidence(self):
        if self.value is None and self.confidence != 0:
            raise ValueError("未知の観測は信頼度をゼロにしてください")
        return self


class Phase(StrEnum):
    DRAW = "DRAW"
    STANDBY = "STANDBY"
    MAIN1 = "MAIN1"
    BATTLE = "BATTLE"
    MAIN2 = "MAIN2"
    END = "END"


class Player(StrEnum):
    SELF = "self"
    OPPONENT = "opponent"


class ActionType(StrEnum):
    NORMAL_SUMMON = "NORMAL_SUMMON"
    SPECIAL_SUMMON = "SPECIAL_SUMMON"
    ACTIVATE = "ACTIVATE"
    SET = "SET"
    ATTACK = "ATTACK"
    CHANGE_PHASE = "CHANGE_PHASE"
    SELECT_CARD = "SELECT_CARD"
    SELECT_TARGET = "SELECT_TARGET"
    CONFIRM = "CONFIRM"
    CANCEL = "CANCEL"


class CardIdentity(Model):
    card_id: str
    name: str | None = None
    card_type: str | None = None


class PlayerState(Model):
    lp: Observation[int] = Field(default_factory=Observation[int])
    hand_count: Observation[int] = Field(default_factory=Observation[int])
    # 空の辞書はゾーン未設定を意味し、空の盤面ではありません。
    zones: dict[str, Observation[CardIdentity]] = Field(default_factory=dict)


class UiCoordinateProof(Model):
    """限定profileが同一取得画像へ結び付けた候補位置。汎用入力許可ではありません。"""
    frame_seq: StrictInt = Field(ge=0)
    observed_at: float = Field(gt=0)
    client_rect: tuple[StrictInt, StrictInt, StrictInt, StrictInt]
    evidence_bbox: tuple[StrictInt, StrictInt, StrictInt, StrictInt]
    score: float = Field(ge=.98, le=1)
    position_margin: float = Field(ge=.03, le=1)
    detector_sha256: str
    profile_sha256: str
    profile_id: str
    scope: Literal["normal_inspect_confirmation"] = "normal_inspect_confirmation"
    action_type: Literal["NORMAL_SUMMON"] = "NORMAL_SUMMON"


class HandSearchCoordinateProof(Model):
    """公開UIで確定した手札操作専用。既存NORMAL座標証拠を流用しません。"""
    scope: Literal["hand_search_confirmation"] = "hand_search_confirmation"
    action_type: Literal["ACTIVATE", "SELECT_CARD"]
    layout_id: Literal["hand6-slot3", "hand7-slot3"]
    frame_seq: StrictInt = Field(ge=0)
    observed_at: float = Field(gt=0)
    client_rect: tuple[StrictInt,StrictInt,StrictInt,StrictInt]
    evidence_bbox: tuple[StrictInt,StrictInt,StrictInt,StrictInt]
    point: tuple[StrictInt,StrictInt]
    profile_sha256: str


class Action(Model):
    type: ActionType
    card_id: str | None = None
    target: str | None = None
    confidence: float = Field(ge=0, le=1)
    source_region: str
    observed_at: float = Field(ge=0)
    coordinate_proof: UiCoordinateProof | None = Field(default=None, exclude_if=lambda value: value is None)
    hand_search_proof: HandSearchCoordinateProof | None = Field(default=None, exclude_if=lambda value: value is None)


class Material(Model):
    instance: str
    card_id: str
    name: str
    race: str
    effect: bool
    fusion: bool = False
    token: bool = False
    face_up: bool = True
    level: int | None = None
    link: int = Field(default=0, ge=0, le=6)
    zone: str = "field"
    thunder_dragon: bool = False
    gouki: bool = False


class GameState(Model):
    sequence: int = Field(ge=0)
    captured_at: float = Field(ge=0)
    media_time: float | None = Field(default=None, ge=0)
    turn: Observation[int] = Field(default_factory=Observation[int])
    turn_player: Observation[Player] = Field(default_factory=Observation[Player])
    phase: Observation[Phase] = Field(default_factory=Observation[Phase])
    terminal: Observation[bool] = Field(default_factory=Observation[bool])
    prompt: Observation[str] = Field(default_factory=Observation[str])
    animation: Observation[bool] = Field(default_factory=Observation[bool])
    card_states: dict[str, Observation[str]] = Field(default_factory=dict)
    # 校正済み表示または検証済み履歴が根拠。未観測を false/未使用で補いません。
    facts: dict[str, Observation[str]] = Field(default_factory=dict)
    # 方法名→検証対象の素材個体集合。画像からまだ特定できない時は空のまま。
    material_sets: dict[str, Observation[list[Material]]] = Field(default_factory=dict)
    self: PlayerState = Field(default_factory=PlayerState)
    opponent: PlayerState = Field(default_factory=PlayerState)
    visible_actions: list[Action] = Field(default_factory=list)


class Event(Model):
    timestamp: float
    event: str
    path: str
    before: object
    after: object
    confidence: float = Field(ge=0, le=1)


class Recommendation(Model):
    action: Action | None = None
    target: str | None = None
    confidence: float = Field(default=0, ge=0, le=1)
    reason: str
    recognition_status: str


class ActionExecutor(Protocol):
    """判断層と実行層を分離する操作インターフェースです。"""

    def execute(self, action: Action) -> None: ...
