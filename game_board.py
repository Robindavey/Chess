from collections import deque
import heapq
WHITE = 1
BLACK = -1
BOARD_LIMITS = (8,8)
MAX_INT = 1000000
material = [4*3 + 8 + 10 + 9] * 3
gridded = [[ -50, -40, -30, -30, -30, -30, -40, -50 ],
[ -40, -20,   0,   5,   5,   0, -20, -40 ],
[ -30,   5,  10,  15,  15,  10,   5, -30 ],
[ -30,   0,  15,  20,  20,  15,   0, -30 ],
[ -30,   5,  15,  20,  20,  15,   5, -30 ],
[ -30,   0,  10,  15,  15,  10,   0, -30 ],
[ -40, -20,   0,   0,   0,   0, -20, -40 ],
[ -50, -40, -30, -30, -30, -30, -40, -50 ]]
gridded = [[x/100 for x in g] for g in gridded]
class Piece:
    __slots__ = ("position", "side")
    def __init__(self, position, side):
        self.position = position
        self.side = side
    def get_legal_moves(self)->list[tuple]:
        pass
    def follow_direction(self, move:tuple, temp_position:tuple, state:set, owner:dict, reps:int) -> list[tuple]:
                lm = []
                dx, dy = move
                a_take = False
                nX, nY = temp_position[0] + dx, temp_position[1] + dy
                while reps > 0 and nX >= 0 and nX < BOARD_LIMITS[0] and nY >= 0 and nY < BOARD_LIMITS[1] and ((nX,nY) not in state or (((nX,nY) in state and owner[(nX,nY)] != self.side))) and not a_take:
                    if ((nX,nY) in state and owner[(nX,nY)] != self.side):
                        a_take = True
                    lm.append((nX,nY))
                    nX,nY = nX+dx, nY + dy
                    reps-=1
                return lm
class Rook(Piece):
    def __init__(self, position:tuple, side:int):
        super().__init__(position, side)
        self.moves : list[tuple] = [(0,1), (0,-1), (1,0), (-1,0)]
    def get_legal_moves(self, state : set, owner : dict) -> list[tuple]:
        lm = []
        for move in self.moves:
            lm.extend(self.follow_direction(move, self.position, state, owner, 8))
        return lm
    def copy(self):
        return Rook(self.position, self.side)
class Bishop(Piece):
    def __init__(self, position, side):
        super().__init__(position, side)
        self.moves = [(-1,-1), (-1,1), (1,-1), (1,1)]
    def get_legal_moves(self, state : set, owner : dict) -> list[tuple]:
        lm = []
        for move in self.moves:
            lm.extend(self.follow_direction(move, self.position, state, owner, 8))
        return lm
    def copy(self):
            return Bishop(self.position, self.side)
class Knight(Piece):
    def __init__(self, position, side):
        super().__init__(position, side)
        self.moves = [(2,1), (2,-1), (1,2), (-1,2),(-2,1), (-2,-1), (1,-2), (-1,-2) ]
    def get_legal_moves(self, state : set, owner : dict) -> list[tuple]:
        lm = []
        for move in self.moves:
            lm.extend(self.follow_direction(move, self.position, state, owner, 1))
        return lm
    def copy(self):
            return Knight(self.position, self.side)
class Queen(Piece):
    def __init__(self, position, side):
        super().__init__(position, side)
        self.moves = [(-1,-1), (-1,1), (1,-1), (1,1), (0,1), (0,-1), (1,0), (-1,0)]
    def get_legal_moves(self, state : set, owner : dict) -> list[tuple]:
        lm = []
        for move in self.moves:
            lm.extend(self.follow_direction(move, self.position, state, owner, 8))
        return lm
    def copy(self):
            return Queen(self.position, self.side)
class King(Piece):
    def __init__(self, position, side):
        super().__init__(position, side)
        self.moves = [(-1,-1), (-1,1), (1,-1), (1,1), (0,1), (0,-1), (1,0), (-1,0)]
    def get_legal_moves(self, state : set, owner : dict):
        lm = []
        for move in self.moves:
            lm.extend(self.follow_direction(move, self.position, state, owner, 1))
        return lm
    def copy(self):
            return King(self.position, self.side)
