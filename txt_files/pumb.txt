import re
import pandas as pd
import logging
import pdfplumber
from config import COL_DATE, COL_AMOUNT, COL_CARD, COL_DESC, COL_CAT, COL_BALANCE, CARDS_DICTIONARY
from parsers.base_parser import BaseParser

logger = logging.getLogger(__name__)

class PumbParser(BaseParser):
    """Парсер для ПУМБ (PDF) на базі BaseParser."""

    @property
    def IDENTIFIERS(self) -> list[str]:
        return ["перший український міжнародний банк", "пумб"]

    def _extract_raw_data(self, file_path: str) -> pd.DataFrame:
        all_rows = []
        anchor_pattern = re.compile(r'(\d{4}-\d{2}-\d{2}\s*\d{2}:\d{2}:\d{2})|(\d{2}\.\d{2}\.\d{4}\s*\d{2}:\d{2}:\d{2})')
        card_pattern = re.compile(r'(\d{8})[*.\s]*(\d{4})')
        footers = ['баланс рахунку', 'всього списань', 'всього зарахувань', 'вклади гарантуються']

        try:
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    table = page.extract_table()
                    if table:
                        all_rows.extend(table)
            
            if not all_rows:
                return pd.DataFrame()
            
            flat_stream = []
            for row in all_rows:
                for cell in row:
                    if cell:
                        clean_val = " ".join(str(cell).split())
                        if clean_val:
                            flat_stream.append(clean_val)

            blocks, current_tx = [], []
            for item in flat_stream:
                if any(f in item.lower() for f in footers):
                    continue
                if anchor_pattern.search(item):
                    if current_tx:
                        blocks.append(current_tx)
                    current_tx = [item]
                else:
                    if current_tx:
                        current_tx.append(item)
            if current_tx:
                blocks.append(current_tx)

            final_data = []
            for b in blocks:
                full_text = " ".join(b)
                
                # Локальна детекція карти в блоці через маску
                current_card_mask = None
                for val in b:
                    m = card_pattern.search(str(val))
                    if m:
                        current_card_mask = f"{m.group(1)}****{m.group(2)}"
                        break
                
                # --- Покращена детекція дати ---
                # Шукаємо ISO дату (РРРР-ММ-ДД) в блоці - вона найточніша для ПУМБ
                iso_date_match = re.search(r'(\d{4}-\d{2}-\d{2})', full_text)
                time_match = re.search(r'(\d{2}:\d{2}:\d{2})', full_text)
                
                if iso_date_match:
                    d_part = iso_date_match.group(1)
                    t_part = time_match.group(1) if time_match else "00:00:00"
                    # Явно парсимо ISO формат, щоб уникнути помилкового dayfirst у utils.py
                    date_val = pd.to_datetime(f"{d_part} {t_part}")
                else:
                    # Для формату DD.MM.YYYY використовуємо dayfirst=True
                    date_val = pd.to_datetime(b[0], dayfirst=True, errors='coerce')

                # Опис та очищення
                if "CITY24" in full_text.upper():
                    full_desc = "Поповнення (CITY24)"
                else:
                    # Видаляємо дату/час з початку опису
                    clean_desc = re.sub(r'^(\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4})?\s*(\d{2}:\d{2}:\d{2})?\s*', '', full_text).strip()
                    # Видаляємо технічні слова, зайві дати та суми, що повторюються
                    full_desc = re.sub(r'(Покупка|Надходження|Списання|Комісія|UAH|USD|EUR)', '', clean_desc, flags=re.I)
                    full_desc = re.sub(r'(\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4})', '', full_desc)
                    full_desc = re.sub(r'(\d{2}:\d{2}:\d{2})', '', full_desc)
                    full_desc = re.sub(r'\s+', ' ', full_desc)

                # Категорія
                cat_tag = "Інше"
                for val in reversed(b):
                    m_cat = re.search(r'(Покупка|Надходження|Списання|Комісія|Оплата)', str(val), re.I)
                    if m_cat:
                        cat_tag = m_cat.group(1).capitalize()
                        break
                
                # Сума
                amt_val = "0"
                # Обмежуємо жадібність: шукаємо число без пробілів перед копійками
                m_uah = re.search(r'(-?\d+[.,]\d{2})\s*UAH', full_text, re.I)
                if m_uah:
                    amt_val = m_uah.group(1)
                else:
                    m_any = re.search(r'(-?\d+[.,]\d{2})\s*(?:USD|EUR)', full_text, re.I)
                    if m_any:
                        amt_val = m_any.group(1)

                final_data.append({
                    COL_DATE: date_val,
                    COL_AMOUNT: amt_val,
                    COL_CARD: current_card_mask,
                    COL_DESC: full_desc,
                    COL_CAT: cat_tag,
                    COL_BALANCE: 0.0
                })

            return pd.DataFrame(final_data)
        except Exception as e:
            logger.error(f"Помилка ПУМБ PDF {file_path}: {e}")
            return pd.DataFrame()

    def _assign_card_identity(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Для ПУМБ спочатку мапимо маску з блоку, а якщо її немає - 
        використовуємо self.card_name, знайдений через BaseParser.
        """
        if COL_CARD in df.columns:
            df[COL_CARD] = df[COL_CARD].map(CARDS_DICTIONARY).fillna(self.card_name or "Невідома картка")
        return df