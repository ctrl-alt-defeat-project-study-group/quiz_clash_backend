"""
API routes and WebSocket handler for live multiplayer rooms (Phase 7).
"""
from datetime import datetime, timezone
import json
import time
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session, selectinload

from app.core.deps import ensure_owner_or_admin, get_current_user, get_optional_user
from app.core.errors import api_error
from app.core.ids import parse_prefixed_id
from app.db.models import Attempt, AttemptAnswer, LiveRoom, Question, Quiz, User
from app.db.session import SessionLocal, get_db
from app.schemas.live import (
    LiveGameState,
    LiveJoinResponse,
    LiveNextResponse,
    LiveRoomCreate,
    LiveRoomHistoryItem,
    LiveRoomJoin,
)
from app.services.live_manager import (
    LiveRoomSession,
    format_room_pin,
    live_room_manager,
    normalize_room_pin,
)

router = APIRouter()


def _serialize_quiz_questions(db_quiz: Quiz) -> List[Dict[str, Any]]:
    sorted_questions = sorted(db_quiz.questions, key=lambda q: q.position)
    questions_payload: List[Dict[str, Any]] = []
    for q in sorted_questions:
        sorted_choices = sorted(q.choices, key=lambda c: c.position)
        choices = [
            {
                "id": chr(97 + idx),
                "db_id": c.id,
                "text": c.text,
                "position": idx,
                "is_correct": c.is_correct,
            }
            for idx, c in enumerate(sorted_choices)
        ]
        questions_payload.append(
            {
                "id": f"q_{q.id}",
                "db_id": q.id,
                "prompt": q.prompt,
                "position": q.position,
                "choices": choices,
            }
        )
    return questions_payload


def _get_or_restore_session(pin: str, db: Session) -> LiveRoomSession:
    """Lookup live room session in memory, or restore from DB if present."""
    session = live_room_manager.get_session(pin)
    if session is not None:
        return session

    db_room = (
        db.query(LiveRoom)
        .filter(LiveRoom.pin == pin)
        .first()
    )
    if not db_room:
        raise api_error(404, "ROOM_NOT_FOUND", "No active live game room matches that PIN.")

    db_quiz = (
        db.query(Quiz)
        .options(selectinload(Quiz.questions).selectinload(Question.choices))
        .filter(Quiz.id == db_room.quiz_id)
        .first()
    )
    if not db_quiz:
        raise api_error(404, "ROOM_NOT_FOUND", "No active live game room matches that PIN.")

    session = live_room_manager.create_session(
        pin=db_room.pin,
        quiz_id=db_room.quiz_id,
        host_id=db_room.host_id,
        timer_seconds=db_room.timer_seconds,
        questions=_serialize_quiz_questions(db_quiz),
    )
    session.status = db_room.status
    return session


