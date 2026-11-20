"""
In-memory live multiplayer room session manager and WebSocket broadcaster.
"""
import asyncio
from dataclasses import dataclass, field
import secrets
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import WebSocket

from app.core.errors import api_error

BASE_POINTS = 1000
MAX_LATENCY_BONUS = 500


def normalize_room_pin(raw_pin: str) -> str:
    """Validate and normalize a 6-digit room PIN (accepts '482 619' or '482619')."""
    if not isinstance(raw_pin, str):
        raise api_error(400, "INVALID_ROOM_PIN", "Room PIN must be 6 digits.")
    digits = raw_pin.replace(" ", "").replace("-", "").strip()
    if len(digits) != 6 or not digits.isdigit():
        raise api_error(400, "INVALID_ROOM_PIN", "Room PIN must be 6 digits.")
    return digits


def format_room_pin(normalized_pin: str) -> str:
    """Format a 6-digit PIN as '123 456' to match the frontend contract."""
    return f"{normalized_pin[:3]} {normalized_pin[3:]}"


@dataclass
class LivePlayer:
    id: str
    name: str
    user_id: Optional[int] = None
    status: str = "Ready"
    correct: int = 0
    total: int = 0
    points: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "correct": self.correct,
            "total": self.total,
            "points": self.points,
        }


@dataclass
class LiveRoomSession:
    pin: str  # 6 normalized digits
    quiz_id: int
    host_id: int
    timer_seconds: int
    questions: List[Dict[str, Any]]  # Each has id, prompt, position, choices (with is_correct)
    status: str = "lobby"  # lobby | active | finished | closed
    round: int = 0  # 0 in lobby, 1..total_rounds when active
    players: Dict[str, LivePlayer] = field(default_factory=dict)
    connections: Set[WebSocket] = field(default_factory=set)
    round_started_at: Optional[float] = None
    round_deadline: Optional[float] = None
    round_answered_players: Set[str] = field(default_factory=set)
    timer_task: Optional[asyncio.Task] = None
    _player_seq: int = 0

    @property
    def total_rounds(self) -> int:
        return len(self.questions)

    def add_player(self, display_name: str, user_id: Optional[int] = None) -> LivePlayer:
        self._player_seq += 1
        player_id = f"player_{self._player_seq}"
        player = LivePlayer(id=player_id, name=display_name.strip(), user_id=user_id)
        self.players[player_id] = player
        return player

    def current_question_public(self) -> Optional[Dict[str, Any]]:
        """Return the active round's question without revealing is_correct."""
        if self.status != "active" or self.round < 1 or self.round > self.total_rounds:
            return None
        q = self.questions[self.round - 1]
        return {
            "id": q["id"],
            "prompt": q["prompt"],
            "position": q["position"],
            "choices": [
                {"id": c["id"], "text": c["text"], "position": c["position"]}
                for c in q["choices"]
            ],
        }

    def current_correct_choice_id(self) -> Optional[str]:
        if self.round < 1 or self.round > self.total_rounds:
            return None
        q = self.questions[self.round - 1]
        for c in q["choices"]:
            if c.get("is_correct"):
                return c["id"]
        return None

    def to_state_dict(self) -> Dict[str, Any]:
        sorted_players = sorted(
            self.players.values(),
            key=lambda p: (-p.points, -p.correct, p.id),
        )
        return {
            "pin": format_room_pin(self.pin),
            "quiz_id": f"quiz_{self.quiz_id}",
            "timer_seconds": self.timer_seconds,
            "round": self.round,
            "total_rounds": self.total_rounds,
            "status": self.status,
            "players": [p.to_dict() for p in sorted_players],
        }

    def cancel_timer(self) -> None:
        if self.timer_task and not self.timer_task.done():
            self.timer_task.cancel()
        self.timer_task = None

    def advance_round(self) -> Tuple[str, Optional[Dict[str, Any]]]:
        """Advance to the next round or finish the game."""
        self.cancel_timer()
        if self.round < self.total_rounds:
            self.round += 1
            self.status = "active"
            self.round_answered_players.clear()
            for p in self.players.values():
                p.status = "Ready"
            now = time.monotonic()
            self.round_started_at = now
            self.round_deadline = now + self.timer_seconds
            return self.status, self.current_question_public()

        self.status = "finished"
        self.round_started_at = None
        self.round_deadline = None
        return self.status, None

    def submit_answer(self, player_id: str, choice_id: str) -> Dict[str, Any]:
        """Grade a player's answer for the current round with latency bonus scoring."""
        if self.status != "active" or self.round < 1 or self.round > self.total_rounds:
            return {"error": "No active round."}

        player = self.players.get(player_id)
        if not player:
            return {"error": "Unknown player."}

        if player_id in self.round_answered_players:
            return {"error": "Already answered this round."}

        now = time.monotonic()
        if self.round_deadline is not None and now > self.round_deadline:
            return {"error": "Round timer has expired."}

        normalized_choice = (choice_id or "").strip().lower()
        q = self.questions[self.round - 1]
        valid_choice_ids = {c["id"] for c in q["choices"]}
        if normalized_choice not in valid_choice_ids:
            return {"error": f"Invalid choice '{choice_id}'."}

        self.round_answered_players.add(player_id)
        correct_id = self.current_correct_choice_id()
        is_correct = normalized_choice == correct_id

        points_earned = 0
        player.total += 1
        player.status = "Answered"
        if is_correct:
            player.correct += 1
            remaining = max(0.0, (self.round_deadline or now) - now)
            ratio = min(1.0, remaining / max(1, self.timer_seconds))
            points_earned = BASE_POINTS + int(MAX_LATENCY_BONUS * ratio)
            player.points += points_earned

        return {
            "player_id": player_id,
            "round": self.round,
            "is_correct": is_correct,
            "correct_choice_id": correct_id,
            "points_earned": points_earned,
            "total_points": player.points,
        }