class Pawn(Piece):
    def __init__(self, position, side, first_move = True):
        super().__init__(position, side)
        self.moves = [(1,0), (1,1), (-1,1)]
        self.first_move : bool = first_move
    def get_legal_moves(self, state : set, owner : dict) -> list[tuple]:
        lm = []
        forward = (self.position[0] + self.side, self.position[1])
        if 0 <= forward[0] < BOARD_LIMITS[0] and forward not in state:
            lm.append(forward)
            double_forward = (self.position[0] + 2 * self.side, self.position[1])
            if self.first_move and 0 <= double_forward[0] < BOARD_LIMITS[0] and double_forward not in state:
                lm.append(double_forward)
        for dy in (-1, 1):
            target = (self.position[0] + self.side, self.position[1] + dy)
            if (
                0 <= target[0] < BOARD_LIMITS[0]
                and 0 <= target[1] < BOARD_LIMITS[1]
                and target in state
                and state[target].side != self.side
            ):
                lm.append(target)
        return lm
    def copy(self):
            return Pawn(self.position, self.side, first_move=self.first_move)
def class_to_letter(c : Piece) -> str:
    if type(c) == Rook:
        return f"R-{'w' if c.side == WHITE else 'b'}"
    if type(c) == King:
        return f"K-{'w' if c.side == WHITE else 'b'}"
    if type(c) == Queen:
        return f"Q-{'w' if c.side == WHITE else 'b'}"
    if type(c) == Knight:
        return f"KT-{'w' if c.side == WHITE else 'b'}"
    if type(c) == Pawn:
        return f"p-{'w' if c.side == WHITE else 'b'}"
    if type(c) == Bishop:
        return f"B-{'w' if c.side == WHITE else 'b'}"
board_state = [
    Rook((0,0), WHITE), Knight((0,1), WHITE), Bishop((0,2), WHITE), Queen((0,3), WHITE),
    King((0,4), WHITE), Bishop((0,5), WHITE), Knight((0,6), WHITE), Rook((0,7), WHITE),
    Pawn((1,0), WHITE),Pawn((1,1), WHITE), Pawn((1,2), WHITE), Pawn((1,3), WHITE),
    Pawn((1,4), WHITE), Pawn((1,5), WHITE), Pawn((1,6), WHITE), Pawn((1,7), WHITE),
    Pawn((6,0), BLACK), Pawn((6,1), BLACK), Pawn((6,2), BLACK), Pawn((6,3), BLACK),
    Pawn((6,4), BLACK), Pawn((6,5), BLACK), Pawn((6,6), BLACK), Pawn((6,7), BLACK),
    Rook((7,0), BLACK), Knight((7,1), BLACK), Bishop((7,2), BLACK), Queen((7,3), BLACK),
    King((7,4), BLACK), Bishop((7,5), BLACK), Knight((7,6), BLACK), Rook((7,7), BLACK),
]
"""puzzle = [
    King((0,6), WHITE),
    Rook((0,0), WHITE),
    Rook((1,1), WHITE),
    King((7,4), BLACK),
]
board_state = puzzle"""
def make_states_and_owner(board):
    game_state_set = {}
    ownership = {}
    for b in board:
        game_state_set[b.position] = b
        ownership[b.position] = b.side
    return game_state_set, ownership
def print_board(board_state: list[Piece]) -> None:
    brd = [["." for _ in range(8)] for _ in range(8)]
    for b in board_state:
        x, y = b.position
        brd[x][y] = class_to_letter(b)

    width = max(len(cell) for row in brd for cell in row)
    for row in brd:
        print(" | ".join(cell.ljust(width) for cell in row))
def get_all_legal_moves(board):
    lm = [[],[],[]]
    game_state_set,ownership = make_states_and_owner(board)
    for b in board:
        mini_legals = b.get_legal_moves(game_state_set,ownership)
        if len(mini_legals) > 0:
            lm[b.side + 1].append((mini_legals, b))
    return lm[2], lm[0]
