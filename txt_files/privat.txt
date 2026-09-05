import re
import pandas as pd
import logging
from typing import Optional
from config import EXCEL_MAPPING
from src.text_utils import detect_account_identity
from parsers.base_parser import BaseParser

logger = logging.getLogger(__name__)

class PrivatParser(BaseParser):
    """Парсер для ПриватБанк (Excel) на базі BaseParser."""

    @property
    def IDENTIFIERS(self) -> list[str]:
        # Приват ми ідентифікуємо за розширенням .xlsx, але можна додати маркери для перевірки вмісту
        return ["приватбанк", "код єдрпоу 14360570"]

    def _extract_raw_data(self, file_path: str) -> pd.DataFrame:
        df_raw = pd.read_excel(file_path, header=None, dtype=str)
        header_search = df_raw.apply(lambda r: r.str.contains('Дата', na=False).any(), axis=1)
        if not header_search.any():
            return pd.DataFrame()
        
        header_idx = header_search.idxmax()
        df = pd.read_excel(file_path, header=header_idx, dtype=str)
        df.columns = [" ".join(str(c).split()).lower() for c in df.columns]
        df = df.rename(columns=EXCEL_MAPPING)
        return df

    def _identify_credit_limit(self, file_path: str, df: pd.DataFrame) -> float:
        try:
            # Читаємо перші 30 рядків для пошуку ліміту
            df_raw = pd.read_excel(file_path, header=None, dtype=str, nrows=30)
            limit_row = df_raw[df_raw.apply(lambda r: r.str.contains('Кредитний ліміт', case=False, na=False).any(), axis=1)]
            if not limit_row.empty:
                text = " ".join(limit_row.iloc[0].dropna().astype(str))
                m = re.search(r'([\d\s,.]+)', text.split('ліміт')[-1])
                if m:
                    val = float(m.group(1).replace('\xa0', '').replace(' ', '').replace(',', '.'))
                    logger.info(f"Детектор: виявлено кредитний ліміт ПриватБанку: {val}")
                    return val
        except: pass
        return 0.0

    def _identify_card(self, file_path: str) -> Optional[str]:
        """Версія пошуку карти для Excel."""
        try:
            df_raw = pd.read_excel(file_path, header=None, dtype=str, nrows=20)
            full_text = " ".join(df_raw.fillna("").values.flatten().astype(str))
            return detect_account_identity(full_text)
        except:
            return None

    def _apply_balance_adjustment(self, df: pd.DataFrame) -> pd.DataFrame:
        # Перевизначення: Приват уже містить реальний борг у виписці, коригування не потрібне.
        return df