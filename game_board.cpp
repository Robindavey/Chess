// Build: g++ -O3 -march=native -std=c++20 game_board.cpp -o game_board
// Self-play:      ./game_board [seconds_per_move=4.5] [max_plies=100]
// Server (Flask): ./game_board --serve      (line protocol on stdin/stdout, see serve())
//
// Rules: pseudo-legal moves + castling (not out of / through / into check) + en passant.
// Still no promotion, and leaving your king attacked is allowed (the king can be captured).
//
// Same rules/eval as the Python version (pseudo-legal moves, no promotion,
// no castling/en passant, king capture ends the game, same material +
// positional table), but with a much faster engine underneath.

#include <algorithm>
#include <array>
#include <bit>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

namespace chess {

using U64 = std::uint64_t;

constexpr int WHITE = 0, BLACK = 1;
enum Piece : int { PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING, NONE };

constexpr const char* PIECE_SYMBOLS[6] = {"p", "KT", "B", "R", "Q", "K"};
constexpr int PIECE_VALUE[6] = {100, 300, 300, 500, 900, 0};  // centipawns; king handled as a win

constexpr int INF = 1'000'000;
constexpr int MATE = 100'000;
constexpr int MATE_BOUND = MATE - 1000;
constexpr int MAX_PLY = 64;

// Move flags
constexpr int F_NONE = 0, F_EP = 1, F_CASTLE = 2, F_DOUBLE = 3;
// Castling rights bits
constexpr int CR_WK = 1, CR_WQ = 2, CR_BK = 4, CR_BQ = 8;

constexpr U64 FILE_A = 0x0101010101010101ULL;
constexpr U64 FILE_H = FILE_A << 7;
constexpr U64 RANK3 = 0xFFULL << 16;  // white pawns after a single push from the start row
constexpr U64 RANK6 = 0xFFULL << 40;  // black pawns after a single push from the start row

// Original positional table, in pawns; converted to integer centipawns below.
constexpr double GRIDDED[8][8] = {
    {-0.50, -0.40, -0.30, -0.30, -0.30, -0.30, -0.40, -0.50},
    {-0.40, -0.20, 0.00, 0.05, 0.05, 0.00, -0.20, -0.40},
    {-0.30, 0.05, 0.10, 0.15, 0.15, 0.10, 0.05, -0.30},
    {-0.30, 0.00, 0.15, 0.20, 0.20, 0.15, 0.00, -0.30},
    {-0.30, 0.05, 0.15, 0.20, 0.20, 0.15, 0.05, -0.30},
    {-0.30, 0.00, 0.10, 0.15, 0.15, 0.10, 0.00, -0.30},
    {-0.40, -0.20, 0.00, 0.00, 0.00, 0.00, -0.20, -0.40},
    {-0.50, -0.40, -0.30, -0.30, -0.30, -0.30, -0.40, -0.50},
};

// ---------------------------------------------------------------------------
// Precomputed tables (built once at startup)
// ---------------------------------------------------------------------------
struct Tables {
    U64 knight[64]{}, king[64]{}, ray[8][64]{}, pawnAtk[2][64]{};
    int castleMask[64]{};
    U64 zobristCastle[16]{}, zobristEp[8]{};
    int score[6][64]{};  // material + positional, white-POV magnitude
    U64 zobrist[2][6][64]{};
    U64 zobristSide = 0;

