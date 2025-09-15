# bot.py — A↔B, автосмена ролей, напоминания, многоответность, список вопросов с пагинацией и статистика
# ЛОГИКА ЗАКРЫТИЯ:
# - Частично закрыт: для того, кто ПОЛУЧИЛ ответ по номеру.
# - Полностью закрыт: когда оба получили ответы по номеру.

import os
import json
import random
import logging
from pathlib import Path
from typing import Dict, Any, List, Set

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

TOKEN = os.getenv("TELEGRAM_TOKEN")
STATE_FILE = Path(os.getenv("STATE_FILE_PATH", "state.json"))
QUESTIONS_FILE = Path("questions.txt")
TOTAL_QUESTIONS = 127
QUESTIONS_PER_PAGE = 20   # количество вопросов на странице

# ---------- STORAGE ----------
def load_state() -> Dict[str, Any]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            logging.exception("state.json read error")
    return {
        "roles": {"A": None, "B": None},
        "pending": None,
        "draft_answers": [],
        "completed_by_user": {},
        "participants": []
    }

def save_state(s: Dict[str, Any]) -> None:
    try:
        STATE_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        logging.exception("state.json write error")

def load_questions() -> List[str]:
    if QUESTIONS_FILE.exists():
        lines = [l.strip() for l in QUESTIONS_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
        if len(lines) < TOTAL_QUESTIONS:
            lines += [f"Вопрос №{i}" for i in range(len(lines)+1, TOTAL_QUESTIONS+1)]
        else:
            lines = lines[:TOTAL_QUESTIONS]
        return lines
    return [f"Вопрос №{i}" for i in range(1, TOTAL_QUESTIONS+1)]

QUESTIONS = load_questions()

# ---------- HELPERS ----------
def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Запросить конкретный вопрос", callback_data="ask_specific")],
        [InlineKeyboardButton("Запросить случайный вопрос (без повторов)", callback_data="ask_random")],
        [InlineKeyboardButton("Посмотреть список вопросов", callback_data="list_questions")],
        [InlineKeyboardButton("Напомнить вопрос", callback_data="repeat_q")],
        [InlineKeyboardButton("Кто сейчас A/B?", callback_data="whois")],
        [InlineKeyboardButton("Сбросить историю (частично/полностью)", callback_data="reset_history")],
    ])

def specific_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Посмотреть список вопросов", callback_data="list_questions")],
        [InlineKeyboardButton("⬅️ В меню", callback_data="back_to_menu")],
    ])

def send_answer_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Передать ответ", callback_data="send_answer")],
        [InlineKeyboardButton("Напомнить вопрос", callback_data="repeat_q")]
    ])

def back_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ В меню", callback_data="back_to_menu")]])

def questions_nav_kb(page: int) -> InlineKeyboardMarkup:
    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("◀️", callback_data=f"qpage_{page-1}"))
    if (page+1) * QUESTIONS_PER_PAGE < TOTAL_QUESTIONS:
        buttons.append(InlineKeyboardButton("▶️", callback_data=f"qpage_{page+1}"))
    return InlineKeyboardMarkup([
        buttons,
        [InlineKeyboardButton("⬅️ В меню", callback_data="back_to_menu")]
    ])

def get_questions_page(page: int) -> str:
    start = page * QUESTIONS_PER_PAGE
    end = min(start + QUESTIONS_PER_PAGE, TOTAL_QUESTIONS)
    lines = [f"{i+1}. {QUESTIONS[i]}" for i in range(start, end)]
    return "📋 Список вопросов:\n\n" + "\n".join(lines)

def is_user_A(state, chat_id): return state["roles"]["A"] == chat_id
def is_user_B(state, chat_id): return state["roles"]["B"] == chat_id
def roles_assigned(state): return bool(state["roles"]["A"]) and bool(state["roles"]["B"])

def get_completed_for_user(state: Dict[str, Any], user_id: int) -> Set[int]:
    return set(state.get("completed_by_user", {}).get(str(user_id), []))

def mark_completed_for_user(state: Dict[str, Any], user_id: int, qnum: int) -> None:
    key = str(user_id)
    lst = state.get("completed_by_user", {}).get(key, [])
    if qnum not in lst:
        lst.append(qnum)
        state["completed_by_user"][key] = sorted(lst)
        save_state(state)

def both_participants_ids(state: Dict[str, Any]):
    return state["roles"].get("A"), state["roles"].get("B")

