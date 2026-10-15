
WHITE = -1
BLACK = 1
BOARD_LIMITS = (8,8)
material = [4*3 + 8 + 10 + 9] * 3
print(material)
class Piece:
    def __init__(self, position, side):
        self.position = position
        self.side = side
    def get_legal_moves(self)->list[tuple]:
        pass
    def follow_direction(self, move:tuple, temp_position:tuple, state:set, owner:dict, reps:int) -> list[tuple]:
                lm = []
                dx, dy = move
                a_take = False
                nX, nY = (temp_position[0]+dx* self.side) , (temp_position[1] + dy * self.side)
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
class Bishop(Piece):
    def __init__(self, position, side):
        super().__init__(position, side)
        self.moves = [(-1,-1), (-1,1), (1,-1), (1,1)]
    def get_legal_moves(self, state : set, owner : dict) -> list[tuple]:
        lm = []
        for move in self.moves:
            lm.extend(self.follow_direction(move, self.position, state, owner, 8))
        return lm
class Knight(Piece):
    def __init__(self, position, side):
        super().__init__(position, side)
        self.moves = [(2,1), (2,-1), (1,2), (-1,2),(-2,1), (-2,-1), (1,-2), (-1,-2) ]
    def get_legal_moves(self, state : set, owner : dict) -> list[tuple]:
        lm = []
        for move in self.moves:
            lm.extend(self.follow_direction(move, self.position, state, owner, 1))
        return lm
class Queen(Piece):
    def __init__(self, position, side):
        super().__init__(position, side)
        self.moves = [(-1,-1), (-1,1), (1,-1), (1,1), (0,1), (0,-1), (1,0), (-1,0)]
    def get_legal_moves(self, state : set, owner : dict) -> list[tuple]:
        lm = []
        for move in self.moves:
            lm.extend(self.follow_direction(move, self.position, state, owner, 8))
        return lm
class King(Piece):
    def __init__(self, position, side):
        super().__init__(position, side)
        self.moves = [(-1,-1), (-1,1), (1,-1), (1,1), (0,1), (0,-1), (1,0), (-1,0)]
    def get_legal_moves(self, state : set, owner : dict):
        lm = []
        for move in self.moves:
            lm.extend(self.follow_direction(move, self.position, state, owner, 1))
        return lm
class Pawn(Piece):
    def __init__(self, position, side):
        super().__init__(position, side)
        self.moves = [(0,1), (1,1), (-1,1)]
        self.first_move : bool = True
    def get_legal_moves(self, state : set, owner : dict) -> list[tuple]:
        lm = []
        lm.extend(self.follow_direction(self.moves[0], self.position, state, owner, 2 if self.first_move else 1))
        if self.moves[1][0] * self.side + self.position[0] >= 0 and self.moves[1][0] * self.side + self.position[0] < BOARD_LIMITS[0] and self.moves[1][1] * self.side + self.position[1] >= 0 and self.moves[1][1] * self.side + self.position[1] < BOARD_LIMITS[1] and (self.moves[1][1] * self.side + self.position[0], self.moves[1][1] * self.side + self.position[1]) in state and state[(self.moves[1][1] * self.side + self.position[0], self.moves[1][1] * self.side + self.position[1])].side != self.side:
            lm.extend([(self.moves[1][1] * self.side + self.position[0], self.moves[1][1] * self.side + self.position[1])])
        if self.moves[2][0] * self.side + self.position[0] >= 0 and self.moves[2][0] * self.side + self.position[0] < BOARD_LIMITS[0] and self.moves[2][1] * self.side + self.position[1] >= 0 and self.moves[2][1] * self.side + self.position[1] < BOARD_LIMITS[1] and (self.moves[2][1] * self.side + self.position[0], self.moves[2][1] * self.side + self.position[1]) in state and state[(self.moves[2][1] * self.side + self.position[0], self.moves[2][1] * self.side + self.position[1])].side != self.side:
                    lm.extend([(self.moves[2][1] * self.side + self.position[0], self.moves[2][1] * self.side + self.position[1])])
        return lm
def class_to_letter(c : Piece) -> str:
    if type(c) == Rook:
        return f"R-{'b' if c.side == 1 else 'w'}"
    if type(c) == King:
        return f"K-{'b' if c.side == 1 else 'w'}"
    if type(c) == Queen:
        return f"Q-{'b' if c.side == 1 else 'w'}"
    if type(c) == Knight:
        return f"KT-{'b' if c.side == 1 else 'w'}"
    if type(c) == Pawn:
        return f"p-{'b' if c.side == 1 else 'w'}"
    if type(c) == Bishop:
        return f"B-{'b' if c.side == 1 else 'w'}"
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

def make_states_and_owner(board):
    game_state_set = {}
    ownership = {}
    for b in board_state:
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
    for b in board_state:
        lm[b.side + 1].append((b.get_legal_moves(game_state_set,ownership), b))
    return lm[0], lm[2]
def equate(c : Piece):
    if type(c) == Rook:
        return 5
    if type(c) == King:
        return int("inf")
    if type(c) == Queen:
        return 9
    if type(c) == Knight:
        return 3
    if type(c) == Pawn:
        return 1
    if type(c) == Bishop:
        return 3
def make_move(board : list[Piece], move : tuple, piece:Piece, state : dict, materials :list) -> None:
    x,y = move
    if move in state:
        #this is then an attack
        opp = state[move]
        board.remove(opp)
        materials[piece.side * -1 + 1] -= equate(opp)
    
def minimax(board : list[Piece], me:int, depth=5):
    game_state_set,ownership = make_states_and_owner(board)
    white_legal_moves, black_legal_moves = get_all_legal_moves(board)
    """#print(list(game_state_set.keys()))
    print(black_legal_moves)
    #print(white_legal_moves)
    #print(ownership)"""
    print(f"\n\n{'White' if me == -1 else 'Black'} to play")
    print_board(board)
    print("\n\n")
    if me == -1:
        new_board_copy = board.copy()
        piece = white_legal_moves[1][1]
        make_move(new_board_copy, white_legal_moves[1][0][0], piece, game_state_set, material)
    
minimax(board_state, -1)