    Tables() {
        // Rays: 0-3 point toward higher square indices, 4-7 toward lower.
        constexpr int dr[8] = {1, 0, 1, 1, -1, 0, -1, -1};
        constexpr int dc[8] = {0, 1, 1, -1, 0, -1, -1, 1};
        constexpr int kn[8][2] = {{-2, -1}, {-2, 1}, {-1, -2}, {-1, 2}, {1, -2}, {1, 2}, {2, -1}, {2, 1}};
        constexpr int kg[8][2] = {{-1, -1}, {-1, 0}, {-1, 1}, {0, -1}, {0, 1}, {1, -1}, {1, 0}, {1, 1}};

        for (int sq = 0; sq < 64; ++sq) {
            const int r = sq / 8, c = sq % 8;
            for (int d = 0; d < 8; ++d)
                for (int rr = r + dr[d], cc = c + dc[d]; rr >= 0 && rr < 8 && cc >= 0 && cc < 8;
                     rr += dr[d], cc += dc[d])
                    ray[d][sq] |= 1ULL << (rr * 8 + cc);
            for (auto& s : kn) {
                int rr = r + s[0], cc = c + s[1];
                if (rr >= 0 && rr < 8 && cc >= 0 && cc < 8) knight[sq] |= 1ULL << (rr * 8 + cc);
            }
            for (auto& s : kg) {
                int rr = r + s[0], cc = c + s[1];
                if (rr >= 0 && rr < 8 && cc >= 0 && cc < 8) king[sq] |= 1ULL << (rr * 8 + cc);
            }
            for (int cc : {-1, 1}) {
                if (r + 1 < 8 && c + cc >= 0 && c + cc < 8) pawnAtk[WHITE][sq] |= 1ULL << ((r + 1) * 8 + c + cc);
                if (r - 1 >= 0 && c + cc >= 0 && c + cc < 8) pawnAtk[BLACK][sq] |= 1ULL << ((r - 1) * 8 + c + cc);
            }
            castleMask[sq] = 15;
            for (int p = 0; p < 6; ++p)
                score[p][sq] = PIECE_VALUE[p] + static_cast<int>(std::lround(GRIDDED[r][c] * 100.0));
        }

        castleMask[4] = 15 & ~(CR_WK | CR_WQ);
        castleMask[0] = 15 & ~CR_WQ;
        castleMask[7] = 15 & ~CR_WK;
        castleMask[60] = 15 & ~(CR_BK | CR_BQ);
        castleMask[56] = 15 & ~CR_BQ;
        castleMask[63] = 15 & ~CR_BK;

        U64 seed = 0x9E3779B97F4A7C15ULL;  // splitmix64
        auto next = [&] {
            U64 z = (seed += 0x9E3779B97F4A7C15ULL);
            z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
            z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
            return z ^ (z >> 31);
        };
        for (auto& a : zobrist)
            for (auto& b : a)
                for (auto& k : b) k = next();
        zobristSide = next();
        for (auto& k : zobristCastle) k = next();
        for (auto& k : zobristEp) k = next();
    }
};
inline const Tables T;

// ---------------------------------------------------------------------------
// Sliding attacks via ray tables + bit scan (no per-square loops)
// ---------------------------------------------------------------------------
template <int D>
inline U64 rayAttack(int sq, U64 occ) {
    const U64 r = T.ray[D][sq];
    const U64 blockers = r & occ;
    if (!blockers) return r;
    const int first = D < 4 ? std::countr_zero(blockers) : 63 - std::countl_zero(blockers);
    return r ^ T.ray[D][first];
}
inline U64 rookAttacks(int sq, U64 occ) {
    return rayAttack<0>(sq, occ) | rayAttack<1>(sq, occ) | rayAttack<4>(sq, occ) | rayAttack<5>(sq, occ);
}
inline U64 bishopAttacks(int sq, U64 occ) {
    return rayAttack<2>(sq, occ) | rayAttack<3>(sq, occ) | rayAttack<6>(sq, occ) | rayAttack<7>(sq, occ);
}

// ---------------------------------------------------------------------------
// Moves and position
// ---------------------------------------------------------------------------
struct Move {
    std::uint8_t from = 64, to = 64, piece = NONE, captured = NONE, flag = F_NONE;
    Move() = default;
    Move(int f, int t, int p, int c, int fl = F_NONE)
        : from(static_cast<std::uint8_t>(f)), to(static_cast<std::uint8_t>(t)),
          piece(static_cast<std::uint8_t>(p)), captured(static_cast<std::uint8_t>(c)),
          flag(static_cast<std::uint8_t>(fl)) {}
    std::uint16_t packed() const { return static_cast<std::uint16_t>(from | (to << 6)); }
};

struct Undo {
    int eval;
    U64 hash;
    int castling;
    int ep;
};

struct Position {
    U64 bb[2][6]{};
    U64 occ[2]{};
    std::uint8_t board[64];  // piece type per square (NONE if empty); colour from occ[]
    int side = WHITE;
    int eval = 0;  // incremental, white POV, centipawns
    U64 hash = 0;
    int castling = 0;  // CR_* bits
    int ep = 64;       // en-passant target square (the square a pawn skipped over), 64 = none