def is_fully_closed(state: Dict[str, Any], qnum: int) -> bool:
    a_id, b_id = both_participants_ids(state)
    if not a_id or not b_id:
        return False
    return qnum in get_completed_for_user(state, a_id) and qnum in get_completed_for_user(state, b_id)

def remaining_numbers_for_user(state: Dict[str, Any], user_id: int) -> List[int]:
    completed_me = get_completed_for_user(state, user_id)
    pending_exclude = set([state["pending"]["qnum"]]) if state.get("pending") else set()
    result = []
    for i in range(1, TOTAL_QUESTIONS+1):
        if i in completed_me:
            continue
        if i in pending_exclude:
            continue
        if is_fully_closed(state, i):
            continue
        result.append(i)
    return result

def clear_pending(state): state["pending"] = None; state["draft_answers"] = []; save_state(state)

def auto_assign_role_on_start(state, chat_id: int) -> str:
    if chat_id not in state["participants"]:
        state["participants"].append(chat_id); save_state(state)
    if state["roles"]["A"] is None:
        state["roles"]["A"] = chat_id; save_state(state); return "A"
    if state["roles"]["B"] is None and chat_id != state["roles"]["A"]:
        state["roles"]["B"] = chat_id; save_state(state); return "B"
    if chat_id in (state["roles"]["A"], state["roles"]["B"]): return "none"
    return "none"

def maybe_assign_B(state, chat_id: int):
    if state["roles"]["A"] and state["roles"]["B"] is None and chat_id != state["roles"]["A"]:
        state["roles"]["B"] = chat_id; save_state(state)

def auto_swap_roles(state):
    state["roles"]["A"], state["roles"]["B"] = state["roles"]["B"], state["roles"]["A"]
    save_state(state)

# ---------- QUESTION HELPERS ----------
async def resend_current_question(context: ContextTypes.DEFAULT_TYPE, state: Dict[str, Any], to_chat_id: int) -> None:
    pending = state.get("pending")
    if not pending:
        await context.bot.send_message(chat_id=to_chat_id, text="Сейчас нет активного вопроса.")
        return
    qnum = pending["qnum"]; qtext = QUESTIONS[qnum - 1]
    if to_chat_id == pending["from_user"]:
        hdr = "Текущий вопрос, который ты отправил:"
        tail = "Когда получишь ответ и B нажмёт «Передать ответ», роли автоматически поменяются."
    elif to_chat_id == pending["to_user"]:
        hdr = "Напоминаю текущий вопрос:"
        tail = ("Загрузи ответ в формате текста, голосового сообщения или кружочка — их количество не ограничено. "
                "А после нажми кнопку «Передать ответ».")
    else:
        hdr = "Текущий активный вопрос:"; tail = ""
    msg = f"{hdr}\n\n№{qnum}: {qtext}\n\n{tail}".strip()
    await context.bot.send_message(
        chat_id=to_chat_id, text=msg,
        reply_markup=send_answer_kb() if to_chat_id == pending.get("to_user") else None
    )

    # ---------- HANDLERS ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = load_state()
    chat_id = update.effective_chat.id
    assigned = auto_assign_role_on_start(state, chat_id)
    intro = ("Этот бот для двух людей. Первый, кто нажмёт /start, становится A; второй — B. "
             "После «Передать ответ» роли автоматически меняются.\n\nВыберите действие:")
    role_msg = "Вы стали A (задаёте первый вопрос).\n" if assigned == "A" else ("Вы стали B (ответите на первый вопрос).\n" if assigned == "B" else "")
    await update.effective_chat.send_message(role_msg + intro, reply_markup=main_menu_kb())

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message(
        "1) Первый /start → A. Второй /start → B.\n"
        "2) A выбирает конкретный номер или случайный (без повторов для него).\n"
        "3) B может отправлять несколько сообщений-ответов: текст, голос, аудио, кружочек. Потом нажать «Передать ответ».\n"
        "4) Частично закрыт — для того, кто получил ответ; полностью — когда оба получили.\n"
        "5) «Посмотреть список вопросов» — кнопка в меню.\n"
        "6) «Напомнить вопрос» — кнопка или /question.\n"
        "7) /stats — статистика; /list — список вопросов; /reset — очистка истории.",
        reply_markup=back_menu_kb()
    )

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = load_state()
    a, b = state["roles"]["A"], state["roles"]["B"]
    ca = len(get_completed_for_user(state, a)) if a else 0
    cb = len(get_completed_for_user(state, b)) if b else 0
    fully = [i for i in range(1, TOTAL_QUESTIONS+1) if is_fully_closed(state, i)]
    msg = (
        "📊 Статистика\n"
        f"A ({a if a else '—'}): частично закрыто {ca}\n"
        f"B ({b if b else '—'}): частично закрыто {cb}\n"
        f"Полностью закрытые номера: {fully if fully else '—'}"
    )
    await update.effective_chat.send_message(msg, reply_markup=back_menu_kb())

