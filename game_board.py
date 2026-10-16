from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

WHITE = 1
BLACK = -1
BOARD_SIZE = 8
MAX_INT = 1_000_000

PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING = range(6)
PIECE_VALUES = (1, 3, 3, 5, 9, MAX_INT)
PIECE_SYMBOLS = ("p", "KT", "B", "R", "Q", "K")

# The original positional values and material weights are retained unchanged.
gridded = [
    [-0.50, -0.40, -0.30, -0.30, -0.30, -0.30, -0.40, -0.50],
    [-0.40, -0.20, 0.00, 0.05, 0.05, 0.00, -0.20, -0.40],
    [-0.30, 0.05, 0.10, 0.15, 0.15, 0.10, 0.05, -0.30],
    [-0.30, 0.00, 0.15, 0.20, 0.20, 0.15, 0.00, -0.30],
    [-0.30, 0.05, 0.15, 0.20, 0.20, 0.15, 0.05, -0.30],
    [-0.30, 0.00, 0.10, 0.15, 0.15, 0.10, 0.00, -0.30],
    [-0.40, -0.20, 0.00, 0.00, 0.00, 0.00, -0.20, -0.40],
    [-0.50, -0.40, -0.30, -0.30, -0.30, -0.30, -0.40, -0.50],
]

KNIGHT_STEPS = (
    (-2, -1), (-2, 1), (-1, -2), (-1, 2),
    (1, -2), (1, 2), (2, -1), (2, 1),
)
KING_STEPS = (
    (-1, -1), (-1, 0), (-1, 1), (0, -1),
    (0, 1), (1, -1), (1, 0), (1, 1),
)
ROOK_DIRECTIONS = ((-1, 0), (1, 0), (0, -1), (0, 1))
BISHOP_DIRECTIONS = ((-1, -1), (-1, 1), (1, -1), (1, 1))


def square_index(row: int, column: int) -> int:
    return row * BOARD_SIZE + column


def iter_bits(bitboard: int):
    while bitboard:
        bit = bitboard & -bitboard
        yield bit.bit_length() - 1
        bitboard ^= bit


@dataclass(frozen=True, slots=True)
class Move:
    from_square: int
    to_square: int


class Board:
    """Chess position stored as 12 piece bitboards, indexed by color and type."""

    __slots__ = ("bitboards", "side_to_move")

    def __init__(self, bitboards: list[list[int]] | None = None, side_to_move: int = WHITE):
        self.bitboards = (
            [row[:] for row in bitboards]
            if bitboards is not None
            else [[0] * 6 for _ in range(2)]
        )
        self.side_to_move = side_to_move

    @classmethod
    def initial(cls) -> Board:
        board = cls()
        back_rank = (ROOK, KNIGHT, BISHOP, QUEEN, KING, BISHOP, KNIGHT, ROOK)
        for column, piece in enumerate(back_rank):
            board.bitboards[0][piece] |= 1 << square_index(0, column)
            board.bitboards[1][piece] |= 1 << square_index(7, column)
            board.bitboards[0][PAWN] |= 1 << square_index(1, column)
            board.bitboards[1][PAWN] |= 1 << square_index(6, column)
        return board

    @staticmethod
    def _color_index(side: int) -> int:
        if side == WHITE:
            return 0
        if side == BLACK:
            return 1
        raise ValueError(f"Invalid side: {side}")

    def occupancy(self, side: int | None = None) -> int:
        if side is None:
            return self.occupancy(WHITE) | self.occupancy(BLACK)
        color = self._color_index(side)
        occupied = 0
        for bitboard in self.bitboards[color]:
            occupied |= bitboard
        return occupied

    def piece_at(self, square: int) -> tuple[int, int] | None:
        if not 0 <= square < 64:
            raise ValueError(f"Invalid square index: {square}")
        mask = 1 << square
        for color, side in enumerate((WHITE, BLACK)):
            for piece, bitboard in enumerate(self.bitboards[color]):
                if bitboard & mask:
                    return side, piece
        return None

    def legal_moves(self, side: int | None = None) -> list[Move]:
        side = self.side_to_move if side is None else side
        color = self._color_index(side)
        own = self.occupancy(side)
        enemy = self.occupancy(-side)
        occupied = own | enemy
        moves: list[Move] = []

        for piece, bitboard in enumerate(self.bitboards[color]):
            for source in iter_bits(bitboard):
                row, column = divmod(source, BOARD_SIZE)
                if piece == PAWN:
                    forward = row + side
                    if 0 <= forward < BOARD_SIZE:
                        one_step = square_index(forward, column)
                        if not occupied & (1 << one_step):
                            moves.append(Move(source, one_step))
                            start_row = 1 if side == WHITE else 6
                            two_forward = row + 2 * side
                            if row == start_row:
                                two_step = square_index(two_forward, column)
                                if not occupied & (1 << two_step):
                                    moves.append(Move(source, two_step))
                        for delta_column in (-1, 1):
                            target_column = column + delta_column
                            if 0 <= target_column < BOARD_SIZE:
                                target = square_index(forward, target_column)
                                if enemy & (1 << target):
                                    moves.append(Move(source, target))
                elif piece == KNIGHT:
                    self._add_leaper_moves(moves, source, row, column, KNIGHT_STEPS, own)
                elif piece == KING:
                    self._add_leaper_moves(moves, source, row, column, KING_STEPS, own)
                else:
                    directions = (
                        BISHOP_DIRECTIONS if piece == BISHOP
                        else ROOK_DIRECTIONS if piece == ROOK
                        else ROOK_DIRECTIONS + BISHOP_DIRECTIONS
                    )
                    for delta_row, delta_column in directions:
                        target_row = row + delta_row
                        target_column = column + delta_column
                        while 0 <= target_row < BOARD_SIZE and 0 <= target_column < BOARD_SIZE:
                            target = square_index(target_row, target_column)
                            target_mask = 1 << target
                            if own & target_mask:
                                break
                            moves.append(Move(source, target))
                            if enemy & target_mask:
                                break
                            target_row += delta_row
                            target_column += delta_column
        return moves

    @staticmethod
    def _add_leaper_moves(
        moves: list[Move],
        source: int,
        row: int,
        column: int,
        offsets: tuple[tuple[int, int], ...],
        own: int,
    ) -> None:
        for delta_row, delta_column in offsets:
            target_row = row + delta_row
            target_column = column + delta_column
            if 0 <= target_row < BOARD_SIZE and 0 <= target_column < BOARD_SIZE:
                target = square_index(target_row, target_column)
                if not own & (1 << target):
                    moves.append(Move(source, target))

    def make_move(self, move: Move) -> Board:
        moving_piece = self.piece_at(move.from_square)
        if moving_piece is None:
            raise ValueError(f"No piece on source square {move.from_square}")
        side, piece = moving_piece
        color = self._color_index(side)
        next_board = Board(self.bitboards, -side)
        source_mask = 1 << move.from_square
        target_mask = 1 << move.to_square
        next_board.bitboards[color][piece] &= ~source_mask
        for enemy_piece, bitboard in enumerate(next_board.bitboards[1 - color]):
            if bitboard & target_mask:
                next_board.bitboards[1 - color][enemy_piece] &= ~target_mask
                break
        next_board.bitboards[color][piece] |= target_mask
        return next_board

    def evaluate(self) -> float:
        score = 0.0
        for color, side in enumerate((WHITE, BLACK)):
            for piece, bitboard in enumerate(self.bitboards[color]):
                for square in iter_bits(bitboard):
                    row, column = divmod(square, BOARD_SIZE)
                    score += (PIECE_VALUES[piece] + gridded[row][column]) * side
        return score

    def __str__(self) -> str:
        rows = []
        for row in range(BOARD_SIZE):
            cells = []
            for column in range(BOARD_SIZE):
                occupant = self.piece_at(square_index(row, column))
                if occupant is None:
                    cells.append(".")
                else:
                    side, piece = occupant
                    color = "w" if side == WHITE else "b"
                    cells.append(f"{PIECE_SYMBOLS[piece]}-{color}")
            rows.append(" | ".join(f"{cell:4}" for cell in cells))
        return "\n".join(rows)


