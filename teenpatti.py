"""Teen Patti (Shithead/Palace style). Game interface: __init__(names, rounds), act(pid, msg), drop(pid), end(), view(pid)."""
import random
from math import ceil

LABEL = {11: "J", 12: "Q", 13: "K", 14: "A"}


class TeenPatti:
    min_players, max_players = 2, 12

    def __init__(self, names, rounds=3):
        self.names, self.rounds = names, rounds  # rounds=0: play until host ends
        self.order = list(names)
        self.score = {p: 0 for p in names}
        self.round, self.phase, self.result, self.log, self.winners = 0, "play", "", "", []
        self.deal()

    # --- setup ---
    def deal(self):
        if len(self.order) < 2:
            return self._finish()
        self.round += 1
        n = len(self.order)
        deck = [(r, s) for r in range(2, 15) for s in "SHDC"] * ceil((n * 9 + 8) / 52)  # ponytail: extra decks for big tables
        random.shuffle(deck)
        take = lambda k: [deck.pop() for _ in range(k)]
        self.down = {p: take(3) for p in self.order}
        self.up = {p: take(3) for p in self.order}
        self.hand = {p: take(3) for p in self.order}
        for p in self.order:
            self._sort(p)
        self.deck, self.pile, self.burned, self.out, self.fin = deck, [], 0, set(), []
        self.turn = self.order[(self.round - 1) % n]
        self.phase, self.result, self.log = "play", "", f"Round {self.round}"

    def _sort(self, p):
        self.hand[p].sort()

    # --- rules ---
    def ok(self, r):
        if r in (2, 10) or not self.pile:
            return True
        t = self.pile[-1][0]
        return r <= 7 if t == 7 else (t == 2 or r >= t)  # 7: next must go lower, 2: reset

    def canup(self, p):
        return not self.deck and len(self.hand[p]) < 2 and bool(self.up[p])

    def _next(self, p):
        i = self.order.index(p)
        for k in range(1, len(self.order) + 1):
            q = self.order[(i + k) % len(self.order)]
            if q not in self.out:
                return q

    def _active(self):
        return [p for p in self.order if p not in self.out]

    def _place(self, pid, cards):
        r = cards[-1][0]
        self.pile += cards
        burn = r == 10 or (len(self.pile) >= 4 and len({c[0] for c in self.pile[-4:]}) == 1)
        self.log = f"{self.names[pid]} played {LABEL.get(r, r)}{'' if r == 2 or cards[0][0] != 2 else ' (with a 2)'}" + (f" x{len(cards)}" if len(cards) > 1 and cards[0][0] == r else "") + (" 🔥 burn!" if burn else "")
        if burn:
            self.burned += len(self.pile)
            self.pile = []
        while self.deck and len(self.hand[pid]) < 3:
            self.hand[pid].append(self.deck.pop())
        self._sort(pid)
        if not (self.hand[pid] or self.up[pid] or self.down[pid]):
            self.out.add(pid)
            self.fin.append(pid)
        if len(self._active()) <= 1:
            return self._round_end()
        self._go(pid if burn and pid not in self.out else self._next(pid))

    def _go(self, p):
        """Pass the turn; a player with no playable card automatically takes the pile."""
        self.turn = p
        blind = not self.hand[p] and not self.up[p]
        pool = self.hand[p] + (self.up[p] if self.canup(p) else [])
        if self.pile and not blind and not any(self.ok(c[0]) for c in pool):
            self._pickup(p)
            self.log += " (no valid card)"

    def _pickup(self, pid, extra=()):
        self.hand[pid] += self.pile + list(extra)
        self.pile = []
        self._sort(pid)
        self.log = f"{self.names[pid]} picked up the pile"
        self._go(self._next(pid))

    def _round_end(self):
        act = self._active()
        if self.fin:
            self.score[self.fin[0]] += 1
        loser = f" — {self.names[act[0]]} is last" if act else ""
        self.result = f"{self.names[self.fin[0]] if self.fin else '-'} wins the round{loser}"
        self.phase = "round_end"
        if self.rounds and self.round >= self.rounds:
            self._finish()

    def _finish(self):
        top = max(self.score.values(), default=0)
        self.winners = [self.names[p] for p, s in self.score.items() if s == top] if top else []
        self.result = (self.result + " | " if self.result else "") + ("Winner: " + ", ".join(self.winners) if self.winners else "No winner")
        self.phase = "over"

    def end(self):
        if self.phase != "over":
            self._finish()

    def drop(self, pid):
        if pid not in self.order:
            return
        if self.phase == "play" and pid not in self.out:
            self.out.add(pid)
            if self.turn == pid:
                self.turn = self._next(pid)
            self.burned += len(self.hand[pid]) + len(self.up[pid]) + len(self.down[pid])
        self.order.remove(pid)
        self.out.discard(pid)
        if self.phase == "play" and len(self._active()) <= 1:
            self._round_end()
        elif len(self.order) < 2 and self.phase != "over":
            self._finish()

    # --- actions ---
    def act(self, pid, m):
        a = m.get("a")
        if self.phase == "round_end":
            if a == "next":
                self.deal()
                return None
            return "round is over"
        if self.phase != "play":
            return "game is over"
        if self.turn != pid:
            return "not your turn"
        if a == "take":
            if not self.pile:
                return "pile is empty"
            self._pickup(pid)
        elif a == "play":
            src = self.hand[pid] if m.get("src") == "hand" else self.up[pid] if m.get("src") == "up" and self.canup(pid) else None
            if src is None:
                return "can't play from there"
            try:
                idx = sorted({int(i) for i in m.get("idx", [])})
                cards = [src[i] for i in idx]
            except (ValueError, IndexError, TypeError):
                return "bad selection"
            twos, rest = [c for c in cards if c[0] == 2], [c for c in cards if c[0] != 2]
            if not cards or len({c[0] for c in rest}) > 1:
                return "pick cards of one rank (2s can go with any card)"
            if rest and not twos and not self.ok(rest[0][0]):
                return "can't play that on the pile"
            cards = twos + rest  # a 2 lets any card sit on top of it
            for i in reversed(idx):
                del src[i]
            self._place(pid, cards)
        elif a == "down":
            if self.hand[pid] or self.up[pid] or not self.down[pid]:
                return "not yet"
            c = self.down[pid].pop(random.randrange(len(self.down[pid])))
            if self.ok(c[0]):
                self._place(pid, [c])
            else:
                self._pickup(pid, [c])
                self.log += f" (blind {LABEL.get(c[0], c[0])} failed)"
        else:
            return "unknown action"
        return None

    def view(self, pid):
        return {
            "phase": self.phase, "round": self.round, "rounds": self.rounds, "result": self.result, "log": self.log,
            "turn": self.turn if self.phase == "play" else None, "pile": self.pile[-5:], "pile_n": len(self.pile),
            "deck_n": len(self.deck), "burned": self.burned, "winners": self.winners,
            "ok": [r for r in range(2, 15) if self.ok(r)],
            "players": [{"id": p, "name": self.names[p], "hand": len(self.hand[p]), "up": self.up[p],
                         "down": len(self.down[p]), "out": p in self.out, "score": self.score[p]} for p in self.order],
            "hand": self.hand.get(pid, []), "canup": pid in self.hand and self.canup(pid),
            "candown": pid in self.hand and not self.hand[pid] and not self.up[pid] and bool(self.down[pid]),
        }


