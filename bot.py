import asyncio, hmac, hashlib, urllib.parse, json, os, time, logging, html
from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.utils.deep_linking import create_start_link
from aiogram.filters import CommandStart, CommandObject, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

API_TOKEN = os.environ["BOT_TOKEN"]
WEBAPP_URL = "https://gik1315.github.io/kfc-gap-webapp/"
ALLOWED_ORIGIN = "https://gik1315.github.io"
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
gap_sessions = {}
host_cards = {}


def esc(x):
    return html.escape(str(x))


def user_total(o):
    return sum(i["price"] for i in o["items"])


def board_markup(sid, s, chat_id):
    rows = []
    if s["status"] == "open":
        rows.append([InlineKeyboardButton(
            text="🍗 Menyuni ochish",
            web_app=WebAppInfo(url=f"{WEBAPP_URL}?session_id={sid}"))])
        if chat_id == s["host_id"]:
            rows.append([InlineKeyboardButton(
                text="📋 Tekshirish va to'lovga o'tish",
                callback_data=f"review_{sid}")])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def render_board(s) -> str:
    master, total = {}, 0
    for o in s["orders"].values():
        for it in o["items"]:
            m = master.setdefault(it["name"], {"qty": 0, "sum": 0})
            m["qty"] += 1
            m["sum"] += it["price"]
            total += it["price"]
    status = "🟢 Buyurtma ochiq" if s["status"] == "open" else "💳 To'lov bosqichi"
    t = f"🍗 <b>{esc(s['host_name'])}ning KFC Gapi</b>\n{status}\n───────────────\n"
    if not s["orders"]:
        return t + "Hali hech kim tanlamadi…"
    t += "👤 <b>Kim nima tanladi:</b>\n"
    for o in s["orders"].values():
        mark = ""
        if s["status"] == "payment":
            mark = " ✅" if o["paid"] else " ⏳"
        names = ", ".join(esc(i["name"]) for i in o["items"])
        t += f"• <b>{esc(o['name'])}</b>{mark} — {user_total(o):,} UZS\n   {names}\n"
    t += "\n📦 <b>Umumiy savat:</b>\n"
    for n, m in master.items():
        t += f" ▪️ {esc(n)} × {m['qty']} — {m['sum']:,} UZS\n"
    return t + f"\n🔴 <b>Jami: {total:,} UZS</b>"


async def refresh_board(sid):
    s = gap_sessions[sid]
    text = render_board(s)
    for chat_id, msg_id in list(s["watchers"]):
        try:
            await bot.edit_message_text(
                text, chat_id=chat_id, message_id=msg_id,
                reply_markup=board_markup(sid, s, chat_id), parse_mode="HTML")
        except Exception as e:
            logging.warning(f"edit failed: {e}")


def add_watcher(s, sent):
    s["watchers"] = [w for w in s["watchers"] if w[0] != sent.chat.id]
    s["watchers"].append((sent.chat.id, sent.message_id))


@dp.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject):
    payload = command.args
    if payload and payload.startswith("gap_"):
        s = gap_sessions.get(payload)
        if not s:
            await message.answer("❌ Bu KFC Gap sessiyasi topilmadi yoki muddati tugagan. Iltimos, yangi gap boshlang.")
            return
        sent = await message.answer(
            render_board(s), reply_markup=board_markup(payload, s, message.chat.id),
            parse_mode="HTML")
        add_watcher(s, sent)
    else:
        await message.answer(
            "🍗 <b>KFC Gap Jamoaviy Buyurtma Tizimi</b>\n\n"
            "Do'stlaringiz bilan bitta umumiy buyurtma tuzing.\n\n"
            "Yangi buyurtma xonasi ochish uchun tugmani bosing 👇",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🎉 Yangi KFC Gap Boshlash", callback_data="create_gap")
            ]]),
            parse_mode="HTML")


@dp.message(Command("card"))
async def cmd_card(message: types.Message, command: CommandObject):
    if not command.args:
        await message.answer("Karta raqamingizni shunday yuboring:\n/card 8600 1234 5678 9012")
        return
    host_cards[message.from_user.id] = command.args.strip()
    await message.answer("✅ Karta saqlandi. Endi to'lov bosqichiga o'tishingiz mumkin.")


