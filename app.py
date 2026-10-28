"""Tiny Flask server for playing against the C++ engine.

Setup:
    g++ -O3 -march=native -std=c++20 game_board.cpp -o game_board      (game_board.exe on Windows)
    pip install flask
    python app.py            ->  http://127.0.0.1:5000

Set ENGINE_PATH to point at a differently named/located engine binary.
Set CHESS_STATE_PATH to a persistent SQLite file shared by all workers.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from flask import Flask, jsonify, request

HERE = Path(__file__).resolve().parent
ENGINE_PATH = os.environ.get("ENGINE_PATH") or str(
    HERE / ("game_board.exe" if os.name == "nt" else "game_board")
)

# Square index = row * 8 + col. Row 0 is White's back rank. Upper-case = White.
# Position state = "<board64> <side w|b> <castling rights KQkq|-> <en-passant square|->".
START = "RNBQKBNR" + "P" * 8 + "." * 32 + "p" * 8 + "rnbqkbnr" + " w KQkq -"


class EngineError(RuntimeError):
    pass


class Engine:
    """Persistent C++ engine process (keeps its transposition table between moves)."""

    def __init__(self, path: str):
        self.path = path
        self.proc: subprocess.Popen | None = None
        self.lock = threading.Lock()

    def _ensure(self) -> subprocess.Popen:
        if self.proc is None or self.proc.poll() is not None:
            if not Path(self.path).exists():
                raise EngineError(f"Engine binary not found: {self.path}")
            self.proc = subprocess.Popen(
                [self.path, "--serve"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        return self.proc

    def _ask(self, line: str) -> str:
        with self.lock:
            proc = self._ensure()
            try:
                proc.stdin.write(line + "\n")
                proc.stdin.flush()
                reply = proc.stdout.readline().strip()
            except (BrokenPipeError, OSError) as exc:
                self.proc = None
                raise EngineError("Engine process died") from exc
            if not reply:
                self.proc = None
                raise EngineError("Engine process died")
            if reply.startswith("error"):
                raise EngineError(reply)
            return reply

    def status(self, pos: str):
        """-> (white_in_check, black_in_check, moves for the side to move)."""
        parts = self._ask(f"status {pos}").split()
        moves = [(int(f), int(t), promo) for f, t, promo in (p.split(",") for p in parts[3:])]
        return parts[1] == "1", parts[2] == "1", moves

    def go(self, pos: str, seconds: float):
        parts = self._ask(f"go {pos} {seconds:.3f}").split()
        if parts[1] == "none":
            return None
        promotion = None if parts[5] == "-" else parts[5]
        return int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4]), promotion

    def apply(self, pos: str, f: int, t: int, promotion: str | None = None) -> str:
        """Let the engine apply a move, including special-move state updates."""
        return self._ask(f"apply {pos} {f} {t} {promotion or '-'}")[len("state "):]


engine = Engine(ENGINE_PATH)
app = Flask(__name__)
STATE_PATH = Path(
    os.environ.get("CHESS_STATE_PATH", HERE / "instance" / "chess.sqlite3")
).expanduser().resolve()
STATE_PATH.parent.mkdir(parents=True, exist_ok=True)

with sqlite3.connect(STATE_PATH, timeout=30) as connection:
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS game_state (id INTEGER PRIMARY KEY CHECK (id = 1), state TEXT NOT NULL)"
    )


@contextmanager
def locked_game() -> Iterator[dict]:
    """Load and save the singleton game while serializing updates across workers."""
    with sqlite3.connect(STATE_PATH, timeout=30) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT state FROM game_state WHERE id = 1").fetchone()
        state = json.loads(row[0]) if row else {}
        try:
            yield state
            if state:
                connection.execute(
                    "INSERT INTO game_state (id, state) VALUES (1, ?) "
                    "ON CONFLICT(id) DO UPDATE SET state = excluded.state",
                    (json.dumps(state),),
                )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise


def new_game(human: str, seconds: float) -> dict:
    return dict(pos=START, human=human, seconds=seconds, last=None, winner=None, ai=None)


def board_and_turn(state: dict) -> tuple[str, str]:
    board, turn = state["pos"].split()[:2]
    return board, turn


def play(state: dict, f: int, t: int, promotion: str | None = None) -> None:
    board, turn = board_and_turn(state)
    captured = board[t]
    state["pos"] = engine.apply(state["pos"], f, t, promotion)
    state["last"] = [f, t]
    if captured in "kK":
        state["winner"] = turn


def ai_move_if_needed(state: dict) -> None:
    _, turn = board_and_turn(state)
    if state["winner"] or turn == state["human"]:
        return
    result = engine.go(state["pos"], state["seconds"])
    if result is None:
        state["winner"] = "draw"
        return
    f, t, score, depth, promotion = result
    play(state, f, t, promotion)
    state["ai"] = {"from": f, "to": t, "score": score, "depth": depth}


def payload(state: dict) -> dict:
    board, turn = board_and_turn(state)
    white_check, black_check, moves = engine.status(state["pos"])
    if not state["winner"] and not moves:
        state["winner"] = "draw"  # side to move has no moves at all

    check = []
    if white_check and "K" in board:
        check.append(board.index("K"))
    if black_check and "k" in board:
        check.append(board.index("k"))

    human_to_move = turn == state["human"] and not state["winner"]
    return {
        "board": list(board),
        "turn": turn,
        "human": state["human"],
        "seconds": state["seconds"],
        "last": state["last"],
        "winner": state["winner"],
        "ai": state["ai"],
        "check": check,
        "legal": moves if human_to_move else [],
    }


@app.get("/")
def index():
    return (HERE / "index.html").read_text(encoding="utf-8")


@app.get("/api/state")
def api_state():
    with locked_game() as state:
        if not state:
            state.update(new_game("w", 1.0))
        return jsonify(payload(state))


@app.post("/api/new")
def api_new():
    data = request.get_json(force=True, silent=True) or {}
    human = "b" if data.get("side") == "black" else "w"
    try:
        seconds = requested_seconds(data, 1.0)
    except ValueError:
        return jsonify(error="invalid think time"), 400
    with locked_game() as state:
        state.clear()
        state.update(new_game(human, seconds))
        ai_move_if_needed(state)  # AI opens if the human chose Black
        return jsonify(payload(state))


def requested_seconds(data: dict, default: float) -> float:
    try:
        seconds = float(data.get("seconds", default))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid think time") from exc
    if not math.isfinite(seconds):
        raise ValueError("invalid think time")
    return min(max(seconds, 0.1), 900.0)


@app.post("/api/move")
def api_move():
    data = request.get_json(force=True, silent=True) or {}
    try:
        f, t = int(data["from"]), int(data["to"])
    except (KeyError, TypeError, ValueError):
        return jsonify(error="bad request"), 400
    with locked_game() as state:
        if not state or state["winner"] or board_and_turn(state)[1] != state["human"]:
            return jsonify(error="not your turn"), 409
        promotion = data.get("promotion", "-")
        if not isinstance(promotion, str) or promotion.lower() not in {"-", "q", "r", "b", "n"}:
            return jsonify(error="invalid promotion"), 400
        promotion = promotion.lower()
        if (f, t, promotion) not in engine.status(state["pos"])[2]:
            return jsonify(error="illegal move"), 400
        try:
            state["seconds"] = requested_seconds(data, state["seconds"])
        except ValueError:
            return jsonify(error="invalid think time"), 400
        play(state, f, t, None if promotion == "-" else promotion)
        ai_move_if_needed(state)
        return jsonify(payload(state))


@app.errorhandler(EngineError)
def engine_error(exc):
    return jsonify(error=str(exc)), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