    Position() { std::fill(std::begin(board), std::end(board), static_cast<std::uint8_t>(NONE)); }

    static Position initial() {
        Position p;
        p.castling = CR_WK | CR_WQ | CR_BK | CR_BQ;
        constexpr int back[8] = {ROOK, KNIGHT, BISHOP, QUEEN, KING, BISHOP, KNIGHT, ROOK};
        for (int c = 0; c < 8; ++c) {
            p.bb[WHITE][back[c]] |= 1ULL << c;
            p.bb[BLACK][back[c]] |= 1ULL << (56 + c);
            p.bb[WHITE][PAWN] |= 1ULL << (8 + c);
            p.bb[BLACK][PAWN] |= 1ULL << (48 + c);
        }
        p.recompute();
        return p;
    }

    // State = "<board64> <w|b> <castling KQkq|-> <ep square 0..63|->".
    // Board string: square 0 first (row 0 = white back rank), uppercase = white, '.' = empty.
    bool fromState(const std::string& boardStr, char sideChar, const std::string& castleStr,
                   const std::string& epStr) {
        if (boardStr.size() != 64) return false;
        *this = Position();
        for (int sq = 0; sq < 64; ++sq) {
            const char ch = boardStr[sq];
            if (ch == '.') continue;
            const bool white = ch >= 'A' && ch <= 'Z';
            const char lower = static_cast<char>(white ? ch - 'A' + 'a' : ch);
            int piece;
            switch (lower) {
                case 'p': piece = PAWN; break;
                case 'n': piece = KNIGHT; break;
                case 'b': piece = BISHOP; break;
                case 'r': piece = ROOK; break;
                case 'q': piece = QUEEN; break;
                case 'k': piece = KING; break;
                default: return false;
            }
            bb[white ? WHITE : BLACK][piece] |= 1ULL << sq;
        }
        side = sideChar == 'b' ? BLACK : WHITE;
        castling = 0;
        for (char ch : castleStr) {
            if (ch == 'K') castling |= CR_WK;
            else if (ch == 'Q') castling |= CR_WQ;
            else if (ch == 'k') castling |= CR_BK;
            else if (ch == 'q') castling |= CR_BQ;
        }
        ep = 64;
        if (epStr != "-") {
            const int v = std::atoi(epStr.c_str());
            if (v < 0 || v > 63) return false;
            ep = v;
        }
        recompute();
        return true;
    }

    std::string toState() const {
        static constexpr char sym[6] = {'p', 'n', 'b', 'r', 'q', 'k'};
        std::string s(64, '.');
        for (int sq = 0; sq < 64; ++sq)
            if (board[sq] != NONE) {
                char c = sym[board[sq]];
                if ((occ[WHITE] >> sq) & 1) c = static_cast<char>(c - 'a' + 'A');
                s[sq] = c;
            }
        s += side == WHITE ? " w " : " b ";
        std::string cr;
        if (castling & CR_WK) cr += 'K';
        if (castling & CR_WQ) cr += 'Q';
        if (castling & CR_BK) cr += 'k';
        if (castling & CR_BQ) cr += 'q';
        s += cr.empty() ? "-" : cr;
        s += ' ';
        s += ep < 64 ? std::to_string(ep) : "-";
        return s;
    }

