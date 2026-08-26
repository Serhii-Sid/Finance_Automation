import re
import pandas as pd
import logging
import pdfplumber
from typing import Optional
from config import COL_CARD, IBAN_TO_CARD_MAP
from parsers.base_parser import BaseParser

logger = logging.getLogger(__name__)

class AbankParser(BaseParser):
    """Парсер для А-Банк (PDF) на базі BaseParser."""

    @property
    def IDENTIFIERS(self) -> list[str]:
        return ["акцент-банк", "а-банк"]

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
                if "дата і час" in row_str and "номер картки" in row_str:
                    header_idx = i
                    break

            if header_idx == -1:
                return pd.DataFrame()

            headers = [" ".join(str(c).split()).lower() for c in all_rows[header_idx]]
            data = []
            for row in all_rows[header_idx + 1:]:
                if row and len(row) == len(headers) and any(row):
                    clean_row = [" ".join(str(c).split()) if c else "" for c in row]
                    if "дата і час" not in " ".join(clean_row).lower():
                        data.append(clean_row)

            df = pd.DataFrame(data, columns=headers)
            # Виправлення можливих помилок у заголовках банку перед стандартизацією
            df = df.rename(columns={"залишок після операціїї": "залишок після операції"})
            return df
        except Exception as e:
            logger.error(f"Помилка при читанні PDF А-Банку {file_path}: {e}")
            return pd.DataFrame()

    def _identify_credit_limit(self, file_path: str, df: pd.DataFrame) -> float:
        text = self._get_text_from_pdf(file_path)
        limit_match = re.search(r'Кредитний ліміт.*?:\s*([\d\s,.]+)\s*UAH', text)
        if limit_match:
            limit_str = re.sub(r'\s+', '', limit_match.group(1)).replace(',', '.')
            try:
                limit = float(limit_str)
                logger.info(f"Детектор: виявлено кредитний ліміт А-Банку {limit}")
                return limit
            except (ValueError, TypeError):
                pass
        return 0.0

    def parse(self, file_path: str) -> Optional[pd.DataFrame]:
        self.iban_identified = False
        text = self._get_text_from_pdf(file_path, pages_limit=1)
        if text:
            # Очищуємо пробіли та переводимо в верхній регістр
            clean_text = re.sub(r'\s+', '', text).upper()
            m = re.search(r'UA\d{27}', clean_text)
            if m:
                iban_code = m.group(0)
                if iban_code in IBAN_TO_CARD_MAP:
                    self.card_name = IBAN_TO_CARD_MAP[iban_code]
                    self.iban_identified = True
                    logger.info(f"AbankParser: ідентифіковано рахунок за IBAN в заголовку: {iban_code} -> '{self.card_name}'")

        return super().parse(file_path)

    def _assign_card_identity(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Специфічна логіка А-Банку: при успішній ідентифікації за IBAN у заголовку 
        перезаписуємо всю колонку. Інакше використовуємо запасний варіант (за маскою).
        """
        if COL_CARD in df.columns:
            # Очищуємо та готуємо колонку
            df[COL_CARD] = df[COL_CARD].astype(str).str.strip().replace(
                ['nan', 'None', 'nan nan', '', 'Невідома картка'], pd.NA
            )
            
            if self.card_name:
                if getattr(self, 'iban_identified', False):
                    # При успішній ідентифікації по IBAN перезаписуємо всю колонку повністю
                    df[COL_CARD] = self.card_name
                    logger.info(f"AbankParser: примусово призначено карту '{self.card_name}' для всіх транзакцій виписки.")
                else:
                    # Запасний варіант (за маскою): якщо номер короткий або NA, підставляємо
                    mask = df[COL_CARD].isna() | (df[COL_CARD].astype(str).str.len() < 10)
                    df.loc[mask, COL_CARD] = self.card_name
                    
        return df