def minimax(
    board: Board,
    depth: int,
    alpha: float = -MAX_INT,
    beta: float = MAX_INT,
) -> tuple[float, Move | None, Board]:
    if depth <= 0:
        return board.evaluate(), None, board

    side = board.side_to_move
    moves = board.legal_moves()
    if not moves:
        return board.evaluate(), None, board

    maximizing = side == WHITE
    best_score = -MAX_INT if maximizing else MAX_INT
    best_move: Move | None = None
    best_board = board
    for move in moves:
        child = board.make_move(move)
        score, _, leaf_board = minimax(child, depth - 1, alpha, beta)
        if (maximizing and score > best_score) or (not maximizing and score < best_score):
            best_score, best_move, best_board = score, move, leaf_board
        if maximizing:
            alpha = max(alpha, best_score)
        else:
            beta = min(beta, best_score)
        if beta <= alpha:
            break
    return best_score, best_move, best_board


def white_minimax(
    board: Board,
    depth: int,
    maximise: bool = True,
    alpha: float = -MAX_INT,
    beta: float = MAX_INT,
) -> tuple[float, Move | None, Board]:
    del maximise
    return minimax(Board(board.bitboards, WHITE), depth, alpha, beta)


def black_minimax(
    board: Board,
    depth: int,
    maximise: bool = True,
    alpha: float = -MAX_INT,
    beta: float = MAX_INT,
) -> tuple[float, Move | None, Board]:
    del maximise
    return minimax(Board(board.bitboards, BLACK), depth, alpha, beta)


def sim_game(board: Board, move_time: float = 4.5, max_plies: int = 100) -> Board:
    position = Board(board.bitboards, board.side_to_move)
    for _ in range(max_plies):
        start = perf_counter()
        best_move = None
        depth = 1
        while perf_counter() - start < move_time:
            print(depth)
            _, candidate, _ = minimax(position, depth)
            if candidate is None:
                break
            best_move = candidate
            depth += 1
        if best_move is None:
            break
        position = position.make_move(best_move)
        print(position)
        print(f"{'White' if position.side_to_move == WHITE else 'Black'} to move")
    return position


board_state = Board.initial()

if __name__ == "__main__":
    sim_game(board_state)