class LiveRoomManager:
    """Manages active live rooms and WebSocket broadcasts."""

    def __init__(self) -> None:
        self._rooms: Dict[str, LiveRoomSession] = {}

    def reset(self) -> None:
        for room in self._rooms.values():
            room.cancel_timer()
        self._rooms.clear()

    def generate_unique_pin(self, existing_pins: Optional[Set[str]] = None) -> str:
        taken = set(self._rooms.keys())
        if existing_pins:
            taken |= existing_pins
        for _ in range(100):
            candidate = f"{secrets.randbelow(900000) + 100000}"
            if candidate not in taken:
                return candidate
        raise api_error(500, "SERVER_ERROR", "Unable to allocate a unique room PIN.")

    def create_session(
        self,
        pin: str,
        quiz_id: int,
        host_id: int,
        timer_seconds: int,
        questions: List[Dict[str, Any]],
    ) -> LiveRoomSession:
        session = LiveRoomSession(
            pin=pin,
            quiz_id=quiz_id,
            host_id=host_id,
            timer_seconds=timer_seconds,
            questions=questions,
        )
        self._rooms[pin] = session
        return session

    def get_session(self, pin: str) -> Optional[LiveRoomSession]:
        return self._rooms.get(pin)

    def remove_rooms_for_host(self, host_id: int) -> None:
        to_remove = [pin for pin, s in self._rooms.items() if s.host_id == host_id]
        for pin in to_remove:
            self._rooms[pin].cancel_timer()
            del self._rooms[pin]

    async def broadcast(self, session: LiveRoomSession, payload: Dict[str, Any]) -> None:
        dead: List[WebSocket] = []
        for ws in list(session.connections):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            session.connections.discard(ws)

    def schedule_round_timer(self, session: LiveRoomSession) -> None:
        """Start an asyncio timer that broadcasts round_ended when timer_seconds elapses."""
        current_round = session.round

        async def _expire_round():
            try:
                await asyncio.sleep(session.timer_seconds)
                if session.status == "active" and session.round == current_round:
                    await self.broadcast(
                        session,
                        {
                            "type": "round_ended",
                            "round": current_round,
                            "correct_choice_id": session.current_correct_choice_id(),
                            "state": session.to_state_dict(),
                        },
                    )
            except asyncio.CancelledError:
                return

        try:
            loop = asyncio.get_running_loop()
            session.timer_task = loop.create_task(_expire_round())
        except RuntimeError:
            # No running event loop (e.g., called outside async context)
            session.timer_task = None


live_room_manager = LiveRoomManager()
