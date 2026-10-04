from __future__ import annotations

from enum import StrEnum
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
            raise ValueError("Unknown observations must have zero confidence")
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


class PlayerState(Model):
    lp: Observation[int] = Field(default_factory=Observation[int])
    hand_count: Observation[int] = Field(default_factory=Observation[int])
    # Empty dictionary means zones were not configured, not an empty board.
    zones: dict[str, Observation[CardIdentity]] = Field(default_factory=dict)


class Action(Model):
    type: ActionType
    card_id: str | None = None
    target: str | None = None
    confidence: float = Field(ge=0, le=1)
    source_region: str
    observed_at: float = Field(ge=0)


class GameState(Model):
    sequence: int = Field(ge=0)
    captured_at: float = Field(ge=0)
    media_time: float | None = Field(default=None, ge=0)
    turn: Observation[int] = Field(default_factory=Observation[int])
    turn_player: Observation[Player] = Field(default_factory=Observation[Player])
    phase: Observation[Phase] = Field(default_factory=Observation[Phase])
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
    """Future authorized applications only. No implementation in this project."""

    def execute(self, action: Action) -> None: ...
