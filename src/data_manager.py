import re
import logging
import pandas as pd
from src.text_utils import _normalize_text, REGEX_CAT_CLEAN
from src.finance_logic import classify_transfer, get_category_by_mcc, make_short_id_vectorized
from config import (
    COL_ID, COL_DATE, COL_CAT, COL_CARD, COL_DESC, COL_AMOUNT, COL_BALANCE, COL_MCC,
    IBAN_TO_CARD_MAP, CARDS_DICTIONARY, USEFUL_COLUMNS,
    MCC_MAP, CATEGORIES_KEYWORDS, INCOME_CATEGORIES, EXPENSES_CATEGORIES, AMBIGUOUS_CATEGORIES
)

logger = logging.getLogger(__name__)

ALLOWED_CATEGORIES = {
    # Витрати
    'витрати на авто', 'громадський транспорт', 'житло та побут', 'зв\'язок', 
    'здоров\'я та краса', 'одяг та взуття', 'зняття готівки', 'компослуги',  
    'переказ на чужий рахунок', 'переказ на власний рахунок', 'поштові послуги', 
    'продукти', 'ресторани та розваги', 'спорт', 'техніка і цифрові товари', 
    'оплата кредитів', 'інші витрати', 'інвестиції',
    # Надходження
    'бонуси та кешбек', 'зарплата і виплати', 'інші надходження', 
    'переказ з власного рахунку', 'переказ з чужого рахунку', 'поповнення готівкою', 'транзит Віка'
}

def standardize_df(df: pd.DataFrame) -> pd.DataFrame:
    """Приведення DataFrame до єдиного стандарту колонок."""
    if df is None or df.empty: return df
    
    # 1. Очищення та приведення до нижнього регістру для пошуку
    df.columns = [" ".join(str(c).split()).lower() for c in df.columns]
    df = df.loc[:, ~df.columns.duplicated()]

    # 2. Мапінг варіацій назв у канонічні константи з config.py
    canonical_map = {
        COL_ID.lower(): COL_ID,
        "дата": COL_DATE, "дата і час": COL_DATE, "дата і час операції": COL_DATE, "дата операції": COL_DATE,
        "сума": COL_AMOUNT, "сума у валюті картки": COL_AMOUNT, "сума (uah)": COL_AMOUNT, "сума у валюті карти (uah)": COL_AMOUNT,
        "залишок": COL_BALANCE, "баланс": COL_BALANCE, "залишок після операції": COL_BALANCE, "залишок на кінець періоду": COL_BALANCE,
        "опис": COL_DESC, "опис операції": COL_DESC, "деталі": COL_DESC, "деталі операції": COL_DESC,
        "картка": COL_CARD, "номер картки": COL_CARD,
        "mcc": COL_MCC, "мсс": COL_MCC, "категорія": COL_CAT
    }
    
    # Перейменовуємо лише ті, що знайшли
    df = df.rename(columns={k: v for k, v in canonical_map.items() if k in df.columns})

    # 3. Логіка визначення категорії
    if COL_CAT not in df.columns:
        df[COL_CAT] = pd.NA
    else:
        # Очищаємо колонку від строкових плейсхолдерів порожніх значень
        df[COL_CAT] = df[COL_CAT].astype(str).str.strip().replace(
            ['nan', 'None', 'nan nan', '', '-', '<NA>'], pd.NA
        )

    # Заповнення пропусків у картці
    if COL_CARD in df.columns:
        placeholders = ['nan', 'None', '-', '', 'nan nan', 'x', 'X', 'х', 'Х', 'Невідома картка']
        df[COL_CARD] = df[COL_CARD].astype(str).str.strip().replace(placeholders, pd.NA)
        df[COL_CARD] = df[COL_CARD].ffill().bfill().fillna('Невідома картка')
    else:
        df[COL_CARD] = 'Невідома картка'

    if COL_BALANCE not in df.columns:
        df[COL_BALANCE] = 0.0

    # Гарантуємо наявність усіх цільових колонок, щоб уникнути KeyError
    for col in USEFUL_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
    return df

