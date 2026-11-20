"""
Tests verifying Phase 7: Live rooms (REST lifecycle + WebSocket gameplay & scoring).
"""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.rate_limit import rate_limiter
from app.core.security import create_access_token, hash_password
from app.db.models import Base, User
from app.db.session import SessionLocal, engine
from app.main import app
from app.services.live_manager import live_room_manager


@pytest.fixture(autouse=True)
def reset_db_and_rooms():
    rate_limiter.reset()
    live_room_manager.reset()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    live_room_manager.reset()
    Base.metadata.drop_all(bind=engine)


def _create_user(email: str, role: str = "user") -> User:
    db = SessionLocal()
    try:
        user = User(
            email=email,
            password_hash=hash_password("Password123"),
            display_name=email.split("@")[0],
            role=role,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def _sample_csv() -> bytes:
    return "\n".join(f'"Term{i}","Definition {i}"' for i in range(1, 11)).encode("utf-8")


def test_live_room_lifecycle_auth_and_websocket_scoring():
    host = _create_user("host@example.com")
    other = _create_user("other@example.com")

    with TestClient(app) as client_host:
        # Guest cannot create a live room
        g_create = client_host.post("/api/v1/live/rooms", json={"quiz_id": "quiz_1"})
        assert g_create.status_code == 401

        # Authenticate host and create a 5-question quiz
        client_host.cookies.set(
            settings.ACCESS_COOKIE_NAME, create_access_token(host.id, host.role)
        )
        q_resp = client_host.post(
            "/api/v1/quizzes",
            files={"file": ("live.csv", _sample_csv(), "text/csv")},
            data={"title": "Live Quiz", "question_count": "5"},
        )
        assert q_resp.status_code == 201
        quiz_id = q_resp.json()["id"]

        preview = client_host.get(f"/api/v1/quizzes/{quiz_id}/preview").json()
        first_correct_letter = next(
            c["id"] for c in preview["questions"][0]["choices"] if c["is_correct"]
        )
        first_wrong_letter = next(
            c["id"] for c in preview["questions"][0]["choices"] if not c["is_correct"]
        )

        # Create live room
        room_resp = client_host.post(
            "/api/v1/live/rooms",
            json={"quiz_id": quiz_id, "timer_seconds": 20},
        )
        assert room_resp.status_code == 201
        room = room_resp.json()
        assert room["quiz_id"] == quiz_id
        assert room["timer_seconds"] == 20
        assert room["round"] == 0
        assert room["total_rounds"] == 5
        assert room["status"] == "lobby"
        assert room["players"] == []
        formatted_pin = room["pin"]
        raw_pin = formatted_pin.replace(" ", "")
        assert len(raw_pin) == 6 and raw_pin.isdigit()

        # Invalid PIN -> 400 INVALID_ROOM_PIN; unknown PIN -> 404 ROOM_NOT_FOUND
        with TestClient(app) as guest:
            bad_pin = guest.post("/api/v1/live/rooms/abc/join", json={"display_name": "Maya"})
            assert bad_pin.status_code == 400
            assert bad_pin.json()["detail"]["code"] == "INVALID_ROOM_PIN"

            missing_pin = guest.post("/api/v1/live/rooms/000000/join", json={"display_name": "Maya"})
            assert missing_pin.status_code == 404
            assert missing_pin.json()["detail"]["code"] == "ROOM_NOT_FOUND"

            # Guest joins using formatted or raw PIN
            join_1 = guest.post(
                f"/api/v1/live/rooms/{raw_pin}/join",
                json={"display_name": "Maya"},
            )
            assert join_1.status_code == 200
            p1 = join_1.json()
            assert p1["player_id"] == "player_1"
            assert len(p1["players"]) == 1
            assert p1["players"][0]["name"] == "Maya"

            join_2 = guest.post(
                f"/api/v1/live/rooms/{formatted_pin}/join",
                json={"display_name": "Alex"},
            )
            assert join_2.status_code == 200
            p2 = join_2.json()
            assert p2["player_id"] == "player_2"

        # Non-host cannot advance round
        with TestClient(app) as client_other:
            client_other.cookies.set(
                settings.ACCESS_COOKIE_NAME, create_access_token(other.id, other.role)
            )
            forbidden_next = client_other.post(f"/api/v1/live/rooms/{raw_pin}/next")
            assert forbidden_next.status_code == 403

        # Connect WebSocket for player_1 and advance round 1
        with client_host.websocket_connect(
            f"/api/v1/live/rooms/{raw_pin}/ws?player_id=player_1"
        ) as ws:
            init_msg = ws.receive_json()
            assert init_msg["type"] == "room_state"
            assert init_msg["state"]["status"] == "lobby"
            assert len(init_msg["state"]["players"]) == 2

            # Host advances to Round 1
            next_1 = client_host.post(f"/api/v1/live/rooms/{raw_pin}/next")
            assert next_1.status_code == 200
            next_data = next_1.json()
            assert next_data["status"] == "active"
            assert next_data["round"] == 1
            assert "is_correct" not in next_data["current_question"]["choices"][0]

            # WebSocket receives the broadcast question event
            q_msg = ws.receive_json()
            assert q_msg["type"] == "question"
            assert q_msg["round"] == 1
            assert "is_correct" not in q_msg["question"]["choices"][0]

            # Player 1 submits correct answer -> receives answer_result + leaderboard broadcast
            ws.send_json({"type": "answer", "player_id": "player_1", "choice_id": first_correct_letter})
            ans_res = ws.receive_json()
            assert ans_res["type"] == "answer_result"
            assert ans_res["is_correct"] is True
            assert ans_res["points_earned"] >= 1000

            lb_msg = ws.receive_json()
            assert lb_msg["type"] == "leaderboard"
            assert lb_msg["state"]["players"][0]["id"] == "player_1"
            assert lb_msg["state"]["players"][0]["points"] >= 1000
            assert lb_msg["state"]["players"][0]["correct"] == 1

            # Player 2 submits wrong answer -> 0 points, player_1 stays #1
            ws.send_json({"type": "answer", "player_id": "player_2", "choice_id": first_wrong_letter})
            ans_res_2 = ws.receive_json()
            assert ans_res_2["type"] == "answer_result"
            assert ans_res_2["is_correct"] is False
            assert ans_res_2["points_earned"] == 0

            lb_msg_2 = ws.receive_json()
            assert lb_msg_2["type"] == "leaderboard"
            assert lb_msg_2["state"]["players"][0]["id"] == "player_1"
            assert lb_msg_2["state"]["players"][1]["id"] == "player_2"
            assert lb_msg_2["state"]["players"][1]["points"] == 0

            # Duplicate answer in same round is rejected
            ws.send_json({"type": "answer", "player_id": "player_1", "choice_id": first_correct_letter})
            dup_err = ws.receive_json()
            assert dup_err["type"] == "error"

        # Advance through remaining rounds until finished
        for expected_round in range(2, 6):
            r = client_host.post(f"/api/v1/live/rooms/{raw_pin}/next")
            assert r.status_code == 200
            assert r.json()["round"] == expected_round
            assert r.json()["status"] == "active"

        fin = client_host.post(f"/api/v1/live/rooms/{raw_pin}/next")
        assert fin.status_code == 200
        assert fin.json()["status"] == "finished"
        assert fin.json()["current_question"] is None
