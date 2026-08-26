import re
import logging
import pandas as pd
from typing import Optional
from config import IBAN_TO_CARD_MAP, CARDS_DICTIONARY

# Для Альянс Банку: витягує категорію з початку опису
REGEX_CAT_CLEAN = r'^([^→•·*]{3,})(?=\s*[→•·*])'

logger = logging.getLogger(__name__)

def detect_account_identity(text: str) -> Optional[str]:
    """
    Універсальний пошук IBAN або 4-значного хвоста карти в тексті з жорсткою ієрархією:
    1. Пріоритет №1 (IBAN): Пошук регулярним виразом UA + 27 цифр, перевірка в IBAN_TO_CARD_MAP.
    2. Пріоритет №2 (4 цифри): Пошук будь-якої послідовності з 4-х цифр поспіль, перевірка в CARDS_DICTIONARY.
    """
    if not text:
        return None

    # Очищуємо пробіли та переводимо в верхній регістр
    clean_text = re.sub(r'\s+', '', text).upper()

    # 1. Пріоритет №1 (IBAN)
    iban_match = re.search(r'UA\d{27}', clean_text)
    if iban_match:
        iban_code = iban_match.group(0)
        if iban_code in IBAN_TO_CARD_MAP:
            logger.info(f"Детектор (IBAN): знайдено IBAN {iban_code} -> '{IBAN_TO_CARD_MAP[iban_code]}'")
            return IBAN_TO_CARD_MAP[iban_code]
        # Вилучаємо знайдений IBAN з тексту пошуку, щоб його цифри не заважали резервному кроку
        clean_text = clean_text.replace(iban_code, '')

    # 2. Пріоритет №2 (Цифровий хвіст - Резерв)
    # Шукаємо всі 4-значні послідовності цифр в тексті
    digits4 = re.findall(r'\d{4}', clean_text)
    for d in digits4:
        if d in CARDS_DICTIONARY:
            logger.info(f"Детектор (Резерв): знайдено 4 цифри {d} -> '{CARDS_DICTIONARY[d]}'")
            return CARDS_DICTIONARY[d]

    return None

def _normalize_text(s: pd.Series) -> pd.Series:
    """
    Крок 0: Нормалізація опису.
    Видаляє спецсимволи, цифри, слова-шум та приводить до нижнього регістру.
    Зберігає маркер 'plus380' для ідентифікації поповнень мобільних телефонів.
    """
    # 1. Нижній регістр та видалення спецсимволів
    clean = s.astype(str).str.lower()
    clean = clean.str.replace('i', 'і', regex=False)
    # 1.1. Зберігаємо +380 як тимчасовий маркер БЕЗ ЦИФР ('plusua'), щоб він вижив після strip digits
    clean = clean.str.replace(r'\+\s*380', 'plusua', regex=True)
    clean = clean.str.replace(r'[+•·→●○.,*/\-\\]+', ' ', regex=True)
    # 2. Видалення валют та технічних слів (шуму)
    clean = clean.str.replace(r'\b(uah|грн|покупка|списання)\b', ' ', regex=True)
    # 3. Видалення цифр (коди авторизації тощо) — 'plusua' не містить цифр, тому зберігається
    clean = clean.str.replace(r'\d+', ' ', regex=True)
    # 3.1. Відновлюємо фінальний маркер 'plus380' для пошуку за KEYWORD_MAP
    clean = clean.str.replace('plusua', 'plus380', regex=False)
    # 4. Видалення зайвих пробілів
    return clean.str.replace(r'\s+', ' ', regex=True).str.strip()
