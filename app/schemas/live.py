"""
Pydantic schemas for live multiplayer rooms (Phase 7).
"""
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class LiveRoomCreate(BaseModel):
    quiz_id: str
    timer_seconds: int = Field(default=20, ge=5, le=120)


class LiveRoomJoin(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=100)


class LivePlayerState(BaseModel):
    id: str
    name: str
    avatar_url: Optional[str] = None
    status: str  # "Waiting" | "Ready" | "Answered"
    correct: int
    total: int
    points: int


class LiveChoicePayload(BaseModel):
    id: str
    text: str
    position: int


class LiveQuestionPayload(BaseModel):
    id: str
    prompt: str
    position: int
    choices: List[LiveChoicePayload]


class LiveGameState(BaseModel):
    pin: str
    quiz_id: str
    timer_seconds: int
    round: int
    total_rounds: int
    status: str  # "lobby" | "active" | "finished" | "closed"
    players: List[LivePlayerState]


class LiveJoinResponse(LiveGameState):
    player_id: str


class LiveNextResponse(LiveGameState):
    current_question: Optional[LiveQuestionPayload] = None


class LiveHistoryPlayer(BaseModel):
    name: str
    correct: int
    total: int
    points: int
    is_me: bool = False


class LiveRoomHistoryItem(BaseModel):
    id: str
    pin: str
    quiz_id: str
    quiz_title: str
    timer_seconds: int
    total_rounds: int
    status: str
    role: str  # "host" | "player"
    player_count: int
    winner_name: Optional[str] = None
    winner_points: int = 0
    my_points: Optional[int] = None
    my_correct: Optional[int] = None
    my_total: Optional[int] = None
    my_rank: Optional[int] = None
    players: List[LiveHistoryPlayer] = Field(default_factory=list)
    created_at: datetime
    finished_at: Optional[datetime] = None