    void recompute() {
        occ[0] = occ[1] = 0;
        std::fill(std::begin(board), std::end(board), static_cast<std::uint8_t>(NONE));
        eval = 0;
        hash = 0;
        for (int c = 0; c < 2; ++c)
            for (int p = 0; p < 6; ++p)
                for (U64 b = bb[c][p]; b; b &= b - 1) {
                    const int sq = std::countr_zero(b);
                    board[sq] = static_cast<std::uint8_t>(p);
                    occ[c] |= 1ULL << sq;
                    eval += (c == WHITE ? 1 : -1) * T.score[p][sq];
                    hash ^= T.zobrist[c][p][sq];
                }
        // Drop castling rights that don't match the pieces actually on the board.
        if (!(bb[WHITE][KING] & (1ULL << 4))) castling &= ~(CR_WK | CR_WQ);
        if (!(bb[WHITE][ROOK] & (1ULL << 7))) castling &= ~CR_WK;
        if (!(bb[WHITE][ROOK] & (1ULL << 0))) castling &= ~CR_WQ;
        if (!(bb[BLACK][KING] & (1ULL << 60))) castling &= ~(CR_BK | CR_BQ);
        if (!(bb[BLACK][ROOK] & (1ULL << 63))) castling &= ~CR_BK;
        if (!(bb[BLACK][ROOK] & (1ULL << 56))) castling &= ~CR_BQ;
        hash ^= T.zobristCastle[castling];
        if (ep < 64) hash ^= T.zobristEp[ep & 7];
        if (side == BLACK) hash ^= T.zobristSide;
    }

    // Is `sq` attacked by any piece of colour `by`?
    bool attacked(int sq, int by) const {
        const U64 all = occ[0] | occ[1];
        if (T.pawnAtk[by ^ 1][sq] & bb[by][PAWN]) return true;
        if (T.knight[sq] & bb[by][KNIGHT]) return true;
        if (T.king[sq] & bb[by][KING]) return true;
        if (bishopAttacks(sq, all) & (bb[by][BISHOP] | bb[by][QUEEN])) return true;
        if (rookAttacks(sq, all) & (bb[by][ROOK] | bb[by][QUEEN])) return true;
        return false;
    }

    bool kingAttacked(int color) const {
        return bb[color][KING] && attacked(std::countr_zero(bb[color][KING]), color ^ 1);
    }

    int stmEval() const { return side == WHITE ? eval : -eval; }

    // Pseudo-legal move generation; CapturesOnly is used by quiescence search.
    template <bool CapturesOnly>
    int generate(Move* out) const {
        const int us = side, them = us ^ 1;
        const U64 own = occ[us], enemy = occ[them], all = own | enemy;
        const U64 targets = CapturesOnly ? enemy : ~own;
        int n = 0;

        auto emit = [&](int from, U64 tg, int piece) {
            while (tg) {
                const int to = std::countr_zero(tg);
                tg &= tg - 1;
                out[n++] = Move(from, to, piece, board[to]);
            }
        };
        auto emitPawns = [&](U64 tg, int delta, int flag = F_NONE) {
            while (tg) {
                const int to = std::countr_zero(tg);
                tg &= tg - 1;
                out[n++] = Move(to - delta, to, PAWN, board[to], flag);
            }
        };

        // Pawns: whole-bitboard shifts instead of per-pawn loops.
        const U64 pawns = bb[us][PAWN];
        if (us == WHITE) {
            if (!CapturesOnly) {
                const U64 one = (pawns << 8) & ~all;
                const U64 two = ((one & RANK3) << 8) & ~all;
                emitPawns(one, 8);
                emitPawns(two, 16, F_DOUBLE);
            }
            emitPawns((pawns << 7) & ~FILE_H & enemy, 7);
            emitPawns((pawns << 9) & ~FILE_A & enemy, 9);
        } else {
            if (!CapturesOnly) {
                const U64 one = (pawns >> 8) & ~all;
                const U64 two = ((one & RANK6) >> 8) & ~all;
                emitPawns(one, -8);
                emitPawns(two, -16, F_DOUBLE);
            }
            emitPawns((pawns >> 7) & ~FILE_A & enemy, -7);
            emitPawns((pawns >> 9) & ~FILE_H & enemy, -9);
        }

        // En passant: the target square is empty and an enemy pawn sits right behind it.
        if (ep < 64 && (us == WHITE ? (ep >> 3) == 5 : (ep >> 3) == 2)) {
            const int capSq = us == WHITE ? ep - 8 : ep + 8;
            if (((bb[them][PAWN] >> capSq) & 1) && !((all >> ep) & 1))
                for (U64 a = T.pawnAtk[them][ep] & pawns; a; a &= a - 1)
                    out[n++] = Move(std::countr_zero(a), ep, PAWN, PAWN, F_EP);
        }

        for (U64 b = bb[us][KNIGHT]; b; b &= b - 1) {
            const int sq = std::countr_zero(b);
            emit(sq, T.knight[sq] & targets, KNIGHT);
        }
        for (U64 b = bb[us][BISHOP]; b; b &= b - 1) {
            const int sq = std::countr_zero(b);
            emit(sq, bishopAttacks(sq, all) & targets, BISHOP);
        }
        for (U64 b = bb[us][ROOK]; b; b &= b - 1) {
            const int sq = std::countr_zero(b);
            emit(sq, rookAttacks(sq, all) & targets, ROOK);
        }
        for (U64 b = bb[us][QUEEN]; b; b &= b - 1) {
            const int sq = std::countr_zero(b);
            emit(sq, (rookAttacks(sq, all) | bishopAttacks(sq, all)) & targets, QUEEN);
        }
        for (U64 b = bb[us][KING]; b; b &= b - 1) {
            const int sq = std::countr_zero(b);
            emit(sq, T.king[sq] & targets, KING);
        }

        // Castling: rights intact, squares between empty, king not in / passing through check.
        if (!CapturesOnly && (castling & (us == WHITE ? (CR_WK | CR_WQ) : (CR_BK | CR_BQ)))) {
            const int base = us == WHITE ? 0 : 56;
            const int ks = us == WHITE ? CR_WK : CR_BK, qs = us == WHITE ? CR_WQ : CR_BQ;
            const U64 kingsideGap = (1ULL << (base + 5)) | (1ULL << (base + 6));
            const U64 queensideGap = (1ULL << (base + 1)) | (1ULL << (base + 2)) | (1ULL << (base + 3));
            if ((castling & ks) && !(all & kingsideGap) && !attacked(base + 4, them) &&
                !attacked(base + 5, them) && !attacked(base + 6, them))
                out[n++] = Move(base + 4, base + 6, KING, NONE, F_CASTLE);
            if ((castling & qs) && !(all & queensideGap) && !attacked(base + 4, them) &&
                !attacked(base + 3, them) && !attacked(base + 2, them))
                out[n++] = Move(base + 4, base + 2, KING, NONE, F_CASTLE);
        }
        return n;
    }

