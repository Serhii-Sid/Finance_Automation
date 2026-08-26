import re
import hashlib
import logging
import pandas as pd
from typing import Optional
from text_utils import _normalize_text
from config import (
    CARDS_DICTIONARY, CATEGORIES_KEYWORDS, INCOME_CATEGORIES, AMBIGUOUS_CATEGORIES,
    COL_DESC, COL_CAT, COL_AMOUNT, COL_CARD, COL_DATE, COL_BALANCE, COL_ID, MCC_MAP, EXPENSES_CATEGORIES
)

logger = logging.getLogger(__name__)

def make_short_id_vectorized(df: pd.DataFrame) -> pd.Series:
    """Генерація унікальних ID для транзакцій."""
    combined = (
        df[COL_DATE].dt.strftime('%Y-%m-%d %H:%M:%S') + "_" + 
        df[COL_CARD].astype(str) + "_" + 
        df[COL_AMOUNT].map('{:.2f}'.format)
    )
    return combined.apply(lambda x: str(int(hashlib.md5(x.encode()).hexdigest()[:8], 16) % 10**8).zfill(8))

def classify_transfer(desc: str, amount: float, own_card: str) -> str:
    """
    Класифікує переказ на власний чи чужий рахунок.
    """
    # 1. Знаходимо всі 4-значні послідовності цифр в описі
    desc_digits = re.findall(r'(?<!\d)\d{4}(?!\d)', desc)
    
    # 2. Визначаємо суфікси власної картки
    own_suffixes = set()
    for d in re.findall(r'\d{4}', str(own_card)):
        own_suffixes.add(d)
    for d, name in CARDS_DICTIONARY.items():
        if name == own_card or name in str(own_card) or str(own_card) in name:
            own_suffixes.add(d)
            
    # 3. Виключаємо суфікси власної карти
    other_digits = [d for d in desc_digits if d not in own_suffixes]
    
    # 4. Перевіряємо, чи є серед інших цифр суфікс якоїсь іншої нашої карти
    has_other_own_card = False
    for d in other_digits:
        if d in CARDS_DICTIONARY:
            has_other_own_card = True
            break
            
    if has_other_own_card:
        return 'переказ на власний рахунок' if amount < 0 else 'переказ з власного рахунку'
    else:
        return 'переказ на чужий рахунок' if amount < 0 else 'переказ з чужого рахунку'

def get_category_by_mcc(mcc_code) -> Optional[str]:
    """
    Знаходить назву категорії за кодом MCC у новій структурі MCC_MAP.

    MCC_MAP має структуру: {'Назва категорії': ['код1', 'код2', ...]}
    Функція ітерує через всі категорії та їхні списки кодів,
    повертаючи назву категорії, якщо вхідний код знайдено.

    Args:
        mcc_code: Код MCC (може бути рядком, int або float, наприклад '5411', 5411, 5411.0).

    Returns:
        Назва категорії або None, якщо код не знайдено.
    """
    if mcc_code is None:
        return None
    # Нормалізуємо код: видаляємо '.0' (якщо прийшов як float), зберігаємо рядок
    clean_code = str(mcc_code).strip()
    if clean_code.endswith('.0'):
        clean_code = clean_code[:-2]
    if not clean_code or clean_code in ('nan', 'None', ''):
        return None
    for category, codes in MCC_MAP.items():
        if clean_code in codes:
            return category
    return None

def apply_bank_specific_post_processing(df: pd.DataFrame) -> pd.DataFrame:
    """
    Застосовує коригування для специфічних банків (наприклад, ПУМБ).
    Тут ми рахуємо накопичувальний баланс, якщо він не надається банком.
    """
    pumb_cards = [v for v in CARDS_DICTIONARY.values() if 'ПУМБ' in v]
    if not pumb_cards:
        return df

    df = df.copy()
    df[COL_BALANCE] = df[COL_BALANCE].astype(float)
    
    for card_name in pumb_cards:
        if card_name in df[COL_CARD].values:
            mask = df[COL_CARD] == card_name
            # Сортуємо від старих до нових для розрахунку cumsum
            df_card = df[mask].sort_values(by=COL_DATE)
            df.loc[df_card.index, COL_BALANCE] = df_card[COL_AMOUNT].fillna(0).cumsum()
            
    return df

