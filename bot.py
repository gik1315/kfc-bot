import asyncio, hmac, hashlib, urllib.parse, json, os, time, logging, html
from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.utils.deep_linking import create_start_link
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

API_TOKEN = os.environ["BOT_TOKEN"]
WEBAPP_URL = "https://gik1315.github.io/kfc-gap-webapp/"
ALLOWED_ORIGIN = "https://gik1315.github.io"
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
gap_sessions = {}


def esc(x):
    return html.escape(str(x))


def menu_button(sid):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text="🍗 Menyuni ochish",
        web_app=WebAppInfo(url=f"{WEBAPP_URL}?session_id={sid}"))]])


@dp.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject):
    payload = command.args
    if payload and payload.startswith("gap_"):
        s = gap_sessions.get(payload)
        if not s:
            await message.answer("❌ Bu KFC Gap sessiyasi topilmadi yoki muddati tugagan. Tashkilotchidan yangi havola so'rang.")
            return
        await message.answer(
            f"🍗 <b>{esc(s['host_name'])}ning KFC Gapiga xush kelibsiz!</b>\n\n"
            "Menyuni oching, taomlarni tanlang va «Tayyor» tugmasini bosing. "
            "Hamma ishtirokchilar tanlovi o'sha yerda ko'rinib turadi.",
            reply_markup=menu_button(payload), parse_mode="HTML")
    else:
        await message.answer(
            "🍗 <b>KFC Gap Jamoaviy Buyurtma Tizimi</b>\n\n"
            "Do'stlaringiz bilan bitta umumiy buyurtma tuzing.\n\n"
            "Yangi buyurtma xonasi ochish uchun tugmani bosing 👇",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🎉 Yangi KFC Gap Boshlash", callback_data="create_gap")
            ]]),
            parse_mode="HTML")


@dp.callback_query(lambda c: c.data == "create_gap")
async def create_gap_session(callback: types.CallbackQuery):
    sid = f"gap_{callback.from_user.id}_{int(time.time())}"
    gap_sessions[sid] = {
        "host_id": callback.from_user.id,
        "host_name": callback.from_user.first_name,
        "status": "open",
        "card": "",
        "finished": False,
        "people": {},
    }
    join_link = await create_start_link(bot, sid, encode=False)
    text = (
        "🔥 <b>KFC Gap sessiyasi ochildi!</b>\n\n"
        f"1️⃣ Havolani do'stlaringizga yuboring:\n<code>{join_link}</code>\n\n"
        "2️⃣ Pastdagi tugma bilan o'zingiz ham menyuni oching.\n\n"
        "3️⃣ Hamma «Tayyor» bosgach, menyu ichida «To'lovga o'tish» tugmasi chiqadi."
    )
    await callback.message.edit_text(text, reply_markup=menu_button(sid), parse_mode="HTML")
    await callback.answer()


def verify_init_data(init_data: str):
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        received = parsed.pop("hash", None)
        check = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret = hmac.new(b"WebAppData", API_TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not received or not hmac.compare_digest(calc, received):
            return None
        return json.loads(parsed["user"])
    except Exception:
        return None


def clean_items(raw):
    items = []
    for i in (raw or [])[:60]:
        try:
            items.append({"name": str(i["name"])[:60], "price": int(i["price"])})
        except Exception:
            pass
    return items


def state_view(s, uid):
    return {
        "ok": True,
        "me": uid,
        "host_id": s["host_id"],
        "host_name": s["host_name"],
        "status": s["status"],
        "card": s["card"] if s["status"] == "payment" else "",
        "people": [
            {"uid": u, "name": p["name"], "items": p["items"], "done": p["done"],
             "method": p["method"], "paid": p["paid"]}
            for u, p in s["people"].items()
        ],
    }


async def maybe_finish(s):
    if s.get("finished") or not s["people"]:
        return
    if not all(p["paid"] for p in s["people"].values()):
        return
    s["finished"] = True
    master, total = {}, 0
    for p in s["people"].values():
        for it in p["items"]:
            m = master.setdefault(it["name"], {"qty": 0, "sum": 0})
            m["qty"] += 1
            m["sum"] += it["price"]
            total += it["price"]
    t = "🎉 <b>Hamma to'ladi!</b>\n\n📦 <b>Kassada shu savat bilan buyurtma bering:</b>\n"
    for n, m in master.items():
        t += f" ▪️ {esc(n)} × {m['qty']} — {m['sum']:,} UZS\n"
    t += f"\n🔴 <b>Jami: {total:,} UZS</b>"
    try:
        await bot.send_message(s["host_id"], t, parse_mode="HTML")
    except Exception as e:
        logging.warning(f"host notify failed: {e}")


@web.middleware
async def cors(request, handler):
    resp = web.Response() if request.method == "OPTIONS" else await handler(request)
    resp.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGIN
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


async def api_sync(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False}, status=400)
    user = verify_init_data(body.get("initData", ""))
    if not user:
        return web.json_response({"ok": False, "error": "auth"}, status=401)
    s = gap_sessions.get(body.get("session_id"))
    if not s:
        return web.json_response({"ok": False, "error": "no_session"}, status=404)

    uid = user["id"]
    is_host = uid == s["host_id"]
    p = s["people"].get(uid)
    if p is None and s["status"] == "open":
        p = s["people"][uid] = {
            "name": user.get("first_name", "?"), "items": [],
            "done": False, "method": None, "paid": False}

    if p is not None and s["status"] == "open":
        if "items" in body and not p["done"]:
            p["items"] = clean_items(body["items"])
        if "done" in body:
            p["done"] = bool(body["done"]) and bool(p["items"])

    action = body.get("action")
    if action == "start_payment" and is_host and s["status"] == "open":
        active = [x for x in s["people"].values() if x["items"]]
        if active and all(x["done"] for x in active):
            s["card"] = str(body.get("card", ""))[:40].strip()
            s["people"] = {u: x for u, x in s["people"].items() if x["items"]}
            s["status"] = "payment"
            hp = s["people"].get(uid)
            if hp:
                hp["paid"] = True
                hp["method"] = "host"
    elif action == "pay" and s["status"] == "payment" and p is not None and not p["paid"]:
        if body.get("method") in ("card", "cash"):
            p["method"] = body["method"]
    elif action == "confirm" and is_host and s["status"] == "payment":
        try:
            target = s["people"].get(int(body.get("target")))
        except Exception:
            target = None
        if target:
            target["paid"] = True
            await maybe_finish(s)

    return web.json_response(state_view(s, uid))


async def health(request):
    return web.Response(text="ok")


async def main():
    app = web.Application(middlewares=[cors])
    app.router.add_get("/", health)
    app.router.add_route("*", "/api/sync", api_sync)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