async def list_questions(update: Update, context: ContextTypes.DEFAULT_TYPE, from_button=False, page=0):
    text = get_questions_page(page)
    kb = questions_nav_kb(page)
    if from_button and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=kb)
    else:
        await update.effective_chat.send_message(text, reply_markup=kb)

async def question_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = load_state()
    await resend_current_question(context, state, to_chat_id=update.effective_chat.id)

async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = load_state()
    state["completed_by_user"] = {}
    save_state(state)
    await update.effective_chat.send_message("История частичных/полных закрытий очищена.", reply_markup=back_menu_kb())

# ---------- on_button ----------
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = load_state()
    q = update.callback_query
    await q.answer()
    data = q.data
    chat_id = q.message.chat_id

    maybe_assign_B(state, chat_id)

    if data == "back_to_menu":
        await q.edit_message_text("Главное меню:", reply_markup=main_menu_kb()); return

    if data == "whois":
        a, b = state["roles"]["A"], state["roles"]["B"]
        ca = len(get_completed_for_user(state, a)) if a else 0
        cb = len(get_completed_for_user(state, b)) if b else 0
        await q.edit_message_text(f"A: {a if a else '—'} (закрыто: {ca})\nB: {b if b else '—'} (закрыто: {cb})", reply_markup=back_menu_kb()); return

    if data == "reset_history":
        state["completed_by_user"] = {}; save_state(state)
        await q.edit_message_text("История частичных/полных закрытий очищена.", reply_markup=main_menu_kb()); return

    if data == "repeat_q":
        await resend_current_question(context, state, to_chat_id=chat_id); return

    if data == "list_questions":
        await list_questions(update, context, from_button=True, page=0); return

    if data.startswith("qpage_"):
        try:
            page = int(data.split("_")[1])
        except:
            page = 0
        await list_questions(update, context, from_button=True, page=page); return

    if data == "ask_specific":
        if not is_user_A(state, chat_id):
            await q.edit_message_text("Сейчас задаёт вопросы только A.", reply_markup=back_menu_kb()); return
        if not roles_assigned(state):
            await q.edit_message_text("Ожидаю второго участника (B) — пусть нажмёт /start.", reply_markup=back_menu_kb()); return
        if state.get("pending"):
            await q.edit_message_text("Уже есть активный вопрос. Дождись ответа.", reply_markup=back_menu_kb()); return
        context.user_data["await_qnum"] = True
        await q.edit_message_text(
            "Введи номер (1..127). Для тебя недоступны номера, по которым ты уже получил ответ.\n"
            "Можно также посмотреть список вопросов.",
            reply_markup=specific_menu_kb()
        ); return

    if data == "ask_random":
        if not is_user_A(state, chat_id):
            await q.edit_message_text("Сейчас задаёт вопросы только A.", reply_markup=back_menu_kb()); return
        if not roles_assigned(state):
            await q.edit_message_text("Ожидаю второго участника (B) — пусть нажмёт /start.", reply_markup=back_menu_kb()); return
        if state.get("pending"):
            await q.edit_message_text("Уже есть активный вопрос. Дождись ответа.", reply_markup=back_menu_kb()); return
        remain = remaining_numbers_for_user(state, chat_id)
        if not remain:
            await q.edit_message_text("Нет доступных номеров для тебя (всё уже закрыто для тебя).", reply_markup=back_menu_kb()); return
        qnum = random.choice(remain)
        await send_question(context, state, from_a=chat_id, qnum=qnum, is_random=True); return

    if data == "send_answer":
        if not is_user_B(state, chat_id):
            await q.edit_message_text("Эта кнопка для B.", reply_markup=back_menu_kb()); return
        if not state.get("pending") or state["pending"]["to_user"] != chat_id:
            await q.edit_message_text("Нет ожидающего вопроса.", reply_markup=back_menu_kb()); return

        drafts: List[Dict[str, Any]] = state.get("draft_answers") or []
        if not drafts:
            await q.edit_message_text(
                "Сначала отправь сообщения-ответы (текст/голос/аудио/кружочек), затем нажми «Передать ответ». "
                "Я напомню вопрос ниже.",
                reply_markup=back_menu_kb()
            )
            await resend_current_question(context, state, to_chat_id=chat_id)
            return

        # Отправляем ВСЕ ответы отправителю (A)
        a_chat = state["pending"]["from_user"]
        qnum = state["pending"]["qnum"]
        await context.bot.send_message(chat_id=a_chat, text="Привет, тебе пришли ответы!")

        for item in drafts:
            t = item["type"]; data = item["data"]
            try:
                if t == "text":
                    await context.bot.send_message(chat_id=a_chat, text=data["text"])
                elif t == "voice":
                    await context.bot.send_voice(chat_id=a_chat, voice=data["file_id"], caption=data.get("caption"))
                elif t == "audio":
                    await context.bot.send_audio(chat_id=a_chat, audio=data["file_id"], caption=data.get("caption"))
                elif t == "video_note":
                    await context.bot.send_video_note(chat_id=a_chat, video_note=data["file_id"])
            except Exception:
                logging.exception("Не удалось переслать один из ответов A")

        await q.edit_message_text("Спасибо, твои ответы переданы.", reply_markup=back_menu_kb())
        mark_completed_for_user(state, a_chat, qnum)
        clear_pending(state)
        auto_swap_roles(state)
        new_a, new_b = state["roles"]["A"], state["roles"]["B"]
        try: await context.bot.send_message(chat_id=new_a, text="Теперь ты A — задай следующий вопрос.", reply_markup=main_menu_kb())
        except Exception: logging.exception("notify A failed")
        try: await context.bot.send_message(chat_id=new_b, text="Теперь ты B — жди вопрос.", reply_markup=main_menu_kb())
        except Exception: logging.exception("notify B failed")
        return