def adjust_balance_with_credit_limit(df: pd.DataFrame, credit_limit: float) -> pd.DataFrame:
    """
    Adjusts the balance column by subtracting the credit limit.
    Assumes COL_BALANCE is present and numeric-like.
    """
    if df is None or df.empty or COL_BALANCE not in df.columns or credit_limit <= 0:
        return df

    # Make a copy to avoid SettingWithCopyWarning
    df_copy = df.copy()

    def adjust(val):
        try:
            s = str(val).replace('\xa0', '').replace(' ', '').replace(',', '.')
            m = re.search(r'(-?\d+\.?\d*)', s)
            if m:
                return float(m.group(1)) - credit_limit
            return val
        except Exception:
            return val
    df_copy[COL_BALANCE] = df_copy[COL_BALANCE].apply(adjust)
    return df_copy

def detect_internal_transfers(df: pd.DataFrame) -> pd.DataFrame:
    """
    Інтелектуальне розпізнавання внутрішніх переказів між власними рахунками.
    Аналізує весь підсумковий DataFrame перед збереженням.

    Етап 1 (За масками): Шукає в описі будь-які 4 цифри, що збігаються з останніми 
    цифрами карток (0550, 7854, 4169, 0707, 0627, 4258, 4882, 6333, 4805, 0950).
    Якщо знайдено — присвоює категорію 'переказ на власний рахунок' (якщо сума від'ємна)
    або 'переказ з власного рахунку' (якщо сума додатна).

    Етап 2 (За близнюками): Шукає пари транзакцій з однаковою сумою (різними знаками)
    та однаковим часом (з точністю до хвилини). Маркує їх як внутрішні перекази.
    """
    if df is None or df.empty:
        return df

    df = df.reset_index(drop=True)

    # 0. Пріоритет брендів: Класифікуємо/захищаємо категорію брендів перед перевірками
    # Це гарантує, що ключові слова з CATEGORIES_KEYWORDS мають найвищий пріоритет
    desc_norm = _normalize_text(df[COL_DESC]) if COL_DESC in df.columns else pd.Series()
    if not desc_norm.empty:
        final_cat = df[COL_CAT].copy()
        protected_cats = set(CATEGORIES_KEYWORDS.keys()) - {'переказ на власний рахунок', 'переказ з власного рахунку'}
        
        for cat, keywords in CATEGORIES_KEYWORDS.items():
            for kw in keywords:
                pattern = rf'\b{re.escape(kw.lower().replace("i", "і"))}'
                mask = desc_norm.str.contains(pattern, na=False, regex=True)
                
                # Дозволяємо перезапис тільки якщо поточне значення не є захищеною категорією
                can_overwrite = ~final_cat.isin(protected_cats) | final_cat.isna()
                
                if cat in ['переказ на власний рахунок', 'переказ з власного рахунку']:
                    # Враховуємо знак суми для внутрішніх переказів
                    for idx in df[mask & can_overwrite].index:
                        try:
                            amount = float(df.loc[idx, COL_AMOUNT] or 0)
                        except (ValueError, TypeError):
                            amount = 0.0
                        final_cat.loc[idx] = 'переказ на власний рахунок' if amount < 0 else 'переказ з власного рахунку'
                else:
                    final_cat.loc[mask & can_overwrite] = cat

        # Валідація знаку суми: якщо категорія з INCOME_CATEGORIES отримала негативну суму, змінюємо на 'інші витрати'
        if COL_AMOUNT in df.columns:
            income_mask = final_cat.isin(INCOME_CATEGORIES)
            neg_mask = df[COL_AMOUNT] < 0
            final_cat.loc[income_mask & neg_mask] = 'інші витрати'
        df[COL_CAT] = final_cat

    # Створюємо набір кандидатів для аналізу (Зв'язок та інші бренд-категорії не чіпаємо)
    candidate_cats = set(AMBIGUOUS_CATEGORIES) | {
        'перекази', 'переказ коштів', 'переказ між власними рахунками',
        'переказ на власний рахунок', 'переказ з власного рахунку',
        'переказ на чужий рахунок', 'переказ з чужого рахунку',
        'інші витрати', 'інші надходження'
    }

    # Маски (останні 4 цифри власних карток)
    target_suffixes = {'0550', '7854', '4169', '0707', '0627', '4258', '4882', '6333', '4805', '0950'}

    changed_mask = 0
    changed_twin = 0
    validated_own_indices = set()

    # Етап 1 (За масками)
    # Скануємо всі рядки, які є кандидатами
    if COL_CAT in df.columns:
        candidates_idx = df[df[COL_CAT].isin(candidate_cats)].index
    else:
        candidates_idx = df.index

    for idx in candidates_idx:
        row = df.loc[idx]
        desc = str(row.get(COL_DESC, ''))
        own_card = str(row.get(COL_CARD, ''))
        
        # Визначаємо суфікси власної картки
        own_suffixes = set()
        for d in re.findall(r'\d{4}', own_card):
            own_suffixes.add(d)
        for d, name in CARDS_DICTIONARY.items():
            if name == own_card or name in own_card or own_card in name:
                own_suffixes.add(d)

        # Шукаємо standalone 4-значні числа в описі
        # Використовуємо regex, щоб уникнути витягування 4-значних частин з довших чисел (як IBAN)
        digits4 = re.findall(r'(?<!\d)\d{4}(?!\d)', desc)
        matched_suffix = None
        for d in digits4:
            if d in target_suffixes and d not in own_suffixes:
                matched_suffix = d
                break
        
        if matched_suffix:
            try:
                amount = float(row.get(COL_AMOUNT, 0) or 0)
            except (ValueError, TypeError):
                amount = 0.0
                
            new_cat = 'переказ на власний рахунок' if amount < 0 else 'переказ з власного рахунку'
            
            validated_own_indices.add(idx)
            
            if df.loc[idx, COL_CAT] != new_cat:
                df.loc[idx, COL_CAT] = new_cat
                changed_mask += 1
                logger.info(
                    f"detect_internal_transfers (Етап 1: Маска): idx={idx}, "
                    f"desc='{desc[:60]}', amount={amount:.2f}, matched_suffix='{matched_suffix}' → '{new_cat}'"
                )

    # Етап 2 (За близнюками) — двохфазне спарювання
    # Фаза А: Точний збіг абсолютних сум (оригінальна логіка).
    # Фаза Б: М'який збіг з допуском на комісію (до 1% або 100 грн),
    #          тільки якщо ОБИДВІ картки є власними (є в CARDS_DICTIONARY).
    # В обох фазах: різні картки + часовий ліміт <= 5 хвилин.

    own_card_names = set(CARDS_DICTIONARY.values())

    def to_naive(t):
        return t.replace(tzinfo=None) if t.tzinfo is not None else t

    valid_mask = df[COL_AMOUNT].notna() & df[COL_DATE].notna()
    valid_df = df[valid_mask].copy()
    valid_df['abs_amount'] = valid_df[COL_AMOUNT].abs().round(2)
    valid_df = valid_df[valid_df['abs_amount'] > 0]
    valid_df['naive_date'] = valid_df[COL_DATE].apply(to_naive)

    overwrite_cats = set(AMBIGUOUS_CATEGORIES) | {
        'перекази', 'переказ коштів', 'переказ між власними рахунками',
        'переказ на власний рахунок', 'переказ з власного рахунку',
        'переказ на чужий рахунок', 'переказ з чужого рахунку',
        'інші витрати', 'інші надходження'
    }

    twin_indices = set()          # (neg_idx, pos_idx) — підтверджені пари
    already_matched = set()       # індекси, що вже спаровані
    splits_to_apply = []          # [(neg_idx, pos_idx, abs_pos, commission)] - пари для розщеплення

    pos_all = valid_df[valid_df[COL_AMOUNT] > 0].sort_values('naive_date')
    neg_all = valid_df[valid_df[COL_AMOUNT] < 0].sort_values('naive_date')

    # ---------- Фаза А: Точний збіг (abs_neg == abs_pos) ----------
    grouped = valid_df.groupby('abs_amount')
    for abs_amt, group in grouped:
        if len(group) < 2:
            continue
        pos_g = group[group[COL_AMOUNT] > 0].copy()
        neg_g = group[group[COL_AMOUNT] < 0].copy()
        if pos_g.empty or neg_g.empty:
            continue

        matched_pos_phase_a = set()
        for neg_idx, neg_row in neg_g.iterrows():
            if neg_idx in already_matched:
                continue
            best_pos_idx = None
            best_time_diff = pd.Timedelta(days=99999)
            neg_time = neg_row['naive_date']
            neg_card = neg_row[COL_CARD]

            for pos_idx, pos_row in pos_g.iterrows():
                if pos_idx in matched_pos_phase_a or pos_idx in already_matched:
                    continue
                if pos_row[COL_CARD] == neg_card:
                    continue
                time_diff = abs(neg_time - pos_row['naive_date'])
                if time_diff <= pd.Timedelta(minutes=5) and time_diff < best_time_diff:
                    best_time_diff = time_diff
                    best_pos_idx = pos_idx

            if best_pos_idx is not None:
                matched_pos_phase_a.add(best_pos_idx)
                twin_indices.add((neg_idx, best_pos_idx))
                already_matched.add(neg_idx)
                already_matched.add(best_pos_idx)

    # ---------- Фаза Б: М'який збіг з допуском на комісію ----------
    # Умови: abs_neg > abs_pos, різниця <= max(abs_neg * 0.01, 100 грн),
    #         обидві картки є власними (в CARDS_DICTIONARY), різні картки, час <= 5 хв
    COMMISSION_PCT  = 0.01   # 1%
    COMMISSION_FLAT = 100.0  # 100 грн — абсолютний мінімальний допуск

    for neg_idx, neg_row in neg_all.iterrows():
        if neg_idx in already_matched:
            continue
        abs_neg   = neg_row['abs_amount']
        neg_time  = neg_row['naive_date']
        neg_card  = neg_row[COL_CARD]

        # М'який матч вимагає, щоб картка-відправник була власною
        if neg_card not in own_card_names:
            continue

        max_commission = max(abs_neg * COMMISSION_PCT, COMMISSION_FLAT)

        best_pos_idx   = None
        best_time_diff = pd.Timedelta(days=99999)

        for pos_idx, pos_row in pos_all.iterrows():
            if pos_idx in already_matched:
                continue
            pos_card = pos_row[COL_CARD]
            if pos_card == neg_card:
                continue
            # Картка-отримувач також має бути власною
            if pos_card not in own_card_names:
                continue

            abs_pos = pos_row['abs_amount']
            # Прихід має бути меншим або рівним списанню (комісія знімається з відправника)
            if not (abs_pos <= abs_neg and (abs_neg - abs_pos) <= max_commission):
                continue

            time_diff = abs(neg_time - pos_row['naive_date'])
            if time_diff <= pd.Timedelta(minutes=5) and time_diff < best_time_diff:
                best_time_diff = time_diff
                best_pos_idx   = pos_idx

        if best_pos_idx is not None:
            abs_pos = pos_all.loc[best_pos_idx, 'abs_amount']
            commission = abs_neg - abs_pos
            logger.info(
                f"detect_internal_transfers (Фаза Б: Комісія): "
                f"neg_idx={neg_idx} ({abs_neg:.2f}) + pos_idx={best_pos_idx} ({abs_pos:.2f}), "
                f"комісія={commission:.2f} грн, час={best_time_diff}"
            )
            if commission > 0:
                splits_to_apply.append((neg_idx, best_pos_idx, abs_pos, commission))
            else:
                twin_indices.add((neg_idx, best_pos_idx))
            already_matched.add(neg_idx)
            already_matched.add(best_pos_idx)

    # ---------- Маркування знайдених пар (без комісійного розщеплення) ----------
    for neg_idx, pos_idx in twin_indices:
        validated_own_indices.add(neg_idx)
        validated_own_indices.add(pos_idx)

        # Для витрати (neg)
        row_neg = df.loc[neg_idx]
        current_cat_neg = row_neg.get(COL_CAT)
        if pd.isna(current_cat_neg) or current_cat_neg in overwrite_cats:
            if df.loc[neg_idx, COL_CAT] != 'переказ на власний рахунок':
                df.loc[neg_idx, COL_CAT] = 'переказ на власний рахунок'
                changed_twin += 1
                logger.info(
                    f"detect_internal_transfers (Етап 2: Близнюки витрата): idx={neg_idx}, "
                    f"desc='{str(row_neg.get(COL_DESC, ''))[:60]}', amount={row_neg.get(COL_AMOUNT):.2f} → 'переказ на власний рахунок'"
                )

        # Для доходу (pos)
        row_pos = df.loc[pos_idx]
        current_cat_pos = row_pos.get(COL_CAT)
        if pd.isna(current_cat_pos) or current_cat_pos in overwrite_cats:
            if df.loc[pos_idx, COL_CAT] != 'переказ з власного рахунку':
                df.loc[pos_idx, COL_CAT] = 'переказ з власного рахунку'
                changed_twin += 1
                logger.info(
                    f"detect_internal_transfers (Етап 2: Близнюки дохід): idx={pos_idx}, "
                    f"desc='{str(row_pos.get(COL_DESC, ''))[:60]}', amount={row_pos.get(COL_AMOUNT):.2f} → 'переказ з власного рахунку'"
                )

    # ---------- Застосування розщеплення транзакцій при наявності комісії ----------
    if splits_to_apply:
        new_rows_list = []
        indices_to_drop = []
        for neg_idx, pos_idx, abs_pos, commission in splits_to_apply:
            row_neg = df.loc[neg_idx]
            
            # 1. Основне тіло переказу
            body_row = row_neg.copy()
            body_row[COL_AMOUNT] = -abs_pos
            body_row[COL_CAT] = 'переказ на власний рахунок'
            
            # 2. Комісія
            commission_row = row_neg.copy()
            commission_row[COL_AMOUNT] = -commission
            commission_row[COL_CAT] = 'інші витрати'
            
            new_rows_list.append(body_row)
            new_rows_list.append(commission_row)
            indices_to_drop.append(neg_idx)
            
            # Маркуємо вхідну транзакцію як переказ
            validated_own_indices.add(pos_idx)
            if df.loc[pos_idx, COL_CAT] != 'переказ з власного рахунку':
                df.loc[pos_idx, COL_CAT] = 'переказ з власного рахунку'
                changed_twin += 1
                logger.info(
                    f"detect_internal_transfers (Близнюки дохід при розщепленні): idx={pos_idx}, "
                    f"desc='{str(df.loc[pos_idx, COL_DESC])[:60]}', amount={df.loc[pos_idx, COL_AMOUNT]:.2f} → 'переказ з власного рахунку'"
                )
        
        # Видаляємо оригінальну транзакцію
        df = df.drop(index=indices_to_drop)
        
        # Створюємо DataFrame з нових рядків
        new_df = pd.DataFrame(new_rows_list)
        # Генеруємо нові унікальні ID
        new_df[COL_ID] = make_short_id_vectorized(new_df)
        
        # Призначаємо нові непересічні індекси для нових рядків
        max_idx = df.index.max() if not df.empty else 0
        new_df.index = range(max_idx + 1, max_idx + 1 + len(new_df))
        
        # Додаємо нові індекси основного тіла переказів до валідованих, щоб уникнути демоції
        for k in range(len(splits_to_apply)):
            body_idx = max_idx + 1 + 2 * k
            validated_own_indices.add(body_idx)
            
        # Об'єднуємо з основним DataFrame
        df = pd.concat([df, new_df])

    # Етап 3 (Демоція непідтверджених власних переказів)
    own_transfer_cats = {
        'переказ на власний рахунок', 
        'переказ з власного рахунку',
        'переказ між власними рахунками',
        'переказ на свою картку'
    }
    
    demoted_count = 0
    for idx, row in df.iterrows():
        current_cat = row.get(COL_CAT)
        if current_cat in own_transfer_cats:
            if idx not in validated_own_indices:
                try:
                    amount = float(row.get(COL_AMOUNT, 0) or 0)
                except (ValueError, TypeError):
                    amount = 0.0
                
                new_cat = 'переказ на чужий рахунок' if amount < 0 else 'переказ з чужого рахунку'
                df.loc[idx, COL_CAT] = new_cat
                demoted_count += 1
                logger.info(
                    f"detect_internal_transfers (Демоція): idx={idx}, "
                    f"desc='{str(row.get(COL_DESC, ''))[:60]}', amount={amount:.2f} → '{new_cat}'"
                )

    logger.info(
        f"detect_internal_transfers завершено: змінено за масками {changed_mask}, "
        f"змінено за близнюками {changed_twin}, демонтовано {demoted_count} транзакцій."
    )

    # Перевірка лімітів доходів: будь-яка категорія з INCOME_CATEGORIES з негативною сумою примусово переводиться в 'інші витрати'
    if COL_AMOUNT in df.columns:
        income_mask = df[COL_CAT].isin(INCOME_CATEGORIES)
        neg_mask = df[COL_AMOUNT] < 0
        df.loc[income_mask & neg_mask, COL_CAT] = 'інші витрати'

    # 4. Фінальний Fallback (Перевірка білого списку) для гарантії відповідності ALLOWED_CATEGORIES
    from data_manager import ALLOWED_CATEGORIES
    whitelist_mask = ~df[COL_CAT].isin(ALLOWED_CATEGORIES) | df[COL_CAT].isna()
    if COL_AMOUNT in df.columns:
        df.loc[whitelist_mask & (df[COL_AMOUNT] < 0), COL_CAT] = 'інші витрати'
        df.loc[whitelist_mask & (df[COL_AMOUNT] >= 0), COL_CAT] = 'інші надходження'
    else:
        df.loc[whitelist_mask, COL_CAT] = 'інші витрати'

    # Сортування за датою для збереження хронології
    df = df.sort_values(by=COL_DATE, ascending=False).reset_index(drop=True)

    return df