    // In-place make/unmake: no board copies, eval and hash updated incrementally.
    Undo make(const Move& m) {
        const Undo u{eval, hash, castling, ep};
        const int us = side, them = us ^ 1, sign = us == WHITE ? 1 : -1;
        const U64 f = 1ULL << m.from, t = 1ULL << m.to;

        if (ep < 64) hash ^= T.zobristEp[ep & 7];
        hash ^= T.zobristCastle[castling];
        hash ^= T.zobrist[us][m.piece][m.from] ^ T.zobrist[us][m.piece][m.to];
        eval += sign * (T.score[m.piece][m.to] - T.score[m.piece][m.from]);

        if (m.captured != NONE) {
            const int capSq = m.flag == F_EP ? (us == WHITE ? m.to - 8 : m.to + 8) : m.to;
            const U64 c = 1ULL << capSq;
            bb[them][m.captured] ^= c;
            occ[them] ^= c;
            board[capSq] = NONE;
            hash ^= T.zobrist[them][m.captured][capSq];
            eval += sign * T.score[m.captured][capSq];
        }
        bb[us][m.piece] ^= f | t;
        occ[us] ^= f | t;
        board[m.from] = NONE;
        board[m.to] = m.piece;

        if (m.flag == F_CASTLE) {
            const bool kingside = m.to > m.from;
            const int rf = kingside ? m.from + 3 : m.from - 4;
            const int rt = kingside ? m.from + 1 : m.from - 1;
            const U64 rm = (1ULL << rf) | (1ULL << rt);
            bb[us][ROOK] ^= rm;
            occ[us] ^= rm;
            board[rf] = NONE;
            board[rt] = ROOK;
            hash ^= T.zobrist[us][ROOK][rf] ^ T.zobrist[us][ROOK][rt];
            eval += sign * (T.score[ROOK][rt] - T.score[ROOK][rf]);
        }

        castling &= T.castleMask[m.from] & T.castleMask[m.to];
        ep = m.flag == F_DOUBLE ? (m.from + m.to) / 2 : 64;
        hash ^= T.zobristCastle[castling];
        if (ep < 64) hash ^= T.zobristEp[ep & 7];
        hash ^= T.zobristSide;
        side = them;
        return u;
    }