# ---------- send_question ----------
async def send_question(context: ContextTypes.DEFAULT_TYPE, state: Dict[str, Any], from_a: int, qnum: int, is_random: bool):
    b_chat = state["roles"]["B"]
    if not b_chat:
        await context.bot.send_message(chat_id=from_a, text="B ещё не присоединился. Пусть второй участник нажмёт /start.")
        return
    if state.get("pending"):
        await context.bot.send_message(chat_id=from_a, text="Уже есть активный вопрос. Дождись ответа.")
        return
    if qnum < 1 or qnum > TOTAL_QUESTIONS:
        await context.bot.send_message(chat_id=from_a, text="Номер вне диапазона (1..127)."); return

    if qnum in get_completed_for_user(state, from_a):
        await context.bot.send_message(chat_id=from_a, text=f"Вопрос №{qnum} уже закрыт для тебя. Выбери другой номер."); return
    if is_fully_closed(state, qnum):
        await context.bot.send_message(chat_id=from_a, text=f"Вопрос №{qnum} уже полностью закрыт (оба получили ответы)."); return

    state["pending"] = {"to_user": b_chat, "from_user": from_a, "qnum": qnum}
    state["draft_answers"] = []
    save_state(state)

    qtext = QUESTIONS[qnum - 1]
    await context.bot.send_message(
        chat_id=from_a,
        text=f"Готово, твой вопрос №{qnum} передан. Его текст звучит так:\n\n{qtext}"
    )

    prefix_b = "Привет, тебе пришел рандомный вопрос" if is_random else "Привет, тебе пришел конкретный вопрос"
    msg_b = (
        f"{prefix_b}.\n\n№{qnum}: {qtext}\n\n"
        "Загрузи ответ в формате текста, голосового сообщения или кружочка — их количество не ограничено. "
        "А после нажми кнопку «Передать ответ»."
    )
    await context.bot.send_message(chat_id=b_chat, text=msg_b, reply_markup=send_answer_kb())