@router.post("/live/rooms", response_model=LiveGameState, status_code=201)
def create_live_room(
    payload: LiveRoomCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a live multiplayer room for a quiz (authenticated host only)."""
    quiz_numeric_id = parse_prefixed_id(
        payload.quiz_id,
        "quiz",
        status_code=404,
        detail="Quiz not found.",
        code="QUIZ_NOT_FOUND",
    )

    db_quiz = (
        db.query(Quiz)
        .options(selectinload(Quiz.questions).selectinload(Question.choices))
        .filter(Quiz.id == quiz_numeric_id)
        .first()
    )
    if not db_quiz:
        raise api_error(404, "QUIZ_NOT_FOUND", "Quiz not found.")

    ensure_owner_or_admin(db_quiz.owner_id, current_user)

    questions = _serialize_quiz_questions(db_quiz)
    if not questions:
        raise api_error(400, "VALIDATION_ERROR", "Quiz has no questions.")

    existing_pins = {row[0] for row in db.query(LiveRoom.pin).all()}
    pin = live_room_manager.generate_unique_pin(
        existing_pins=existing_pins,
        account_email=current_user.email,
        topic=db_quiz.category or db_quiz.title,
    )

    db_room = LiveRoom(
        quiz_id=db_quiz.id,
        host_id=current_user.id,
        pin=pin,
        timer_seconds=payload.timer_seconds,
        status="lobby",
    )
    db.add(db_room)
    db.commit()

    session = live_room_manager.create_session(
        pin=pin,
        quiz_id=db_quiz.id,
        host_id=current_user.id,
        timer_seconds=payload.timer_seconds,
        questions=questions,
    )
    return session.to_state_dict()


@router.get("/live/rooms/{pin}", response_model=LiveGameState)
def get_live_room(
    pin: str,
    db: Session = Depends(get_db),
):
    """Get current live room state by PIN."""
    normalized_pin = normalize_room_pin(pin)
    session = _get_or_restore_session(normalized_pin, db)
    return session.to_state_dict()


@router.post("/live/rooms/{pin}/join", response_model=LiveJoinResponse)
async def join_live_room(
    pin: str,
    payload: LiveRoomJoin,
    current_user: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Join a live room by PIN. Guests are allowed by supplying display_name."""
    normalized_pin = normalize_room_pin(pin)
    session = _get_or_restore_session(normalized_pin, db)

    if session.status in ("finished", "closed"):
        raise api_error(404, "ROOM_NOT_FOUND", "This live room has already ended.")

    display_name = (payload.display_name or "").strip()
    if not display_name and current_user is not None:
        display_name = current_user.display_name.strip()
    if not display_name:
        raise api_error(422, "VALIDATION_ERROR", "display_name is required to join a live room.")

    player = session.add_player(
        display_name=display_name,
        user_id=current_user.id if current_user else None,
        avatar_url=current_user.avatar_url if current_user else None,
    )
    state = session.to_state_dict()

    await live_room_manager.broadcast(
        session,
        {"type": "player_joined", "player": player.to_dict(), "state": state},
    )

    return {**state, "player_id": player.id}


@router.post("/live/rooms/{pin}/players/{player_id}/ready", response_model=LiveGameState)
async def mark_live_player_ready(
    pin: str,
    player_id: str,
    db: Session = Depends(get_db),
):
    """Mark a player as Ready when they click 'Enter live game'."""
    normalized_pin = normalize_room_pin(pin)
    session = _get_or_restore_session(normalized_pin, db)

    player = session.mark_player_ready(player_id)
    if player is None:
        raise api_error(404, "PLAYER_NOT_FOUND", "Player not found in this live room.")

    state = session.to_state_dict()
    await live_room_manager.broadcast(
        session,
        {"type": "player_ready", "player_id": player_id, "state": state},
    )
    return state


@router.delete("/live/rooms/{pin}/players/{player_id}", response_model=LiveGameState)
async def leave_live_room_player(
    pin: str,
    player_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove a player from a live room (e.g. host opting out of participating before start)."""
    normalized_pin = normalize_room_pin(pin)
    session = _get_or_restore_session(normalized_pin, db)

    target = session.players.get(player_id)
    if target is None:
        return session.to_state_dict()

    is_host_or_admin = (
        current_user.role == "admin" or session.host_id == current_user.id
    )
    is_self = target.user_id is not None and target.user_id == current_user.id
    if not (is_host_or_admin or is_self):
        raise api_error(403, "FORBIDDEN", "Not allowed to remove this player.")

    session.remove_player(player_id)
    state = session.to_state_dict()

    await live_room_manager.broadcast(
        session,
        {"type": "player_left", "player_id": player_id, "state": state},
    )
    return state


@router.delete("/live/rooms/{pin}")
async def close_live_room(
    pin: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Close an active/lobby room. Unfinished rooms are deleted; finished rooms remain for history."""
    normalized_pin = normalize_room_pin(pin)
    db_room = db.query(LiveRoom).filter(LiveRoom.pin == normalized_pin).first()
    if db_room is not None:
        ensure_owner_or_admin(db_room.host_id, current_user)
        if db_room.status != "finished":
            db.delete(db_room)
            db.commit()

    session = live_room_manager.get_session(normalized_pin)
    if session is not None:
        await live_room_manager.broadcast(
            session,
            {"type": "room_closed", "pin": format_room_pin(normalized_pin)},
        )
    live_room_manager.remove_session(normalized_pin)
    return {"message": "Room closed."}


@router.get("/live/history", response_model=List[LiveRoomHistoryItem])
def list_live_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List finished live game rooms hosted or played by the authenticated user."""
    rooms = (
        db.query(LiveRoom)
        .options(selectinload(LiveRoom.quiz))
        .filter(LiveRoom.status == "finished")
        .order_by(LiveRoom.finished_at.desc(), LiveRoom.created_at.desc(), LiveRoom.id.desc())
        .all()
    )

    items: List[Dict[str, Any]] = []
    for room in rooms:
        summary: Dict[str, Any] = {}
        if room.results_json:
            try:
                summary = json.loads(room.results_json)
            except Exception:
                summary = {}

        participant_ids = summary.get("participant_user_ids") or []
        is_host = room.host_id == current_user.id
        is_participant = current_user.id in participant_ids
        if not is_host and not is_participant:
            continue

        raw_players = summary.get("players") or []
        players_out = []
        my_points = None
        my_correct = None
        my_total = None
        my_rank = None

        for rank_idx, p in enumerate(raw_players, start=1):
            p_uid = p.get("user_id")
            is_me = p_uid is not None and p_uid == current_user.id
            if is_me and my_rank is None:
                my_rank = rank_idx
                my_points = int(p.get("points") or 0)
                my_correct = int(p.get("correct") or 0)
                my_total = int(p.get("total") or 0)
            players_out.append(
                {
                    "name": p.get("name") or "Player",
                    "correct": int(p.get("correct") or 0),
                    "total": int(p.get("total") or 0),
                    "points": int(p.get("points") or 0),
                    "is_me": is_me,
                }
            )

        items.append(
            {
                "id": f"room_{room.id}",
                "pin": format_room_pin(room.pin),
                "quiz_id": f"quiz_{room.quiz_id}",
                "quiz_title": room.quiz.title if room.quiz else "Untitled Quiz",
                "timer_seconds": room.timer_seconds,
                "total_rounds": int(summary.get("total_rounds") or 0),
                "status": room.status,
                "role": "host" if is_host else "player",
                "player_count": int(summary.get("player_count") or len(players_out)),
                "winner_name": summary.get("winner_name"),
                "winner_points": int(summary.get("winner_points") or 0),
                "my_points": my_points,
                "my_correct": my_correct,
                "my_total": my_total,
                "my_rank": my_rank,
                "players": players_out,
                "created_at": room.created_at,
                "finished_at": room.finished_at or room.created_at,
            }
        )

    return items


@router.delete("/live/history/{room_id}")
def delete_live_history_room(
    room_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a finished live room from history (host or admin only)."""
    numeric_id = parse_prefixed_id(
        room_id,
        "room",
        status_code=404,
        detail="Live room not found.",
        code="ROOM_NOT_FOUND",
    )
    db_room = db.query(LiveRoom).filter(LiveRoom.id == numeric_id).first()
    if not db_room:
        raise api_error(404, "ROOM_NOT_FOUND", "Live room not found.")

    ensure_owner_or_admin(db_room.host_id, current_user)
    db.delete(db_room)
    db.commit()
    return {"message": "Live game history entry deleted."}


@router.post("/live/rooms/{pin}/next", response_model=LiveNextResponse)
async def advance_live_room(
    pin: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Advance to the next round and broadcast the next question (host or admin only)."""
    normalized_pin = normalize_room_pin(pin)
    session = _get_or_restore_session(normalized_pin, db)

    ensure_owner_or_admin(session.host_id, current_user)

    was_already_finished = session.status == "finished"
    new_status, question = session.advance_round()

    # Persist room status transition (and finished summary + logged-in attempts)
    db_room = db.query(LiveRoom).filter(LiveRoom.pin == normalized_pin).first()
    if db_room:
        db_room.status = new_status
        if new_status == "finished" and not was_already_finished:
            elapsed_seconds = (
                max(1, int(round(time.monotonic() - session.game_started_at)))
                if session.game_started_at is not None
                else session.total_rounds * session.timer_seconds
            )
            sorted_players = sorted(
                session.players.values(),
                key=lambda p: (-p.points, -p.correct, p.id),
            )
            winner = sorted_players[0] if sorted_players else None
            participant_user_ids = sorted(
                {p.user_id for p in sorted_players if p.user_id is not None}
            )
            db_room.finished_at = datetime.now(timezone.utc)
            db_room.results_json = json.dumps(
                {
                    "total_rounds": session.total_rounds,
                    "duration_seconds": elapsed_seconds,
                    "player_count": len(sorted_players),
                    "winner_name": winner.name if winner else None,
                    "winner_points": winner.points if winner else 0,
                    "participant_user_ids": participant_user_ids,
                    "players": [
                        {
                            "name": p.name,
                            "user_id": p.user_id,
                            "correct": p.correct,
                            "total": p.total,
                            "points": p.points,
                        }
                        for p in sorted_players
                    ],
                }
            )

            # Persist Attempt + AttemptAnswer records for logged-in participants only
            for p in sorted_players:
                if p.user_id is None:
                    continue
                db_attempt = Attempt(
                    quiz_id=session.quiz_id,
                    user_id=p.user_id,
                    score=p.correct,
                    total_questions=session.total_rounds,
                    duration_seconds=elapsed_seconds,
                )
                db.add(db_attempt)
                db.flush()
                for ans in p.answers:
                    db.add(
                        AttemptAnswer(
                            attempt_id=db_attempt.id,
                            question_id=ans["question_db_id"],
                            choice_id=ans["choice_db_id"],
                            is_correct=ans["is_correct"],
                        )
                    )
        db.commit()

    state = session.to_state_dict()

    if new_status == "active" and question is not None:
        live_room_manager.schedule_round_timer(session)
        await live_room_manager.broadcast(
            session,
            {
                "type": "question",
                "round": session.round,
                "total_rounds": session.total_rounds,
                "timer_seconds": session.timer_seconds,
                "question": question,
                "state": state,
            },
        )
    else:
        await live_room_manager.broadcast(
            session,
            {"type": "game_finished", "state": state},
        )

    return {**state, "current_question": question}


@router.websocket("/live/rooms/{pin}/ws")
async def live_room_websocket(
    websocket: WebSocket,
    pin: str,
    player_id: Optional[str] = None,
    display_name: Optional[str] = None,
):
    """
    Real-time WebSocket for live room lobby, question rounds, answer submission,
    latency scoring, and leaderboard broadcasts.
    """
    await websocket.accept()

    try:
        normalized_pin = normalize_room_pin(pin)
    except Exception:
        await websocket.send_json(
            {"type": "error", "code": "INVALID_ROOM_PIN", "message": "Room PIN must be 6 digits."}
        )
        await websocket.close(code=4400)
        return

    session = live_room_manager.get_session(normalized_pin)
    if session is None:
        db = SessionLocal()
        try:
            session = _get_or_restore_session(normalized_pin, db)
        except Exception:
            await websocket.send_json(
                {"type": "error", "code": "ROOM_NOT_FOUND", "message": "Live room not found."}
            )
            await websocket.close(code=4404)
            return
        finally:
            db.close()

    session.connections.add(websocket)
    bound_player_id = player_id

    try:
        # Optional auto-join if display_name query param was supplied
        if not bound_player_id and display_name and display_name.strip():
            player = session.add_player(display_name=display_name.strip())
            bound_player_id = player.id
            await live_room_manager.broadcast(
                session,
                {
                    "type": "player_joined",
                    "player": player.to_dict(),
                    "state": session.to_state_dict(),
                },
            )

        # Send initial room state snapshot to this connection
        init_payload: Dict[str, Any] = {
            "type": "room_state",
            "state": session.to_state_dict(),
        }
        if bound_player_id:
            init_payload["player_id"] = bound_player_id
        current_q = session.current_question_public()
        if current_q is not None:
            init_payload["question"] = current_q
        await websocket.send_json(init_payload)

        while True:
            data = await websocket.receive_json()
            msg_type = (data.get("type") or "").strip().lower()

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            if msg_type == "join":
                name = (data.get("display_name") or "").strip()
                if not name:
                    await websocket.send_json(
                        {"type": "error", "code": "VALIDATION_ERROR", "message": "display_name is required."}
                    )
                    continue
                player = session.add_player(display_name=name)
                bound_player_id = player.id
                await websocket.send_json(
                    {"type": "joined", "player_id": player.id, "state": session.to_state_dict()}
                )
                await live_room_manager.broadcast(
                    session,
                    {
                        "type": "player_joined",
                        "player": player.to_dict(),
                        "state": session.to_state_dict(),
                    },
                )
                continue

            if msg_type == "answer":
                pid = data.get("player_id") or bound_player_id
                choice_id = data.get("choice_id", "")
                if not pid:
                    await websocket.send_json(
                        {"type": "error", "code": "VALIDATION_ERROR", "message": "player_id is required."}
                    )
                    continue

                result = session.submit_answer(pid, choice_id)
                if "error" in result:
                    await websocket.send_json(
                        {"type": "error", "code": "VALIDATION_ERROR", "message": result["error"]}
                    )
                    continue

                await websocket.send_json({"type": "answer_result", **result})
                await live_room_manager.broadcast(
                    session,
                    {"type": "leaderboard", "state": session.to_state_dict()},
                )
                continue

            await websocket.send_json(
                {"type": "error", "code": "VALIDATION_ERROR", "message": f"Unsupported message type: {msg_type}"}
            )
    except WebSocketDisconnect:
        pass
    finally:
        session.connections.discard(websocket)