    void unmake(const Move& m, const Undo& u) {
        side ^= 1;
        const int us = side, them = us ^ 1;
        const U64 f = 1ULL << m.from, t = 1ULL << m.to;

        if (m.flag == F_CASTLE) {
            const bool kingside = m.to > m.from;
            const int rf = kingside ? m.from + 3 : m.from - 4;
            const int rt = kingside ? m.from + 1 : m.from - 1;
            const U64 rm = (1ULL << rf) | (1ULL << rt);
            bb[us][ROOK] ^= rm;
            occ[us] ^= rm;
            board[rt] = NONE;
            board[rf] = ROOK;
        }
        bb[us][m.piece] ^= f | t;
        occ[us] ^= f | t;
        board[m.from] = m.piece;
        board[m.to] = NONE;
        if (m.captured != NONE) {
            const int capSq = m.flag == F_EP ? (us == WHITE ? m.to - 8 : m.to + 8) : m.to;
            const U64 c = 1ULL << capSq;
            bb[them][m.captured] ^= c;
            occ[them] ^= c;
            board[capSq] = m.captured;
        }
        eval = u.eval;
        hash = u.hash;
        castling = u.castling;
        ep = u.ep;
    }

    void print() const {
        for (int r = 0; r < 8; ++r) {
            for (int c = 0; c < 8; ++c) {
                const int sq = r * 8 + c;
                char cell[16];
                if (board[sq] == NONE)
                    std::snprintf(cell, sizeof cell, ".");
                else
                    std::snprintf(cell, sizeof cell, "%s-%c", PIECE_SYMBOLS[board[sq]],
                                  (occ[WHITE] >> sq) & 1 ? 'w' : 'b');
                std::printf("%-4s%s", cell, c < 7 ? " | " : "");
            }
            std::printf("\n");
        }
    }
};

// ---------------------------------------------------------------------------
// Search: negamax + alpha-beta, iterative deepening, TT, MVV-LVA + history
// ordering, quiescence, and time checks *inside* the search.
// ---------------------------------------------------------------------------
class Engine {
public:
    struct Result {
        Move move;
        int score = 0;
        int depth = 0;
        bool valid = false;
    };

    explicit Engine(int ttBits = 20) : tt_(1ULL << ttBits), mask_((1ULL << ttBits) - 1) {}

    Result think(const Position& root, double seconds, int maxDepth = 40, bool verbose = true) {
        using Clock = std::chrono::steady_clock;
        pos_ = root;
        start_ = Clock::now();
        deadline_ = start_ + std::chrono::duration_cast<Clock::duration>(std::chrono::duration<double>(seconds));
        stop_ = false;
        nodes_ = 0;
        for (auto& a : history_) for (auto& b : a) for (auto& h : b) h /= 2;

        Result best;
        for (rootDepth_ = 1; rootDepth_ <= maxDepth; ++rootDepth_) {
            rootBest_ = Move();
            const int score = search(rootDepth_, -INF, INF, 0);
            if (stop_ && rootDepth_ > 1) break;  // discard the unfinished iteration
            if (rootBest_.from == 64) break;     // no moves
            best = {rootBest_, score, rootDepth_, true};
            if (verbose) {
                const double ms = std::chrono::duration<double, std::milli>(Clock::now() - start_).count();
                std::printf("depth %d score %d nodes %llu time %.0fms\n", rootDepth_, score,
                            static_cast<unsigned long long>(nodes_), ms);
            }
            if (std::abs(score) >= MATE_BOUND) break;
            if (Clock::now() >= deadline_) break;
        }
        return best;
    }

private:
    enum Flag : std::uint8_t { EXACT, LOWER, UPPER };
    struct TTEntry {
        U64 key = 0;
        std::int32_t score = 0;
        std::uint16_t move = 0;
        std::int8_t depth = -1;
        std::uint8_t flag = EXACT;
    };

    static int toTT(int s, int ply) { return s >= MATE_BOUND ? s + ply : s <= -MATE_BOUND ? s - ply : s; }
    static int fromTT(int s, int ply) { return s >= MATE_BOUND ? s - ply : s <= -MATE_BOUND ? s + ply : s; }

