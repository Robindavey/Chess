"""Tiny Flask server for playing against the C++ engine.

Setup:
    g++ -O3 -march=native -std=c++20 game_board.cpp -o game_board      (game_board.exe on Windows)
    pip install flask
    python app.py            ->  http://127.0.0.1:5000

Set ENGINE_PATH to point at a differently named/located engine binary.
"""
from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path

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
        moves = [tuple(map(int, p.split(","))) for p in parts[3:]]
        return parts[1] == "1", parts[2] == "1", moves

    def go(self, pos: str, seconds: float):
        parts = self._ask(f"go {pos} {seconds:.3f}").split()
        if parts[1] == "none":
            return None
        return int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4])  # from, to, score, depth

    def apply(self, pos: str, f: int, t: int) -> str:
        """Let the engine apply a move (it handles castling, en passant and rights)."""
        return self._ask(f"apply {pos} {f} {t}")[len("state "):]


engine = Engine(ENGINE_PATH)
app = Flask(__name__)
game_lock = threading.Lock()
game: dict = {}


def new_game(human: str, seconds: float) -> None:
    game.clear()
    game.update(pos=START, human=human, seconds=seconds, last=None, winner=None, ai=None)


def board_and_turn() -> tuple[str, str]:
    board, turn = game["pos"].split()[:2]
    return board, turn


def play(f: int, t: int) -> None:
    board, turn = board_and_turn()
    captured = board[t]
    game["pos"] = engine.apply(game["pos"], f, t)
    game["last"] = [f, t]
    if captured in "kK":
        game["winner"] = turn


def ai_move_if_needed() -> None:
    _, turn = board_and_turn()
    if game["winner"] or turn == game["human"]:
        return
    result = engine.go(game["pos"], game["seconds"])
    if result is None:
        game["winner"] = "draw"
        return
    f, t, score, depth = result
    play(f, t)
    game["ai"] = {"from": f, "to": t, "score": score, "depth": depth}


def payload() -> dict:
    board, turn = board_and_turn()
    white_check, black_check, moves = engine.status(game["pos"])
    if not game["winner"] and not moves:
        game["winner"] = "draw"  # side to move has no moves at all

    check = []
    if white_check and "K" in board:
        check.append(board.index("K"))
    if black_check and "k" in board:
        check.append(board.index("k"))

    human_to_move = turn == game["human"] and not game["winner"]
    return {
        "board": list(board),
        "turn": turn,
        "human": game["human"],
        "seconds": game["seconds"],
        "last": game["last"],
        "winner": game["winner"],
        "ai": game["ai"],
        "check": check,
        "legal": moves if human_to_move else [],
    }


@app.get("/")
def index():
    return (HERE / "index.html").read_text(encoding="utf-8")


@app.get("/api/state")
def api_state():
    with game_lock:
        if not game:
            new_game("w", 1.0)
        return jsonify(payload())


@app.post("/api/new")
def api_new():
    data = request.get_json(force=True, silent=True) or {}
    human = "b" if data.get("side") == "black" else "w"
    seconds = min(max(float(data.get("seconds", 1.0)), 0.1), 30.0)
    with game_lock:
        new_game(human, seconds)
        ai_move_if_needed()  # AI opens if the human chose Black
        return jsonify(payload())


@app.post("/api/move")
def api_move():
    data = request.get_json(force=True, silent=True) or {}
    try:
        f, t = int(data["from"]), int(data["to"])
    except (KeyError, TypeError, ValueError):
        return jsonify(error="bad request"), 400
    with game_lock:
        if not game or game["winner"] or board_and_turn()[1] != game["human"]:
            return jsonify(error="not your turn"), 409
        if (f, t) not in engine.status(game["pos"])[2]:
            return jsonify(error="illegal move"), 400
        play(f, t)
        ai_move_if_needed()
        return jsonify(payload())


@app.errorhandler(EngineError)
def engine_error(exc):
    return jsonify(error=str(exc)), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
