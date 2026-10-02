"""Run: py server.py  -> friends on the same Wi-Fi open http://<printed-ip>:8080"""
import asyncio, json, os, socket, uuid
from pathlib import Path
from aiohttp import web, WSMsgType
from teenpatti import TeenPatti

GAMES = {"teenpatti": TeenPatti}  # add bluff, sequence, ... here
MAX_PLAYERS = 12
GRACE = 120  # seconds a disconnected player (phone tabbed out) keeps their seat
HERE = Path(__file__).parent
LB_FILE = HERE / "leaderboard.json"  # {game: {player name: wins}}
# code -> {"players": {pid: [name, ws|None]}, "host": pid, "game": obj|None, "kind": str, "rec": bool, "timers": {pid: handle}}
ROOMS = {}


def load_lb():
    try:
        return json.loads(LB_FILE.read_text())
    except (OSError, ValueError):
        return {}


def record(room):
    """Credit a win once per finished game."""
    g = room["game"]
    if g and g.phase == "over" and not room["rec"]:
        room["rec"] = True
        lb = load_lb()
        for name in g.winners:
            lb.setdefault(room["kind"], {})
            lb[room["kind"]][name] = lb[room["kind"]].get(name, 0) + 1
        try:
            LB_FILE.write_text(json.dumps(lb, indent=1))
        except OSError:  # read-only or ephemeral disk: the leaderboard is just for show
            pass


async def push(code):
    r = ROOMS[code]
    names = {p: v[0] for p, v in r["players"].items()}
    off = [p for p, v in r["players"].items() if v[1] is None]
    lb = load_lb()
    for pid, (_, ws) in list(r["players"].items()):
        if ws is None or ws.closed:
            continue
        try:
            await ws.send_json({"t": "state", "me": pid, "room": code, "host": r["host"], "names": names, "off": off,
                                "lb": lb, "kind": r["kind"], "games": list(GAMES),
                                "game": r["game"].view(pid) if r["game"] else None})
        except (ConnectionError, RuntimeError):
            pass


async def leave(code, pid):
    r = ROOMS.get(code)
    if not r or pid not in r["players"]:
        return
    del r["players"][pid]
    if t := r["timers"].pop(pid, None):
        t.cancel()
    if r["game"]:
        r["game"].drop(pid)
        record(r)
    if not r["players"]:
        del ROOMS[code]
    else:
        if r["host"] == pid:
            r["host"] = next(iter(r["players"]))
        await push(code)


async def ws_handler(req):
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(req)
    pid = code = None
    async for msg in ws:
        if msg.type != WSMsgType.TEXT:
            continue
        d = json.loads(msg.data)
        t, err = d.get("t"), None
        if code and code not in ROOMS:
            code = pid = None
        r = ROOMS.get(code)
        if t == "join" and not code:
            c = d["room"].strip().lower()[:12] or "room"
            r = ROOMS.setdefault(c, {"players": {}, "host": None, "game": None, "kind": "", "rec": False, "timers": {}})
            if len(r["players"]) >= MAX_PLAYERS or r["game"]:
                err = "room is full or the game already started"
                if not r["players"]:
                    del ROOMS[c]
            else:
                code, pid = c, uuid.uuid4().hex[:6]
                r["players"][pid] = [d["name"].strip()[:16] or "Player", ws]
                r["host"] = r["host"] or pid
        elif t == "resume" and not code:
            r = ROOMS.get(d.get("room"))
            if r and d.get("pid") in r["players"]:
                code, pid = d["room"], d["pid"]
                r["players"][pid][1] = ws
                if h := r["timers"].pop(pid, None):
                    h.cancel()
            else:
                await ws.send_json({"t": "expired"})
        elif r and t == "start" and r["host"] == pid:
            cls = GAMES.get(d.get("game"))
            n = len(r["players"])
            if not cls or not cls.min_players <= n <= cls.max_players:
                err = f"{d.get('game')} needs {cls.min_players}-{cls.max_players} players, you have {n}" if cls else "unknown game"
            else:
                rounds = max(0, min(int(d.get("rounds") or 0), 50))
                r.update(kind=d["game"], rec=False, game=cls({p: v[0] for p, v in r["players"].items()}, rounds))
        elif r and t == "act" and r["game"]:
            err = r["game"].act(pid, d)
        elif r and t == "end" and r["host"] == pid and r["game"]:
            r["game"].end()
        elif r and t == "lobby" and r["host"] == pid:
            r["game"] = None
        elif r and t == "leave":
            await leave(code, pid)
            code = pid = None
            await ws.send_json({"t": "left"})
            continue
        if code and code in ROOMS:
            record(ROOMS[code])
        if err:
            await ws.send_json({"t": "err", "m": err})
        if code and code in ROOMS:
            await push(code)  # also answers t == "sync"
    r = ROOMS.get(code)
    if r and pid in r["players"] and r["players"][pid][1] is ws:  # not already replaced by a reconnect
        r["players"][pid][1] = None
        r["timers"][pid] = asyncio.get_running_loop().call_later(GRACE, lambda: asyncio.ensure_future(leave(code, pid)))
        await push(code)
    return ws


async def rooms(req):
    return web.json_response([
        {"code": c, "n": len(r["players"]), "kind": r["kind"], "started": bool(r["game"]), "host": r["players"][r["host"]][0]}
        for c, r in ROOMS.items() if r["players"]])


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packet sent
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


app = web.Application()
app.add_routes([web.get("/ws", ws_handler), web.get("/rooms", rooms), web.get("/health", lambda r: web.Response(text="ok")),
                web.get("/", lambda r: web.FileResponse(HERE / "index.html", headers={"Cache-Control": "no-store"}))])

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))  # hosts like Render set PORT
    print(f"Friends open: http://{lan_ip()}:{port}")
    web.run_app(app, port=port, print=None)