def equate(c : Piece):
    if type(c) == Rook:
        return 5
    if type(c) == King:
        return MAX_INT
    if type(c) == Queen:
        return 9
    if type(c) == Knight:
        return 3
    if type(c) == Pawn:
        return 1
    if type(c) == Bishop:
        return 3
def eval_board(board):
    output = 0
    for p in board:
        output += (equate(p) + gridded[p.position[0]][p.position[1]]) * p.side
    return output
def make_move(board : list[Piece], move : tuple, piece:Piece, state : dict) -> None:
    if move in state:
        #this is then an attack
        opp = state[move]
        board.remove(opp)
    if type(piece) == Pawn:
        piece.first_move = False
    piece.position = move
def white_minimax(board: list[Piece], depth, maximise, alpha, beta):
    """Returns (value, best_move, best_board).
    best_move  = (piece, move) chosen at this node (None at leaves / no moves)
    best_board = leaf board at the end of the best line from this node
    """
    if depth == 0:
        return eval_board(board), None, board

    white_legal_moves, black_legal_moves = get_all_legal_moves(board)
    legal_moves = white_legal_moves if maximise else black_legal_moves

    bestVal = -MAX_INT if maximise else MAX_INT
    bestMove = None
    bestBoard = board          # fallback if there are no legal moves

    for moves, piece in legal_moves:
        for move in moves:
            new_board = [b.copy() for b in board]
            state_dict, owners = make_states_and_owner(new_board)
            make_move(new_board, move, state_dict[piece.position], state_dict)

            value, _, leaf_board = white_minimax(new_board, depth - 1, not maximise, alpha, beta)

            if maximise:
                if value > bestVal:
                    bestVal, bestMove, bestBoard = value, (piece, move), leaf_board
                alpha = max(alpha, bestVal)
            else:
                if value < bestVal:
                    bestVal, bestMove, bestBoard = value, (piece, move), leaf_board
                beta = min(beta, bestVal)

            if beta <= alpha:
                return bestVal, bestMove, bestBoard

    return bestVal, bestMove, bestBoard
def black_minimax(board: list[Piece], depth, maximise, alpha, beta):
    """Returns (value, best_move, best_board).
    best_move  = (piece, move) chosen at this node (None at leaves / no moves)
    best_board = leaf board at the end of the best line from this node
    """
    if depth == 0:
        return eval_board(board), None, board

    white_legal_moves, black_legal_moves = get_all_legal_moves(board)
    legal_moves = black_legal_moves if maximise else white_legal_moves

    bestVal = -MAX_INT if maximise else MAX_INT
    bestMove = None
    bestBoard = board

    for moves, piece in legal_moves:
        for move in moves:
            new_board = [b.copy() for b in board]
            state_dict, owners = make_states_and_owner(new_board)
            make_move(new_board, move, state_dict[piece.position], state_dict)

            value, _, leaf_board = white_minimax(new_board, depth - 1, not maximise, alpha, beta)

            if maximise:
                if value > bestVal:
                    bestVal, bestMove, bestBoard = value, (piece, move), leaf_board
                alpha = max(alpha, bestVal)
            else:
                if value < bestVal:
                    bestVal, bestMove, bestBoard = value, (piece, move), leaf_board
                beta = min(beta, bestVal)

            if beta <= alpha:
                return bestVal, bestMove, bestBoard

    return bestVal, bestMove, bestBoard
import time
def sim_game(board):
    score = 0
    white = True
    while score < 100:
        start_time = time.perf_counter()
        et = time.perf_counter()
        iter_deep = 3
        last_et = time.perf_counter()
        if white:
            while et - start_time  < 4.5:
                
                last_et = et
                print(iter_deep, last_et - start_time)
                score,(p, bm),__ = white_minimax(board, iter_deep, True, -MAX_INT, MAX_INT)
                iter_deep +=1
                et = time.perf_counter()
        else:
            while et-start_time  < 4.5:
                last_et = et
                print(iter_deep, last_et - start_time)

                score,(p, bm),__ = black_minimax(board, iter_deep, True, -MAX_INT, MAX_INT)
                iter_deep +=1
                et = time.perf_counter()
        p.position = bm
        white = not white
        print_board(board)
sim_game(board_state)