if __name__ == "__main__":
    for n in (2, 5, 12):  # random-bot full games: cards conserved, rounds terminate
        g = TeenPatti({str(i): str(i) for i in range(n)}, rounds=2)
        total = len(g.deck) + sum(len(g.hand[p]) + len(g.up[p]) + len(g.down[p]) for p in g.order)
        for _ in range(100000):
            if g.phase == "over":
                break
            if g.phase == "round_end":
                g.act("0", {"a": "next"})
                continue
            p, cnt = g.turn, len(g.deck) + len(g.pile) + g.burned
            cnt += sum(len(g.hand[q]) + len(g.up[q]) + len(g.down[q]) for q in g.order)
            assert cnt == total, "cards lost"
            v = g.view(p)
            if v["candown"]:
                g.act(p, {"a": "down"})
                continue
            src, cards = ("up", g.up[p]) if v["canup"] else ("hand", g.hand[p])
            legal = [i for i, c in enumerate(cards) if g.ok(c[0])]
            if legal:
                low = min(legal, key=lambda i: cards[i][0])
                same = [i for i, c in enumerate(cards) if c[0] == cards[low][0]]
                assert g.act(p, {"a": "play", "src": src, "idx": same}) is None
            else:
                assert g.act(p, {"a": "take"}) is None
        assert g.phase == "over", f"n={n} did not finish"
    g = TeenPatti({"a": "A", "b": "B"})
    p = g.turn
    g.hand[p], g.pile = [(2, "S"), (5, "H"), (9, "D")], [(13, "S")]
    assert g.act(p, {"a": "play", "src": "hand", "idx": [1]}) and g.pile == [(13, "S")]  # 5 on K alone: rejected
    assert g.act(p, {"a": "play", "src": "hand", "idx": [0, 1]}) is None  # 2 + 5 ok
    assert g.pile[-1] == (5, "H") and g.pile[-2] == (2, "S")
    g.pile = [(7, "S")]
    assert g.ok(7) and g.ok(3) and not g.ok(9) and g.ok(10) and g.ok(2)
    g.pile = [(9, "S")]
    assert not g.ok(5) and g.ok(9) and g.ok(14)
    print("ok")