@dp.callback_query(lambda c: c.data == "create_gap")
async def create_gap_session(callback: types.CallbackQuery):
    sid = f"gap_{callback.from_user.id}_{int(time.time())}"
    gap_sessions[sid] = {
        "host_id": callback.from_user.id,
        "host_name": callback.from_user.first_name,
        "status": "open",
        "orders": {},
        "watchers": [],
    }
    s = gap_sessions[sid]
    join_link = await create_start_link(bot, sid, encode=False)
    text = (
        "🔥 <b>KFC Gap sessiyasi ochildi!</b>\n\n"
        f"1️⃣ Havolani guruhga yuboring:\n<code>{join_link}</code>\n\n"
        "2️⃣ Do'stlaringiz havola orqali kirib taom tanlashadi.\n\n"
        "3️⃣ To'lov uchun karta raqamingizni yuboring:\n<code>/card 8600 1234 5678 9012</code>\n\n"
        "4️⃣ Hamma tanlab bo'lgach, pastdagi xabarda «Tekshirish» tugmasini bosing."
    )
    await callback.message.edit_text(text, parse_mode="HTML")
    sent = await callback.message.answer(
        render_board(s), reply_markup=board_markup(sid, s, callback.message.chat.id),
        parse_mode="HTML")
    add_watcher(s, sent)
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("review_"))
async def review(callback: types.CallbackQuery):
    sid = callback.data[len("review_"):]
    s = gap_sessions.get(sid)
    if not s or callback.from_user.id != s["host_id"]:
        await callback.answer("Faqat tashkilotchi bosa oladi", show_alert=True)
        return
    if not s["orders"]:
        await callback.answer("⚠️ Hali hech kim taom tanlamadi!", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Ha, to'lovga o'tish", callback_data=f"confirm_{sid}")],
        [InlineKeyboardButton(text="↩️ Orqaga", callback_data=f"back_{sid}")],
    ])
    await callback.message.answer(
        "🔍 <b>Iltimos, tekshiring!</b>\n\n" + render_board(s) +
        "\n\nHammasi to'g'rimi? Tasdiqlasangiz buyurtma yopiladi va "
        "hamma a'zolarga to'lov so'rovi yuboriladi.",
        reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("back_"))
async def back(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("confirm_"))
async def confirm(callback: types.CallbackQuery):
    sid = callback.data[len("confirm_"):]
    s = gap_sessions.get(sid)
    if not s or callback.from_user.id != s["host_id"]:
        await callback.answer("Faqat tashkilotchi bosa oladi", show_alert=True)
        return
    if s["status"] != "open":
        await callback.answer("Buyurtma allaqachon yopilgan", show_alert=True)
        return
    card = host_cards.get(s["host_id"])
    if not card:
        await callback.answer("Avval karta raqamingizni yuboring: /card 8600 1234 5678 9012", show_alert=True)
        return
    s["status"] = "payment"
    for uid, o in s["orders"].items():
        if uid == s["host_id"]:
            o["paid"] = True
            continue
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ To'ladim", callback_data=f"paid_{sid}")]])
        try:
            await bot.send_message(
                uid,
                f"💳 <b>To'lov vaqti!</b>\n\n"
                f"<b>{esc(s['host_name'])}</b> ga o'tkazing:\n"
                f"💰 <b>{user_total(o):,} UZS</b>\n"
                f"🏦 Karta: <code>{esc(card)}</code>\n\n"
                f"To'lab bo'lgach, tugmani bosing 👇",
                reply_markup=kb, parse_mode="HTML")
        except Exception as e:
            logging.warning(f"could not message {uid}: {e}")
    await refresh_board(sid)
    await callback.message.edit_text("✅ Buyurtma yopildi. To'lov so'rovlari yuborildi.")
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("paid_"))
async def paid(callback: types.CallbackQuery):
    sid = callback.data[len("paid_"):]
    s = gap_sessions.get(sid)
    o = s["orders"].get(callback.from_user.id) if s else None
    if not o:
        await callback.answer("Buyurtma topilmadi", show_alert=True)
        return
    o["paid"] = True
    await callback.message.edit_text("✅ To'lov belgilandi. Rahmat!")
    await refresh_board(sid)
    done = sum(1 for x in s["orders"].values() if x["paid"])
    total = len(s["orders"])
    try:
        await bot.send_message(
            s["host_id"], f"✅ <b>{esc(o['name'])}</b> to'ladi ({done}/{total})",
            parse_mode="HTML")
        if done == total:
            await bot.send_message(
                s["host_id"],
                "🎉 <b>Hamma to'ladi!</b> Kassada shu savat bilan buyurtma bering:\n\n" + render_board(s),
                parse_mode="HTML")
    except Exception as e:
        logging.warning(f"host notify failed: {e}")
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
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


async def api_order(request):
    body = await request.json()
    user = verify_init_data(body.get("initData", ""))
    sid = body.get("session_id")
    s = gap_sessions.get(sid)
    if not user or not s:
        return web.json_response({"ok": False}, status=400)
    if s["status"] != "open":
        return web.json_response({"ok": False, "error": "closed"}, status=409)
    items = []
    for i in body.get("items", [])[:50]:
        try:
            items.append({"name": str(i["name"])[:60], "price": int(i["price"])})
        except Exception:
            pass
    if items:
        s["orders"][user["id"]] = {
            "name": user.get("first_name", "?"), "items": items, "paid": False}
    else:
        s["orders"].pop(user["id"], None)
    await refresh_board(sid)
    return web.json_response({"ok": True})


async def api_session(request):
    s = gap_sessions.get(request.query.get("session_id"))
    if not s:
        return web.json_response({"ok": False}, status=404)
    orders = [
        {"uid": uid, "name": o["name"], "items": o["items"], "paid": o["paid"]}
        for uid, o in s["orders"].items()
    ]
    return web.json_response({
        "ok": True, "host_name": s["host_name"],
        "status": s["status"], "orders": orders})


async def health(request):
    return web.Response(text="ok")


async def main():
    app = web.Application(middlewares=[cors])
    app.router.add_get("/", health)
    app.router.add_route("*", "/api/order", api_order)
    app.router.add_route("*", "/api/session", api_session)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