    void checkTime() {
        if (rootDepth_ > 1 && std::chrono::steady_clock::now() >= deadline_) stop_ = true;
    }

    static void pickBest(Move* mv, int* sc, int n, int i) {
        int b = i;
        for (int j = i + 1; j < n; ++j)
            if (sc[j] > sc[b]) b = j;
        if (b != i) {
            std::swap(mv[i], mv[b]);
            std::swap(sc[i], sc[b]);
        }
    }

    // MVV-LVA: most valuable victim first, cheapest attacker first. King capture sorts first.
    static int captureScore(const Move& m) {
        static constexpr int victim[6] = {1, 3, 3, 5, 9, 100};
        return 100'000 + victim[m.captured] * 16 - m.piece;
    }

    int quiesce(int alpha, int beta, int ply) {
        if ((++nodes_ & 2047) == 0) checkTime();
        if (stop_) return 0;
        int stand = pos_.stmEval();
        if (ply >= MAX_PLY - 1) return stand;
        if (stand >= beta) return stand;
        alpha = std::max(alpha, stand);

        Move mv[256];
        int sc[256];
        const int n = pos_.generate<true>(mv);
        for (int i = 0; i < n; ++i) sc[i] = captureScore(mv[i]);

        for (int i = 0; i < n; ++i) {
            pickBest(mv, sc, n, i);
            if (mv[i].captured == KING) return MATE - ply;
            const Undo u = pos_.make(mv[i]);
            const int s = -quiesce(-beta, -alpha, ply + 1);
            pos_.unmake(mv[i], u);
            if (stop_) return 0;
            if (s >= beta) return s;
            alpha = std::max(alpha, s);
        }
        return alpha;
    }

    int search(int depth, int alpha, int beta, int ply) {
        if (depth <= 0) return quiesce(alpha, beta, ply);
        if ((++nodes_ & 2047) == 0) checkTime();
        if (stop_) return 0;
        if (ply >= MAX_PLY - 1) return pos_.stmEval();

        const int alphaOrig = alpha;
        TTEntry& e = tt_[pos_.hash & mask_];
        std::uint16_t ttMove = 0;
        if (e.key == pos_.hash) {
            ttMove = e.move;
            if (ply > 0 && e.depth >= depth) {
                const int s = fromTT(e.score, ply);
                if (e.flag == EXACT) return s;
                if (e.flag == LOWER) alpha = std::max(alpha, s);
                else beta = std::min(beta, s);
                if (alpha >= beta) return s;
            }
        }

        Move mv[256];
        int sc[256];
        const int n = pos_.generate<false>(mv);
        if (n == 0) return pos_.stmEval();  // same as original: static eval when no moves

        const int us = pos_.side;
        for (int i = 0; i < n; ++i) {
            if (ttMove && mv[i].packed() == ttMove) sc[i] = 1'000'000;
            else if (mv[i].captured != NONE) sc[i] = captureScore(mv[i]);
            else sc[i] = history_[us][mv[i].from][mv[i].to];
        }

        int best = -INF;
        Move bestMove;
        for (int i = 0; i < n; ++i) {
            pickBest(mv, sc, n, i);
            const Move m = mv[i];
            if (m.captured == KING) {
                if (ply == 0) rootBest_ = m;
                return MATE - ply;
            }
            const Undo u = pos_.make(m);
            const int s = -search(depth - 1, -beta, -alpha, ply + 1);
            pos_.unmake(m, u);
            if (stop_) return 0;

            if (s > best) {
                best = s;
                bestMove = m;
                if (s > alpha) {
                    alpha = s;
                    if (ply == 0) rootBest_ = m;
                }
            }
            if (alpha >= beta) {
                if (m.captured == NONE) history_[us][m.from][m.to] += depth * depth;
                break;
            }
        }

        e.key = pos_.hash;
        e.score = toTT(best, ply);
        e.move = bestMove.packed();
        e.depth = static_cast<std::int8_t>(depth);
        e.flag = best <= alphaOrig ? UPPER : best >= beta ? LOWER : EXACT;
        return best;
    }

