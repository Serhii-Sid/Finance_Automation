import pandas as pd
import logging
from abc import ABC, abstractmethod
from typing import Optional
from config import COL_CARD
from data_manager import standardize_df
from finance_logic import adjust_balance_with_credit_limit
from text_utils import detect_account_identity

logger = logging.getLogger(__name__)

class BaseParser(ABC):
    """
    Абстрактний базовий клас для всіх парсерів банків.
    Визначає шаблонний метод parse(), який координує процес.
    """

    def __init__(self, card_name: Optional[str] = None):
        self.card_name = card_name
        self.credit_limit = 0.0

    @property
    @abstractmethod
    def IDENTIFIERS(self) -> list[str]:
        """Список ключових слів для ідентифікації банку в тексті виписки."""
        pass

    def parse(self, file_path: str) -> Optional[pd.DataFrame]:
        """
        Головний метод, який викликає кроки обробки по черзі.
        """
        try:
            # 1. Зчитування "сирих" даних (реалізується конкретним банком)
            df = self._extract_raw_data(file_path)
            if df is None or df.empty:
                return None

            # Якщо карту не передали, шукаємо її за текстом (IBAN -> Mask)
            if not self.card_name:
                self.card_name = self._identify_card(file_path)

            # 2. Пошук кредитного ліміту (якщо банк це підтримує)
            self.credit_limit = self._identify_credit_limit(file_path, df)

            # 3. Стандартизація колонок (спільна логіка з utils.py)
            df = standardize_df(df)

            # 4. Прив'язка до конкретної картки (якщо не передано - шукаємо в процесі)
            df = self._assign_card_identity(df)

            # 5. Коригування балансу (реальний борг vs залишок)
            df = self._apply_balance_adjustment(df)

            return df
        except Exception as e:
            logger.error(f"Критична помилка парсингу {file_path}: {e}", exc_info=True)
            return None

    @abstractmethod
    def _extract_raw_data(self, file_path: str) -> pd.DataFrame:
        """Витягує таблицю транзакцій з файлу (PDF або Excel)."""
        pass

    def _identify_credit_limit(self, file_path: str, df: pd.DataFrame) -> float:
        """За замовчуванням ліміт 0.0. Банки можуть перевизначити цей метод."""
        return 0.0

    def _identify_card(self, file_path: str) -> Optional[str]:
        """Автоматичний пошук карти за IBAN або маскою через utils.detect_account_identity."""
        # Для PDF використовуємо існуючий метод отримання тексту
        if file_path.lower().endswith('.pdf'):
            text = self._get_text_from_pdf(file_path)
            return detect_account_identity(text)
        return None

    def _assign_card_identity(self, df: pd.DataFrame) -> pd.DataFrame:
        """Заповнює колонку картки."""
        if self.card_name and COL_CARD in df.columns:
            df[COL_CARD] = self.card_name
        return df

    def _apply_balance_adjustment(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Логіка коригування балансу. 
        За замовчуванням використовуємо стандартну функцію віднімання ліміту.
        """
        if self.credit_limit > 0:
            logger.info(f"Застосовано коригування ліміту: {self.credit_limit}")
            return adjust_balance_with_credit_limit(df, self.credit_limit)
        return df

    def _get_text_from_pdf(self, file_path: str, pages_limit: int = 1) -> str:
        """Допоміжний метод для отримання тексту з PDF (для пошуку ліміту або карти)."""
        import pdfplumber
        text = ""
        try:
            with pdfplumber.open(file_path) as pdf:
                for i in range(min(len(pdf.pages), pages_limit)):
                    text += (pdf.pages[i].extract_text() or "") + "\n"
        except Exception as e:
            logger.warning(f"Не вдалося витягнути текст з PDF {file_path}: {e}")
        return text