def clean_and_transform(df: pd.DataFrame) -> pd.DataFrame:
    """Фінальна векторизована обробка даних за принципом 'Keyword First'."""
    for col in [COL_AMOUNT, COL_BALANCE]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.replace(r'\s+', '', regex=True).str.replace(',', '.', regex=False)
            df[col] = df[col].str.extract(r'(-?\d+\.?\d*)')[0]
            df[col] = pd.to_numeric(df[col], errors='coerce')

    # Попередня корекція знаку для технічних категорій (якщо банк не вказав мінус)
    expense_keywords = ['Покупка', 'Списання', 'Комісія', 'Видача готівки', 'Оплата']
    if COL_CAT in df.columns and COL_AMOUNT in df.columns:
        # Тимчасово приводимо до строки для маски
        mask = df[COL_CAT].astype(str).str.contains('|'.join(expense_keywords), case=False, na=False)
        df.loc[mask & (df[COL_AMOUNT] > 0), COL_AMOUNT] *= -1

    # --- Лійка рішень (Decision Funnel) за принципом "Keyword First" ---
    if COL_CAT in df.columns:
        # – Нормалізуємо початкову категорію банку (якщо вона є)
        df[COL_CAT] = df[COL_CAT].astype(str).str.strip().replace(
            ['nan', 'None', 'nan nan', '', '-', '<NA>'], pd.NA
        )

        # Створюємо тимчасову серію для класифікації
        final_cat = pd.Series(pd.NA, index=df.index, dtype='object')

        # 1. Нормалізація опису (викликається перед пошуком за ключовими словами)
        desc_norm = _normalize_text(df[COL_DESC]) if COL_DESC in df.columns else pd.Series()

        # ======================================================================
        # ПРІОРИТЕТ №1 (Найвищий): Пошук за ключовими словами (CATEGORIES_KEYWORDS)
        # ======================================================================
        if not desc_norm.empty:
            # Розділяємо категорії на витрати та надходження для пріоритизації за знаком суми
            expense_cats = [cat for cat in CATEGORIES_KEYWORDS.keys() if cat in EXPENSES_CATEGORIES]
            income_cats = [cat for cat in CATEGORIES_KEYWORDS.keys() if cat in INCOME_CATEGORIES]
            other_cats = [cat for cat in CATEGORIES_KEYWORDS.keys() if cat not in expense_cats and cat not in income_cats]

            # Визначаємо маски для знаку суми
            is_neg = df[COL_AMOUNT] < 0 if COL_AMOUNT in df.columns else pd.Series(True, index=df.index)
            is_pos = ~is_neg

            # Збираємо пари (keyword, category) та сортуємо за довжиною ключового слова (від найдовших до найкоротших)
            expense_kw_pairs = [(kw, cat) for cat in expense_cats for kw in CATEGORIES_KEYWORDS[cat]]
            expense_kw_pairs.sort(key=lambda x: len(x[0]), reverse=True)

            income_kw_pairs = [(kw, cat) for cat in income_cats for kw in CATEGORIES_KEYWORDS[cat]]
            income_kw_pairs.sort(key=lambda x: len(x[0]), reverse=True)

            other_kw_pairs = [(kw, cat) for cat in other_cats for kw in CATEGORIES_KEYWORDS[cat]]
            other_kw_pairs.sort(key=lambda x: len(x[0]), reverse=True)

            def match_categories_sorted(kw_cat_pairs, row_mask):
                for kw, cat in kw_cat_pairs:
                    pattern = rf'\b{re.escape(kw.lower().replace("i", "і"))}'
                    mask = desc_norm.str.contains(pattern, na=False, regex=True) & row_mask
                    if cat in ['переказ на власний рахунок', 'переказ з власного рахунку']:
                        # Враховуємо знак суми для внутрішніх переказів
                        for idx in df[mask & final_cat.isna()].index:
                            try:
                                amount = float(df.loc[idx, COL_AMOUNT] or 0)
                            except (ValueError, TypeError):
                                amount = 0.0
                            final_cat.loc[idx] = 'переказ на власний рахунок' if amount < 0 else 'переказ з власного рахунку'
                    else:
                        final_cat.loc[mask & final_cat.isna()] = cat

            # 1. Першочергово матчимо категорії, що відповідають знаку транзакції (Захист від перехресних збігів)
            match_categories_sorted(expense_kw_pairs, is_neg)
            match_categories_sorted(income_kw_pairs, is_pos)

            # 2. Другочергово матчимо категорії іншого знаку як резерв
            match_categories_sorted(income_kw_pairs, is_neg)
            match_categories_sorted(expense_kw_pairs, is_pos)
            match_categories_sorted(other_kw_pairs, pd.Series(True, index=df.index))

        # Валідація знаку суми: якщо категорія з INCOME_CATEGORIES отримала негативну суму, змінюємо на 'інші витрати'
        if COL_AMOUNT in df.columns:
            income_mask = final_cat.isin(INCOME_CATEGORIES)
            neg_mask = df[COL_AMOUNT] < 0
            final_cat.loc[income_mask & neg_mask] = 'інші витрати'

        # --- Супутні правила на основі опису ---
        # Крок 1.1: Розумні перекази (Власний vs Чужий)
        if COL_DESC in df.columns and COL_CARD in df.columns and COL_AMOUNT in df.columns:
            transfer_keywords = ['переказ', 'to card', 'на картку']
            
            # P2P патерни: тільки цифри/зірочки або тільки ім'я власника
            is_only_card = df[COL_DESC].astype(str).str.match(r'^[\d\s*]+$', na=False)
            name_regex = r'^[A-ZА-ЯІЄЇ][a-zа-яієїi\']+(\s+[A-ZА-ЯІЄЇ]\.?|\s+[A-ZА-ЯІЄЇ][a-zа-яієїi\']+)?$'
            is_only_name = df[COL_DESC].astype(str).str.match(name_regex, na=False)
            name_init_pattern = r'(?:[A-ZА-ЯІЄЇ][a-zа-яієїi\']+\s+[A-ZА-ЯІЄЇ]\.?|[A-ZА-ЯІЄЇ]\.?\s+[A-ZА-ЯІЄЇ][a-zа-яієїi\']+)'
            has_name_initial = df[COL_DESC].astype(str).str.contains(name_init_pattern, na=False, regex=True)
            
            for idx, row in df.iterrows():
                desc = str(row.get(COL_DESC, ''))
                desc_lower = desc.lower()
                
                is_transfer = any(tk in desc_lower for tk in transfer_keywords) or \
                              is_only_card.loc[idx] or \
                              is_only_name.loc[idx] or \
                              has_name_initial.loc[idx]
                              
                # Або якщо категорія вже визначена як переказ/P2P
                current_cat = final_cat.loc[idx]
                if not pd.isna(current_cat) and ('переказ' in str(current_cat).lower() or 'p2p' in str(current_cat).lower()):
                    is_transfer = True
                    
                if is_transfer and pd.isna(final_cat.loc[idx]):
                    try:
                        amount = float(row.get(COL_AMOUNT, 0) or 0)
                    except (ValueError, TypeError):
                        amount = 0.0
                        
                    own_card = str(row.get(COL_CARD, ''))
                    final_cat.loc[idx] = classify_transfer(desc, amount, own_card)

        # ======================================================================
        # ПРІОРИТЕТ №2 (Резервний): Категорія від банку або MCC
        # ======================================================================
        # 2.1. Категорія від MCC
        mcc_cats = pd.Series(pd.NA, index=df.index, dtype='object')
        if COL_MCC in df.columns:
            mcc_series = df[COL_MCC].astype(str).str.extract(r'(\d{4})')[0]
            mcc_cats = mcc_series.map(get_category_by_mcc)

        # 2.2. Категорія з опису за допомогою REGEX_CAT_CLEAN (для Альянс банку)
        desc_regex_cats = pd.Series(pd.NA, index=df.index, dtype='object')
        if COL_DESC in df.columns:
            desc_regex_cats = df[COL_DESC].astype(str).str.extract(REGEX_CAT_CLEAN)[0].str.strip()

        # Об'єднуємо резервні категорії:
        fallback_cat = df[COL_CAT].fillna(mcc_cats).fillna(desc_regex_cats)
        final_cat = final_cat.fillna(fallback_cat)

        # Записуємо фінальний результат назад у DataFrame
        df[COL_CAT] = final_cat

        # Визначаємо набір усіх дозволених категорій (білий список)
        # Використовуємо .keys(), бо тепер назви категорій — це КЛЮЧІ в MCC_MAP
        final_categories = set(MCC_MAP.keys()) | set(CATEGORIES_KEYWORDS.keys()) | \
                           set(INCOME_CATEGORIES) | set(EXPENSES_CATEGORIES)

        # --- Додатковий крок: Bank Remapping (Очищення/перейменування категорій банку) ---
        for cat, keywords in CATEGORIES_KEYWORDS.items():
            for kw in keywords:
                is_not_standardized = ~df[COL_CAT].isin(final_categories) | df[COL_CAT].isin(AMBIGUOUS_CATEGORIES)
                mask = is_not_standardized & \
                       df[COL_CAT].astype(str).str.contains(kw, case=False, na=False, regex=False) & \
                       (~df[COL_CAT].astype(str).str.contains('власний рахунок', na=False))
                df.loc[mask, COL_CAT] = cat

        # --- Контекстні правила (Врахування знаку суми) ---
        if COL_AMOUNT in df.columns:
            # Розділення власних переказів (якщо потрапили через CATEGORIES_KEYWORDS або старі категорії)
            mask_internal = df[COL_CAT].isin([
                'переказ між власними рахунками', 
                'переказ на власний рахунок', 
                'переказ з власного рахунку',
                'переказ на свою картку'
            ])
            df.loc[mask_internal & (df[COL_AMOUNT] < 0), COL_CAT] = 'переказ на власний рахунок'
            df.loc[mask_internal & (df[COL_AMOUNT] > 0), COL_CAT] = 'переказ з власного рахунку'

        # ======================================================================
        # SELF-CLEANING: Фінальна валідація знаку суми (Розділ 7 Паспорта проєкту)
        # ======================================================================
        if COL_AMOUNT in df.columns:
            # Правило 7.1 (Захист доходів): категорія з INCOME_CATEGORIES + від'ємна сума → 'інші витрати'
            income_mask = df[COL_CAT].isin(INCOME_CATEGORIES)
            neg_mask = df[COL_AMOUNT] < 0
            df.loc[income_mask & neg_mask, COL_CAT] = 'інші витрати'

            # Правило 7.2 (Захист витрат): категорія з EXPENSES_CATEGORIES + позитивна сума → 'інші надходження'
            # Виключаємо переказ-категорії — їхній знак управляється окремою логікою (detect_internal_transfers)
            transfer_cats = {
                'переказ на власний рахунок', 'переказ з власного рахунку',
                'переказ на чужий рахунок', 'переказ з чужого рахунку',
            }
            pure_expense_cats = set(EXPENSES_CATEGORIES) - transfer_cats
            expenses_mask = df[COL_CAT].isin(pure_expense_cats)
            pos_mask = df[COL_AMOUNT] > 0
            df.loc[expenses_mask & pos_mask, COL_CAT] = 'інші надходження'

            # Правило 7.3 (Корекція напряму зовнішніх переказів за знаком суми)
            # Виправляє кейс Альянс Банку: банк пише 'Переказ на картку' як опис,
            # але сума позитивна (це вхідний переказ), тому категорія має бути 'з чужого рахунку'
            mask_wrong_in  = (df[COL_CAT] == 'переказ на чужий рахунок') & (df[COL_AMOUNT] > 0)
            mask_wrong_out = (df[COL_CAT] == 'переказ з чужого рахунку') & (df[COL_AMOUNT] < 0)
            df.loc[mask_wrong_in,  COL_CAT] = 'переказ з чужого рахунку'
            df.loc[mask_wrong_out, COL_CAT] = 'переказ на чужий рахунок'

        # --- Фінальний Fallback (Перевірка білого списку) ---
        whitelist_mask = ~df[COL_CAT].isin(ALLOWED_CATEGORIES) | df[COL_CAT].isna()
        if COL_AMOUNT in df.columns:
            df.loc[whitelist_mask & (df[COL_AMOUNT] < 0), COL_CAT] = 'інші витрати'
            df.loc[whitelist_mask & (df[COL_AMOUNT] >= 0), COL_CAT] = 'інші надходження'
        else:
            df.loc[whitelist_mask, COL_CAT] = 'інші витрати'

    if COL_DATE in df.columns:
        if not pd.api.types.is_datetime64_any_dtype(df[COL_DATE]):
            df[COL_DATE] = df[COL_DATE].astype(str).str.replace('\xa0', ' ', regex=False)
            df[COL_DATE] = df[COL_DATE].str.replace(r'\s+', ' ', regex=True).str.strip()
    
    df[COL_DATE] = pd.to_datetime(df[COL_DATE], dayfirst=True, errors='coerce')
    df[COL_CARD] = df[COL_CARD].astype(str).replace(CARDS_DICTIONARY)
    
    return df[df[COL_DATE].notna()].copy()

