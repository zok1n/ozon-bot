"""
Telegram bot for vacancy collection with Ozon Bank card referral
---------------------------------------------------------------
Setup:
1) Install dependencies:
   pip install aiogram==2.25.1 python-dotenv
   (optional for Google Sheets: gspread oauth2client)

2) Create a .env file in the same folder with these variables:
   BOT_TOKEN=your_bot_token_here
   REF_LINK=https://your-referral-link.example
   MANAGER_USERNAME=@your_manager_username   # shown as contact button
   ADMIN_CHAT_ID=123456789   # optional: your admin chat id for notifications

3) Run:
   python telegram_bot_aiogram.py

Behavior:
- User starts /start and submits ФИО and номер телефона.
- Bot asks whether user already has Ozon Bank card; if no — shows referral link.
- After user confirms they applied for the card, the bot shows "Заявка отправлена" and provides a button to contact the manager.
- Submissions are saved to submissions.csv with timestamp.

Customize messages and branding variables below.
"""

import logging
import os
import csv
from datetime import datetime
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup

# Load environment
load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')
REF_LINK = os.getenv('REF_LINK', 'https://example.com')
MANAGER_USERNAME = os.getenv('MANAGER_USERNAME', '@manager')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID')  # optional

if not BOT_TOKEN:
    raise RuntimeError('Please set BOT_TOKEN in .env file')

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

CSV_FILE = 'submissions.csv'

# --- Bot copy / branding (edit these strings) ---
WELCOME_TEXT = (
    "👋 Привет! Мы ищем сотрудников на позицию *Ассистент по онлайн-обработке заказов*\n"
    "\n"
    "🏠 Работа: удалённо\n"
    "⏱ График: гибкий\n"
    "💸 Выплаты: еженедельно\n"
    "\n"
    "Нажмите кнопку ниже, чтобы подать заявку — это займет пару минут.")

ASK_NAME = "Напишите, пожалуйста, *ФИО* полностью (пример: Иванов Иван Иванович):"
ASK_PHONE = "Отправьте ваш номер телефона (можно нажать кнопку — отправить контакт):"
ASK_OZON = "У вас уже есть карта Ozon Bank? Это нужно для выплат:"

OZON_PROMO = (
    "Мы сотрудничаем с *Ozon Bank* — это позволяет начислять зарплату быстро и без комиссий.\n"
    "Если у вас ещё нет карты Ozon Bank, вы можете оформить её бесплатно (3 минуты).\n"
    "Нажмите кнопку *Оформить карту Ozon* и завершите заявку по ссылке.")

APPLICATION_SUBMITTED = (
    "🎉 *Заявка отправлена!*\n"
    "Ваша информация сохранена. Менеджер свяжется с вами в течение 24 часов.\n"
    "Если хотите — напишите менеджеру прямо сейчас по кнопке ниже.")

# --- States ---
class ApplyStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_phone = State()
    waiting_for_ozon_status = State()
    waiting_for_card_confirmation = State()

# --- Utilities ---

def save_submission(data: dict):
    fieldnames = [
        'timestamp', 'tg_id', 'username', 'full_name', 'phone', 'has_ozon_card', 'card_applied', 'ref_link_used'
    ]
    exists = os.path.exists(CSV_FILE)
    with open(CSV_FILE, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        writer.writerow(data)

async def notify_admin(text: str):
    if ADMIN_CHAT_ID:
        try:
            await bot.send_message(ADMIN_CHAT_ID, text, parse_mode='Markdown')
        except Exception as e:
            logging.exception('Не удалось отправить уведомление админу: %s', e)

# --- Keyboards ---

def main_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton('Подать заявку'))
    return kb

def contact_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton('Отправить контакт', request_contact=True))
    kb.add(types.KeyboardButton('Ввести номер вручную'))
    return kb

def ozon_choice_keyboard():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton('Да, есть', callback_data='ozon_yes'))
    kb.add(types.InlineKeyboardButton('Нет, оформлю', callback_data='ozon_no'))
    return kb

def ozon_ref_keyboard():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton('Оформить карту Ozon (бесплатно)', url=REF_LINK))
    kb.add(types.InlineKeyboardButton('Я оформил(а) карту', callback_data='card_done'))
    return kb

def manager_keyboard():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton('Написать менеджеру', url=f'https://t.me/{MANAGER_USERNAME.lstrip("@")}'))
    return kb