# --------- МНОГООТВЕТНОСТЬ ОТ B ---------
def _append_draft(state: Dict[str, Any], item: Dict[str, Any]) -> None:
    drafts = state.get("draft_answers") or []
    drafts.append(item)
    state["draft_answers"] = drafts
    save_state(state)

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = load_state()
    chat_id = update.effective_chat.id
    maybe_assign_B(state, chat_id)
    text = update.message.text or ""

    if context.user_data.get("await_qnum"):
        context.user_data["await_qnum"] = False
        if not is_user_A(state, chat_id):
            await update.message.reply_text("Сейчас спрашивает только A.", reply_markup=back_menu_kb()); return
        if not roles_assigned(state):
            await update.message.reply_text("Ожидаю второго участника (B) — пусть нажмёт /start.", reply_markup=back_menu_kb()); return
        if state.get("pending"):
            await update.message.reply_text("Уже есть активный вопрос. Дождись ответа.", reply_markup=back_menu_kb()); return
        try:
            qnum = int(text.strip())
        except Exception:
            await update.message.reply_text("Нужно число от 1 до 127.", reply_markup=back_menu_kb()); return
        if qnum in get_completed_for_user(state, chat_id):
            await update.message.reply_text(f"Вопрос №{qnum} уже закрыт для тебя. Выбери другой номер.", reply_markup=back_menu_kb()); return
        if is_fully_closed(state, qnum):
            await update.message.reply_text(f"Вопрос №{qnum} уже полностью закрыт (оба получили ответы).", reply_markup=back_menu_kb()); return
        await send_question(context, state, from_a=chat_id, qnum=qnum, is_random=False); return

    if state.get("pending") and state["pending"]["to_user"] == chat_id and is_user_B(state, chat_id):
        _append_draft(state, {"from_user": chat_id, "type": "text", "data": {"text": text}})
        await update.message.reply_text("Текст принят. Можешь отправить ещё или нажать «Передать ответ».", reply_markup=send_answer_kb()); return

    if text.strip().lower() in {"вопрос", "напомни", "напомнить вопрос"}:
        await resend_current_question(context, state, to_chat_id=chat_id); return

    await update.message.reply_text("Выбери действие:", reply_markup=main_menu_kb())

async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = load_state()
    chat_id = update.effective_chat.id
    maybe_assign_B(state, chat_id)
    if state.get("pending") and state["pending"]["to_user"] == chat_id and is_user_B(state, chat_id):
        voice = update.message.voice; caption = update.message.caption
        _append_draft(state, {"from_user": chat_id, "type": "voice", "data": {"file_id": voice.file_id, "caption": caption}})
        await update.message.reply_text("Голосовое принято. Можешь отправить ещё или нажать «Передать ответ».", reply_markup=send_answer_kb()); return
    await update.message.reply_text("Сейчас нет ожидающего вопроса.", reply_markup=back_menu_kb())

async def on_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = load_state()
    chat_id = update.effective_chat.id
    maybe_assign_B(state, chat_id)
    if state.get("pending") and state["pending"]["to_user"] == chat_id and is_user_B(state, chat_id):
        audio = update.message.audio; caption = update.message.caption
        _append_draft(state, {"from_user": chat_id, "type": "audio", "data": {"file_id": audio.file_id, "caption": caption}})
        await update.message.reply_text("Аудио принято. Можешь отправить ещё или нажать «Передать ответ».", reply_markup=send_answer_kb()); return
    await update.message.reply_text("Сейчас нет ожидающего вопроса.", reply_markup=back_menu_kb())

async def on_video_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = load_state()
    chat_id = update.effective_chat.id
    maybe_assign_B(state, chat_id)
    if state.get("pending") and state["pending"]["to_user"] == chat_id and is_user_B(state, chat_id):
        vn = update.message.video_note
        _append_draft(state, {"from_user": chat_id, "type": "video_note", "data": {"file_id": vn.file_id}})
        await update.message.reply_text("Кружочек принят. Можешь отправить ещё или нажать «Передать ответ».", reply_markup=send_answer_kb()); return
    await update.message.reply_text("Сейчас нет ожидающего вопроса.", reply_markup=back_menu_kb())

async def on_other(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = load_state()
    chat_id = update.effective_chat.id
    maybe_assign_B(state, chat_id)
    await update.effective_chat.send_message("Поддерживаются: текст, голос, аудио, кружочек. Используй кнопку «Напомнить вопрос».", reply_markup=back_menu_kb())
def build_app() -> Application:
    if not TOKEN:
        raise RuntimeError("Нет TELEGRAM_TOKEN в переменных окружения.")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("question", question_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CommandHandler("list", list_questions))

    app.add_handler(CallbackQueryHandler(on_button))

    app.add_handler(MessageHandler(filters.VOICE, on_voice))
    app.add_handler(MessageHandler(filters.AUDIO, on_audio))
    app.add_handler(MessageHandler(filters.VIDEO_NOTE, on_video_note))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(~(filters.TEXT | filters.VOICE | filters.AUDIO | filters.VIDEO_NOTE), on_other))
    return app

def main():
    app = build_app()
    logging.info("Бот запускается (polling)...")
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
