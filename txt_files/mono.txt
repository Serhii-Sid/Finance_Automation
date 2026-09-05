import re
import pandas as pd
import logging
import pdfplumber
from config import COL_DATE, COL_DESC, COL_AMOUNT, COL_BALANCE, COL_MCC
from parsers.base_parser import BaseParser

logger = logging.getLogger(__name__)

class MonoParser(BaseParser):
    """Парсер для Monobank (PDF) на базі BaseParser."""

    @property
    def IDENTIFIERS(self) -> list[str]:
        return ["універсал банк", "monobank"]

    def _extract_raw_data(self, file_path: str) -> pd.DataFrame:
        all_rows = []
        try:
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    table = page.extract_table()
                    if table:
                        all_rows.extend(table)
            
            if not all_rows:
                return pd.DataFrame()

            header_idx = -1
            for i, row in enumerate(all_rows):
                row_str = " ".join([str(c) for c in row if c]).lower()
                if "деталі операції" in row_str and "сума в" in row_str:
                    header_idx = i
                    break
            
            if header_idx == -1:
                return pd.DataFrame()

            headers = [" ".join(str(c).split()).lower() for c in all_rows[header_idx]]
            data = []
            for row in all_rows[header_idx + 1:]:
                if row and len(row) == len(headers) and any(row):
                    clean_row = [" ".join(str(c).split()) if c else "" for c in row]
                    # Фільтруємо повтори заголовків на наступних сторінках та занадто короткі рядки
                    if "деталі операції" not in " ".join(clean_row).lower() and len(clean_row[0]) > 5:
                        data.append(clean_row)
            
            df = pd.DataFrame(data, columns=headers)
            
            # Специфічний мапінг для Monobank перед загальною стандартизацією
            mapping = {
                "дата i час операції": COL_DATE, 
                "деталі операції": COL_DESC,
                "mcc": COL_MCC, 
                "сума в валюті картки (uah)": COL_AMOUNT,
                "залишок після операції": COL_BALANCE
            }
            df = df.rename(columns=mapping)
            return df
        except Exception as e:
            logger.error(f"Помилка при зчитуванні Monobank PDF {file_path}: {e}")
            return pd.DataFrame()

    def _identify_credit_limit(self, file_path: str, df: pd.DataFrame) -> float:
        text = self._get_text_from_pdf(file_path)
        limit_match = re.search(r'Кредитний ліміт.*?:([\d\s,.]+)\s*UAH', text)
        if limit_match:
            limit_str = re.sub(r'\s+', '', limit_match.group(1)).replace(',', '.')
            try:
                limit = float(limit_str)
                logger.info(f"Детектор: виявлено кредитний ліміт Monobank: {limit}")
                return limit
            except (ValueError, TypeError):
                pass
        return 0.0