# --- Handlers ---

@dp.message_handler(commands=['start', 'help'])
async def cmd_start(message: types.Message):
    await message.answer(WELCOME_TEXT, parse_mode='Markdown', reply_markup=main_keyboard())

@dp.message_handler(lambda m: m.text == 'Подать заявку')
async def start_application(message: types.Message):
    await ApplyStates.waiting_for_name.set()
    await message.answer(ASK_NAME, reply_markup=types.ReplyKeyboardRemove())

@dp.message_handler(state=ApplyStates.waiting_for_name, content_types=types.ContentTypes.TEXT)
async def process_name(message: types.Message, state: FSMContext):
    name = message.text.strip()
    await state.update_data(full_name=name)
    await ApplyStates.waiting_for_phone.set()
    await message.answer(ASK_PHONE, reply_markup=contact_keyboard())

@dp.message_handler(lambda m: m.text == 'Ввести номер вручную', state=ApplyStates.waiting_for_phone)
async def ask_manual_phone(message: types.Message):
    await message.answer('Отправьте ваш номер в формате +7XXXXXXXXXX:')

@dp.message_handler(content_types=types.ContentTypes.CONTACT, state=ApplyStates.waiting_for_phone)
async def process_contact(message: types.Message, state: FSMContext):
    contact = message.contact
    phone = contact.phone_number
    await state.update_data(phone=phone)
    await ApplyStates.waiting_for_ozon_status.set()
    await message.answer(ASK_OZON, reply_markup=ozon_choice_keyboard())

@dp.message_handler(lambda m: m.text and m.text.startswith('+'), state=ApplyStates.waiting_for_phone)
async def process_manual_phone(message: types.Message, state: FSMContext):
    phone = message.text.strip()
    await state.update_data(phone=phone)
    await ApplyStates.waiting_for_ozon_status.set()
    await message.answer(ASK_OZON, reply_markup=ozon_choice_keyboard())

@dp.callback_query_handler(lambda c: c.data and c.data.startswith('ozon_'), state=ApplyStates.waiting_for_ozon_status)
async def process_ozon_choice(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    choice = callback.data.split('_', 1)[1]
    if choice == 'yes':
        # user already has card
        data = await state.get_data()
        submission = {
            'timestamp': datetime.utcnow().isoformat(),
            'tg_id': callback.from_user.id,
            'username': callback.from_user.username or '',
            'full_name': data.get('full_name', ''),
            'phone': data.get('phone', ''),
            'has_ozon_card': 'yes',
            'card_applied': 'n/a',
            'ref_link_used': ''
        }
        save_submission(submission)
        await notify_admin(f"Новая заявка: {submission}")
        await callback.message.answer(APPLICATION_SUBMITTED, parse_mode='Markdown', reply_markup=manager_keyboard())
        await state.finish()
    else:
        # user doesn't have card — show referral
        await ApplyStates.waiting_for_card_confirmation.set()
        await callback.message.answer(OZON_PROMO, parse_mode='Markdown', reply_markup=ozon_ref_keyboard())

@dp.callback_query_handler(lambda c: c.data == 'card_done', state=ApplyStates.waiting_for_card_confirmation)
async def card_done(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer('Отлично — пометили, что вы оформили карту.')
    data = await state.get_data()
    submission = {
        'timestamp': datetime.utcnow().isoformat(),
        'tg_id': callback.from_user.id,
        'username': callback.from_user.username or '',
        'full_name': data.get('full_name', ''),
        'phone': data.get('phone', ''),
        'has_ozon_card': 'no',
        'card_applied': datetime.utcnow().isoformat(),
        'ref_link_used': REF_LINK
    }
    save_submission(submission)
    await notify_admin(f"Новая заявка (оформил карту): {submission}")
    await callback.message.answer(APPLICATION_SUBMITTED, parse_mode='Markdown', reply_markup=manager_keyboard())
    await state.finish()

@dp.message_handler(content_types=types.ContentTypes.TEXT)
async def fallback(message: types.Message):
    # Friendly catch-all
    await message.answer('Чтобы подать заявку, нажмите кнопку *Подать заявку*.', parse_mode='Markdown', reply_markup=main_keyboard())

# --- Run ---
if __name__ == '__main__':
    print('Bot is starting...')
    executor.start_polling(dp, skip_updates=True)