    Position pos_;
    std::vector<TTEntry> tt_;
    U64 mask_;
    int history_[2][64][64]{};
    Move rootBest_;
    int rootDepth_ = 0;
    std::uint64_t nodes_ = 0;
    bool stop_ = false;
    std::chrono::steady_clock::time_point start_, deadline_;
};

// ---------------------------------------------------------------------------
// Self-play
// ---------------------------------------------------------------------------
Position simGame(Position position, double moveTime = 4.5, int maxPlies = 100) {
    Engine engine;
    for (int ply = 0; ply < maxPlies; ++ply) {
        const Engine::Result r = engine.think(position, moveTime);
        if (!r.valid) break;
        position.make(r.move);
        position.print();
        std::printf("%s to move\n", position.side == WHITE ? "White" : "Black");
        if (r.move.captured == KING) {
            std::printf("King captured - game over\n");
            break;
        }
    }
    return position;
}

// ---------------------------------------------------------------------------
// Server mode: one command per line on stdin, one reply per line on stdout.
// <state> is four tokens: "<board64> <w|b> <castling KQkq|-> <ep square|->".
//   status <state>              -> "status <whiteInCheck> <blackInCheck> f,t f,t ..." (side to move's moves)
//   go     <state> <seconds>    -> "bestmove f t score depth" | "bestmove none"
//   apply  <state> <from> <to>  -> "state <new state>"   (handles castling / en passant)
//   ping                        -> "pong"
//   quit
// Squares are 0..63 (row*8+col, row 0 = white back rank).
// ---------------------------------------------------------------------------
static bool readState(std::istringstream& in, Position& p) {
    std::string board, side, castle, ep;
    in >> board >> side >> castle >> ep;
    return !ep.empty() && p.fromState(board, side[0], castle, ep);
}

void serve() {
    Engine engine;
    std::string line;
    while (std::getline(std::cin, line)) {
        while (!line.empty() && (line.back() == '\r' || line.back() == ' ')) line.pop_back();
        std::istringstream in(line);
        std::string cmd;
        in >> cmd;
        if (cmd.empty()) continue;
        if (cmd == "quit") break;
        if (cmd == "ping") {
            std::cout << "pong" << std::endl;
            continue;
        }
        if (cmd != "status" && cmd != "go" && cmd != "apply") {
            std::cout << "error unknown_command" << std::endl;
            continue;
        }

        Position p;
        if (!readState(in, p)) {
            std::cout << "error bad_position" << std::endl;
            continue;
        }

        if (cmd == "status") {
            Move mv[256];
            const int n = p.generate<false>(mv);
            std::cout << "status " << p.kingAttacked(WHITE) << ' ' << p.kingAttacked(BLACK);
            for (int i = 0; i < n; ++i) std::cout << ' ' << int(mv[i].from) << ',' << int(mv[i].to);
            std::cout << std::endl;
        } else if (cmd == "go") {
            double seconds = 1.0;
            in >> seconds;
            const Engine::Result r = engine.think(p, seconds, 40, false);
            if (!r.valid)
                std::cout << "bestmove none" << std::endl;
            else
                std::cout << "bestmove " << int(r.move.from) << ' ' << int(r.move.to) << ' ' << r.score << ' '
                          << r.depth << std::endl;
        } else {
            int from = -1, to = -1;
            in >> from >> to;
            Move mv[256];
            const int n = p.generate<false>(mv);
            bool done = false;
            for (int i = 0; i < n && !done; ++i)
                if (mv[i].from == from && mv[i].to == to) {
                    p.make(mv[i]);
                    std::cout << "state " << p.toState() << std::endl;
                    done = true;
                }
            if (!done) std::cout << "error illegal_move" << std::endl;
        }
    }
}

}  // namespace chess

int main(int argc, char** argv) {
    if (argc > 1 && std::string(argv[1]) == "--serve") {
        chess::serve();
        return 0;
    }
    const double moveTime = argc > 1 ? std::atof(argv[1]) : 4.5;
    const int maxPlies = argc > 2 ? std::atoi(argv[2]) : 100;
    chess::simGame(chess::Position::initial(), moveTime, maxPlies);
    return 0;
}
