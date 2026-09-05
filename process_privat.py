# --- Стандартні модулі Python ---
import os
import sys
import glob
import logging
import shutil
import warnings
from typing import Optional

# --- Сторонні бібліотеки ---
import pandas as pd

# --- Налаштування проекту (Конфігурація) ---
from config import (
    INPUT_FOLDER, OUTPUT_FOLDER, ARCHIVE_FOLDER, OUTPUT_FILE, LOG_FILE,
    COL_ID, COL_DATE, COL_CARD, USEFUL_COLUMNS, REBUILD_MODE
)

# --- Імпорт модулів-парсерів ---
from parsers.base_parser import BaseParser
from parsers import PrivatParser
from src.data_manager import standardize_df, clean_and_transform, reconcile_and_merge
from src.finance_logic import (
    apply_bank_specific_post_processing,
    detect_internal_transfers,
    process_transit_vika,
    process_mono_investments
)
from src.report_engine import save_final_ledger

# --- Налаштування логування ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Налаштування: вимикаємо ворнінги openpyxl, щоб термінал був чистим
warnings.simplefilter(action='ignore', category=UserWarning)

# ==============================================================================
# КРОК 1. ІНІЦІАЛІЗАЦІЯ СЕРЕДОВИЩА (Шляхи та папки)
# ==============================================================================

def initialize_environment():
    """Створює необхідні папки, якщо вони відсутні на диску."""

    
    # --- Формуємо список цільових папок для ініціалізації ---
    folders = [INPUT_FOLDER, OUTPUT_FOLDER, ARCHIVE_FOLDER]    
    
    # --- Цикл перевірки та створення папок ---
    for folder in folders:
        if not os.path.exists(folder):
            os.makedirs(folder)
            logger.info(f"Створено папку: {os.path.basename(folder)}")

def identify_bank_by_markers(file_path: str) -> Optional[type]:
    """Детектор: Визначає банк за текстом на першій сторінці PDF."""
    import pdfplumber
    # Автоматично беремо всі класи, що успадкували BaseParser
    all_parsers = BaseParser.__subclasses__()
    try:
        with pdfplumber.open(file_path) as pdf:
            if not pdf.pages: return None
            text = (pdf.pages[0].extract_text() or "").lower()

            for parser_cls in all_parsers:
                if parser_cls == PrivatParser: continue # Приват ідентифікуємо за розширенням .xlsx
                # Створюємо тимчасовий об'єкт, щоб отримати доступ до IDENTIFIERS
                temp_parser = parser_cls()  # type: ignore
                if any(marker in text for marker in temp_parser.IDENTIFIERS):
                    return parser_cls
    except Exception as e:
        logger.warning(f"Не вдалося ідентифікувати банк у {file_path}: {e}")
    return None