def reconcile_and_merge(new_data: pd.DataFrame, df_base: pd.DataFrame) -> pd.DataFrame:
    """Порівнює нові дані з існуючою базою, уникаючи дублікатів."""
    if df_base.empty:
        new_data[COL_ID] = make_short_id_vectorized(new_data)
        return new_data

    if COL_ID in df_base.columns:
        df_base[COL_ID] = df_base[COL_ID].astype(str).str.zfill(8)

    if not pd.api.types.is_datetime64_any_dtype(df_base[COL_DATE]):
        df_base[COL_DATE] = pd.to_datetime(df_base[COL_DATE], dayfirst=True, errors='coerce')
        
    df_base[COL_AMOUNT] = pd.to_numeric(df_base[COL_AMOUNT], errors='coerce')
    df_base[COL_BALANCE] = pd.to_numeric(df_base[COL_BALANCE], errors='coerce')
    
    keys = [COL_DATE, COL_CARD, COL_DESC, COL_AMOUNT]
    df_base_keys = df_base[keys].drop_duplicates()
    
    merged = new_data.merge(df_base_keys, on=keys, how='left', indicator=True)
    unique_new = new_data[merged['_merge'] == 'left_only'].copy()
    
    count_new = len(unique_new)
    count_dupes = len(new_data) - count_new
    
    if not unique_new.empty:
        logger.info(f"Звірка: додано {count_new} нових транзакцій. Відфільтровано {count_dupes} дублікатів.")
        unique_new[COL_ID] = make_short_id_vectorized(unique_new)
        return pd.concat([df_base, unique_new], ignore_index=True)
    
    return df_base
