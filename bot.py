import asyncio, hmac, hashlib, urllib.parse, json, os, time, logging, html
from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.utils.deep_linking import create_start_link
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

API_TOKEN = os.environ["BOT_TOKEN"]
WEBAPP_URL = "https://luvwnqw-jpg.github.io/kfc-gap-webapp/"
ALLOWED_ORIGIN = "https://luvwnqw-jpg.github.io"
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
gap_sessions = {}


def esc(x):
    return html.escape(str(x))


def menu_markup(session_id):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text="🍗 Menyuni ochish",
        web_app=WebAppInfo(url=f"{WEBAPP_URL}?session_id={session_id}"))]])


def render_board(s) -> str:
    master, total = {}, 0
    for o in s["orders"].values():
        for it in o["items"]:
            m = master.setdefault(it["name"], {"qty": 0, "sum": 0})
            m["qty"] += 1
            m["sum"] += it["price"]
            total += it["price"]
    t = f"🍗 <b>{esc(s['host_name'])}ning KFC Gapi</b>\n───────────────\n"
    if not s["orders"]:
        return t + "Hali hech kim tanlamadi…"
    t += "👤 <b>Kim nima tanladi:</b>\n"
    for o in s["orders"].values():
        sub = sum(i["price"] for i in o["items"])
        names = ", ".join(esc(i["name"]) for i in o["items"])
        t += f"• <b>{esc(o['name'])}</b> — {sub:,} UZS\n   {names}\n"
    t += "\n📦 <b>Umumiy savat:</b>\n"
    for n, m in master.items():
        t += f" ▪️ {esc(n)} × {m['qty']} — {m['sum']:,} UZS\n"
    return t + f"\n🔴 <b>Jami: {total:,} UZS</b>"


async def refresh_board(session_id):
    s = gap_sessions[session_id]
    for chat_id, msg_id in list(s["watchers"]):
        try:
            await bot.edit_message_text(render_board(s), chat_id=chat_id, message_id=msg_id,
                                        reply_markup=menu_markup(session_id), parse_mode="HTML")
        except Exception as e:
            logging.warning(f"edit failed: {e}")


@dp.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject):
    payload = command.args
    if payload and payload.startswith("gap_"):
        s = gap_sessions.get(payload)
        if not s:
            await message.answer("❌ Bu KFC Gap sessiyasi topilmadi yoki muddati tugagan. Iltimos, yangi gap boshlang.")
            return
        sent = await message.answer(render_board(s), reply_markup=menu_markup(payload), parse_mode="HTML")
        s["watchers"].append((sent.chat.id, sent.message_id))
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
    session_id = f"gap_{callback.from_user.id}_{int(time.time())}"
    gap_sessions[session_id] = {
        "host_id": callback.from_user.id,
        "host_name": callback.from_user.first_name,
        "orders": {},
        "watchers": [],
    }
    join_link = await create_start_link(bot, session_id, encode=False)
    text = (
        "🔥 <b>KFC Gap sessiyasi ochildi!</b>\n\n"
        f"1️⃣ Havolani guruhga yuboring:\n<code>{join_link}</code>\n\n"
        "2️⃣ Do'stlaringiz havola orqali kirib taom tanlashadi.\n\n"
        "3️⃣ Hamma tanlab bo'lgach, «Jami hisob» tugmasini bosing."
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Jami hisobni chiqarish", callback_data=f"total_{session_id}")]
    ])
    await callback.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    sent = await callback.message.answer(render_board(gap_sessions[session_id]),
                                         reply_markup=menu_markup(session_id), parse_mode="HTML")
    gap_sessions[session_id]["watchers"].append((sent.chat.id, sent.message_id))
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("total_"))
async def calculate_gap_total(callback: types.CallbackQuery):
    session_id = callback.data.replace("total_", "")
    s = gap_sessions.get(session_id)
    if not s or not s["orders"]:
        await callback.answer("⚠️ Hali hech kim taom tanlamadi!", show_alert=True)
        return
    await callback.message.answer(render_board(s) + "\n\n✨ <i>Osh bo'lsin!</i>", parse_mode="HTML")
    await callback.answer()


def verify_init_data(init_data: str):
    parsed = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
    received = parsed.pop("hash", None)
    check = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret = hmac.new(b"WebAppData", API_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not received or not hmac.compare_digest(calc, received):
        return None
    return json.loads(parsed["user"])


@web.middleware
async def cors(request, handler):
    resp = web.Response() if request.method == "OPTIONS" else await handler(request)
    resp.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGIN
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    return resp


async def api_order(request):
    body = await request.json()
    user = verify_init_data(body.get("initData", ""))
    s = gap_sessions.get(body.get("session_id"))
    if not user or not s:
        return web.json_response({"ok": False}, status=400)
    s["orders"][user["id"]] = {"name": user.get("first_name", "?"), "items": body.get("items", [])}
    await refresh_board(body["session_id"])
    return web.json_response({"ok": True})


async def health(request):
    return web.Response(text="ok")


async def main():
    app = web.Application(middlewares=[cors])
    app.router.add_get("/", health)
    app.router.add_route("*", "/api/order", api_order)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