def load_bank_file(file_path: str) -> Optional[pd.DataFrame]:
    """Оркестратор: Визначає банк та викликає відповідний парсер."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == '.xlsx':
        return PrivatParser().parse(file_path)

    if ext == '.pdf':
        parser_class = identify_bank_by_markers(file_path)
        if parser_class:
            logger.info(f"Детектор впізнав: {parser_class.__name__}")
            return parser_class().parse(file_path)
        
        logger.warning(f"Детектор не впізнав банк у PDF: {file_path}")

    return None

def main():
    initialize_environment()
    all_entries = glob.glob(os.path.join(INPUT_FOLDER, '*.xlsx')) + glob.glob(os.path.join(INPUT_FOLDER, '*.pdf'))
    found_files = [f for f in all_entries if os.path.isfile(f) and not os.path.basename(f).startswith('~$')]

    # Визначаємо режим роботи (з config.py або з командного рядка --rebuild)
    is_rebuild = REBUILD_MODE or ('--rebuild' in sys.argv)

    # Читаємо базу без примусового перетворення на str, щоб зберегти об'єкти дати
    if not is_rebuild and os.path.exists(OUTPUT_FILE):
        logger.info(f"Режим запуску: Щоденний дозапис (is_rebuild={is_rebuild}). Завантажуємо існуючу базу з {os.path.basename(OUTPUT_FILE)}")
        df_base = pd.read_excel(OUTPUT_FILE, sheet_name='Total_Ledger', dtype={COL_ID: str}, parse_dates=[COL_DATE])
        df_base = standardize_df(df_base)  # Автоматично перейменує колонки в старій базі
    else:
        if is_rebuild:
            logger.info(f"Режим запуску: Повний перезапис (is_rebuild={is_rebuild}). Існуюча база буде ігноруватись.")
        else:
            logger.info(f"Базу {os.path.basename(OUTPUT_FILE)} не знайдено. Ініціалізація порожнього реєстру.")
        df_base = pd.DataFrame()

    all_dfs = []

    for f in found_files:
        logger.info(f"Обробка: {os.path.basename(f)}")
        try:
            df = load_bank_file(f)
        except Exception as e:
            logger.error(f"Критична помилка при читанні {f}: {e}")
            df = None
        
        # standardize_df is called inside load_bank_file, so USEFUL_COLUMNS should be present.
        # We only need to check if df is not None and not empty.
        if df is not None and not df.empty:
            df = clean_and_transform(df)
        
        if df is not None and len(df) > 0:
            all_dfs.append(df)
        else:
            logger.error(f"Не вдалося обробити файл: {f}")

        # Переміщуємо файл в архів незалежно від того, чи була обробка успішною
        try:
            if os.path.exists(f):
                shutil.move(f, os.path.join(ARCHIVE_FOLDER, os.path.basename(f)))
        except Exception as e:
            logger.error(f"Не вдалося перемістити файл {f} в архів (можливо, він відкритий): {e}")

    if all_dfs or not df_base.empty:
        if all_dfs:
            new_data = pd.concat(all_dfs, ignore_index=True).drop_duplicates()
            # Скидаємо індекс для надійного вирівнювання при фільтрації
            new_data = new_data.reset_index(drop=True)
            # Об'єднуємо з існуючою базою через розумну звірку
            df_final = reconcile_and_merge(new_data, df_base)
        else:
            df_final = df_base

        df_final = df_final.sort_values(by=COL_DATE, ascending=False).reset_index(drop=True)
        df_final = apply_bank_specific_post_processing(df_final)

        # Залишаємо лише потрібні колонки у суворо визначеному порядку
        final_columns = [COL_ID] + USEFUL_COLUMNS
        df_final = df_final[final_columns]

        # Застосовуємо оновлену категоризацію до всієї бази
        df_final = clean_and_transform(df_final)

        # Виявлення внутрішніх переказів (detect_internal_transfers) — НАЙВИЩИЙ ПРІОРИТЕТ
        df_final = detect_internal_transfers(df_final)

        # Маркування прихідних транзакцій від Віки
        df_final = process_transit_vika(df_final)

        # Маркування інвестиційних витрат для картки Monobank
        df_final = process_mono_investments(df_final)

        # Первинний незмінний реєстр транзакцій (для листа Total_Ledger)
        df_raw = df_final.copy()

        # Зберігаємо леджер з 4 листами (Total_Ledger, Income, Expenses, Daily_Dashboard)
        save_final_ledger(df_raw)

        # --- Звіт у лог ---
        logger.info("=" * 40)
        logger.info("[ЗВІТ] ТЕСТОВИЙ ЗВІТ ПО НОВИХ ДАНИХ")
        if all_dfs:
            logger.info("\n" + new_data.groupby(COL_CARD).size().reset_index(name='Кількість транзакцій').to_string(index=False))
        else:
            logger.info("Базу оновлено згідно з останніми правилами категоризації (без нових файлів).")
        logger.info("=" * 40)

    else:
        logger.info("Нових даних не виявлено.")

if __name__ == "__main__":
    main()