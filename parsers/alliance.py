import re
import pandas as pd
import logging
import pdfplumber
from typing import Optional
from config import COL_DATE, COL_DESC, COL_AMOUNT, COL_BALANCE, COL_CARD
from parsers.base_parser import BaseParser

logger = logging.getLogger(__name__)

ALLIANCE_CARD_REGEX = r'[•·*]+\s*(\d{4})'

class AllianceParser(BaseParser):
    """Парсер для Альянс Банк (PDF) на базі BaseParser."""

    @property
    def IDENTIFIERS(self) -> list[str]:
        return ["банк альянс"]

    def _extract_raw_data(self, file_path: str) -> pd.DataFrame:
        mapping = {
            "дата": COL_DATE, "дата операції": COL_DATE,
            "операція": COL_DESC, "опис": COL_DESC, "деталі": COL_DESC,
            "сума": COL_AMOUNT, "сума (uah)": COL_AMOUNT,
            "баланс після операції": COL_BALANCE, "залишок": COL_BALANCE
        }
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
                if row and any("Дата" in str(c) for c in row):
                    header_idx = i
                    break

            if header_idx == -1:
                return pd.DataFrame()

            headers = all_rows[header_idx]
            data = [row for row in all_rows[header_idx+1:] if row and not any("Дата" in str(c) for c in row)]

            df = pd.DataFrame(data, columns=headers)
            df.columns = [" ".join(str(c).split()).lower() for c in df.columns]
            df = df.rename(columns=mapping)
            return df
        except Exception as e:
            logger.error(f"Помилка при читанні PDF Альянс Банку {file_path}: {e}")
            return pd.DataFrame()

    def _identify_credit_limit(self, file_path: str, df: pd.DataFrame) -> float:
        text = self._get_text_from_pdf(file_path)
        limit_match = re.search(r'Кредитний ліміт.*?:\s*([\d\s,.]+)\s*UAH', text)
        if limit_match:
            limit_str = re.sub(r'\s+', '', limit_match.group(1)).replace(',', '.')
            try:
                limit = float(limit_str)
                logger.info(f"Детектор: виявлено кредитний ліміт Альянсу: {limit}")
                return limit
            except (ValueError, TypeError):
                pass
        return 0.0

    def _assign_card_identity(self, df: pd.DataFrame) -> pd.DataFrame:
        """Витягуємо номер картки з опису, якщо він там є (специфіка Альянсу)."""
        df = super()._assign_card_identity(df)
        if COL_DESC in df.columns:
            extracted_card = df[COL_DESC].str.extract(ALLIANCE_CARD_REGEX)[0]
            if COL_CARD in df.columns:
                df[COL_CARD] = df[COL_CARD].fillna(extracted_card)
            else:
                df[COL_CARD] = extracted_card
        return df