def process_cash_clearing(df: pd.DataFrame) -> pd.DataFrame:
    """
    Інтелектуальна компенсація готівкових потоків за місяць через механізм розщеплення транзакцій.
    """
    if df is None or df.empty:
        return df

    df = df.copy()
    if COL_DATE not in df.columns or COL_CAT not in df.columns or COL_AMOUNT not in df.columns:
        return df

    # Додаємо тимчасові колонки для групування
    df['temp_year'] = df[COL_DATE].dt.year
    df['temp_month'] = df[COL_DATE].dt.month

    grouped = df.groupby(['temp_year', 'temp_month'], sort=False)
    
    final_rows = []

    for (yr, mn), group in grouped:
        # Розділяємо на зняття, поповнення та інші
        withdrawals = group[group[COL_CAT] == 'зняття готівки'].sort_values(by=COL_DATE)
        deposits = group[group[COL_CAT] == 'поповнення готівкою'].sort_values(by=COL_DATE)
        others = group[(group[COL_CAT] != 'зняття готівки') & (group[COL_CAT] != 'поповнення готівкою')]

        # Обчислюємо ліміт очищення
        total_out = withdrawals[COL_AMOUNT].sum() # від'ємна
        total_in = deposits[COL_AMOUNT].sum() # позитивна
        
        # Очищення відбувається тільки якщо є обидві операції
        if total_in > 0 and abs(total_out) > 0:
            clearing_limit = min(abs(total_out), total_in)
        else:
            clearing_limit = 0.0

        # Зберігаємо оброблені рядки
        processed_withdrawals = []
        processed_deposits = []

        if clearing_limit > 0:
            # 1. Розподіл зняття (Withdrawals)
            current_sum = 0.0
            for idx, row in withdrawals.iterrows():
                row_abs = abs(row[COL_AMOUNT])
                if current_sum + row_abs <= clearing_limit:
                    # Повністю в межах ліміту
                    processed_withdrawals.append(row.to_dict())
                    current_sum += row_abs
                elif current_sum < clearing_limit:
                    # Частково входить
                    body_abs = clearing_limit - current_sum
                    excess_abs = row_abs - body_abs
                    
                    body_row = row.copy()
                    body_row[COL_AMOUNT] = -body_abs
                    # категорія залишається 'зняття готівки'
                    
                    excess_row = row.copy()
                    excess_row[COL_AMOUNT] = -excess_abs
                    excess_row[COL_CAT] = 'інші витрати'
                    
                    temp_df = pd.DataFrame([body_row])
                    temp_df[COL_DATE] = pd.to_datetime(temp_df[COL_DATE])
                    shared_id = make_short_id_vectorized(temp_df).iloc[0]
                    body_row[COL_ID] = shared_id
                    excess_row[COL_ID] = shared_id
                    
                    processed_withdrawals.append(body_row.to_dict())
                    processed_withdrawals.append(excess_row.to_dict())
                    current_sum = clearing_limit
                else:
                    # Повністю перевищує
                    excess_row = row.copy()
                    excess_row[COL_CAT] = 'інші витрати'
                    processed_withdrawals.append(excess_row.to_dict())
            
            # 2. Розподіл поповнень (Deposits)
            current_sum = 0.0
            for idx, row in deposits.iterrows():
                row_amount = row[COL_AMOUNT]
                if current_sum + row_amount <= clearing_limit:
                    # Повністю в межах ліміту
                    processed_deposits.append(row.to_dict())
                    current_sum += row_amount
                elif current_sum < clearing_limit:
                    # Частково входить
                    body_amount = clearing_limit - current_sum
                    excess_amount = row_amount - body_amount
                    
                    body_row = row.copy()
                    body_row[COL_AMOUNT] = body_amount
                    # категорія залишається 'поповнення готівкою'
                    
                    excess_row = row.copy()
                    excess_row[COL_AMOUNT] = excess_amount
                    excess_row[COL_CAT] = 'інші надходження'
                    
                    temp_df = pd.DataFrame([body_row])
                    temp_df[COL_DATE] = pd.to_datetime(temp_df[COL_DATE])
                    shared_id = make_short_id_vectorized(temp_df).iloc[0]
                    body_row[COL_ID] = shared_id
                    excess_row[COL_ID] = shared_id
                    
                    processed_deposits.append(body_row.to_dict())
                    processed_deposits.append(excess_row.to_dict())
                    current_sum = clearing_limit
                else:
                    # Повністю перевищує
                    excess_row = row.copy()
                    excess_row[COL_CAT] = 'інші надходження'
                    processed_deposits.append(excess_row.to_dict())
        else:
            # Якщо ліміт 0, просто додаємо як є
            processed_withdrawals = withdrawals.to_dict('records')
            processed_deposits = deposits.to_dict('records')

        # Додаємо всі рядки в загальний список
        final_rows.extend(processed_withdrawals)
        final_rows.extend(processed_deposits)
        final_rows.extend(others.to_dict('records'))

    # Reconstruct the DataFrame
    df_new = pd.DataFrame(final_rows)
    df_new = df_new.drop(columns=['temp_year', 'temp_month'], errors='ignore')
    
    # Сортування за датою для збереження хронології
    df_new = df_new.sort_values(by=COL_DATE, ascending=False).reset_index(drop=True)
    return df_new
