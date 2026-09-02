import re
import hashlib
import logging
import pandas as pd
from typing import Optional
from src.text_utils import _normalize_text
from config import (
    CARDS_DICTIONARY, CATEGORIES_KEYWORDS, INCOME_CATEGORIES, AMBIGUOUS_CATEGORIES,
    COL_DESC, COL_CAT, COL_AMOUNT, COL_CARD, COL_DATE, COL_BALANCE, COL_ID, MCC_MAP, EXPENSES_CATEGORIES,
    COL_CLEARING_STATUS
)

logger = logging.getLogger(__name__)

class ReconciliationRegistry:
    _records = []
    
    @classmethod
    def clear(cls):
        cls._records = []
        
    @classmethod
    def register(cls, date_left, id_left, desc_left, amount_left, date_right, id_right, desc_right, amount_right, cleared_amount, remaining_left, clear_type, card_left="", card_right=""):
        cls._records.append({
            'Дата зняття': date_left,
            'ID зняття': id_left,
            'Опис зняття': desc_left,
            'Сума зняття': amount_left,
            'Картка джерела': card_left,
            'Зв\'язок': '➔ ➔ ➔',
            'Дата поповнення': date_right,
            'ID поповнення': id_right,
            'Опис поповнення': desc_right,
            'Сума поповнення': amount_right,
            'Картка отримувача': card_right,
            'Сума компенсації': cleared_amount,
            'Залишок зняття': remaining_left,
            'Тип компенсації': clear_type
        })
        
    @classmethod
    def get_df(cls):
        if not cls._records:
            return pd.DataFrame(columns=[
                'Дата зняття', 'ID зняття', 'Опис зняття', 'Сума зняття', 'Картка джерела',
                'Зв\'язок', 'Дата поповнення', 'ID поповнення', 'Опис поповнення', 'Сума поповнення', 'Картка отримувача',
                'Сума компенсації', 'Залишок зняття', 'Тип компенсації'
            ])
        df = pd.DataFrame(cls._records)
        df['Дата зняття'] = pd.to_datetime(df['Дата зняття'])
        return df.sort_values(by='Дата зняття', ascending=False).reset_index(drop=True)

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

    ReconciliationRegistry.clear()
    df = df.reset_index(drop=True)

    # 0. Пріоритет брендів: Класифікуємо/захищаємо категорію брендів перед перевірками
    # Це гарантує, що ключові слова з CATEGORIES_KEYWORDS мають найвищий пріоритет
    desc_norm = _normalize_text(df[COL_DESC]) if COL_DESC in df.columns else pd.Series()
    if not desc_norm.empty:
        final_cat = df[COL_CAT].copy()
        protected_cats = (set(CATEGORIES_KEYWORDS.keys()) | {'транзит Віка', 'інвестиції'}) - {'переказ на власний рахунок', 'переказ з власного рахунку'}
        
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
            df.loc[idx, COL_CLEARING_STATUS] = 'Внутрішній переказ'
            
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

    def is_own_card(card_val):
        c_str = str(card_val)
        if c_str in own_card_names:
            return True
        for name in own_card_names:
            if name in c_str or c_str in name:
                return True
        for suffix in CARDS_DICTIONARY.keys():
            if suffix in c_str:
                return True
        return False

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
        if not is_own_card(neg_card):
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
            if not is_own_card(pos_card):
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
            twin_indices.add((neg_idx, best_pos_idx))
            already_matched.add(neg_idx)
            already_matched.add(best_pos_idx)

    # ---------- Маркування знайдених пар ----------
    for neg_idx, pos_idx in twin_indices:
        validated_own_indices.add(neg_idx)
        validated_own_indices.add(pos_idx)
        df.loc[neg_idx, COL_CLEARING_STATUS] = 'Внутрішній переказ'
        df.loc[pos_idx, COL_CLEARING_STATUS] = 'Внутрішній переказ'

        row_out = df.loc[neg_idx]
        row_in = df.loc[pos_idx]

        ReconciliationRegistry.register(
            date_left=row_out[COL_DATE],
            id_left=row_out.get(COL_ID, neg_idx),
            desc_left=row_out.get(COL_DESC, ''),
            amount_left=row_out.get(COL_AMOUNT, 0.0),
            date_right=row_in[COL_DATE],
            id_right=row_in.get(COL_ID, pos_idx),
            desc_right=row_in.get(COL_DESC, ''),
            amount_right=row_in.get(COL_AMOUNT, 0.0),
            cleared_amount=abs(float(row_in.get(COL_AMOUNT, 0.0) or 0.0)),
            remaining_left=0.0,
            clear_type='Twins (Картка ➔ Картка)',
            card_left=row_out.get(COL_CARD, ''),
            card_right=row_in.get(COL_CARD, '')
        )

        # Для витрати (neg)
        if df.loc[neg_idx, COL_CAT] != 'переказ на власний рахунок':
            df.loc[neg_idx, COL_CAT] = 'переказ на власний рахунок'
            changed_twin += 1
            logger.info(
                f"detect_internal_transfers (Етап 2: Близнюки витрата): idx={neg_idx}, "
                f"desc='{str(row_out.get(COL_DESC, ''))[:60]}', amount={row_out.get(COL_AMOUNT):.2f} → 'переказ на власний рахунок'"
            )

        # Для доходу (pos)
        if df.loc[pos_idx, COL_CAT] != 'переказ з власного рахунку':
            df.loc[pos_idx, COL_CAT] = 'переказ з власного рахунку'
            changed_twin += 1
            logger.info(
                f"detect_internal_transfers (Етап 2: Близнюки дохід): idx={pos_idx}, "
                f"desc='{str(row_in.get(COL_DESC, ''))[:60]}', amount={row_in.get(COL_AMOUNT):.2f} → 'переказ з власного рахунку'"
            )

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
                df.loc[idx, COL_CLEARING_STATUS] = '-'
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
    from src.data_manager import ALLOWED_CATEGORIES
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
    Математичне ядро компенсації готівки за правилом "Локального пріоритету":
    1. Спочатку зводяться готівкові зняття та поповнення строго FIFO всередині кожного календарного місяця окремо.
    2. Лише якщо після місячного зведення у місяці M+1 залишилися невикористані поповнення (до 10 числа включно),
       вони використовуються для компенсації залишків зняття з попереднього місяця M.
    Повертає новий аналітичний DataFrame (df_analytical) зі розщепленими рядками.
    Вхідний DataFrame (df) залишається 100% незмінним.
    """
    if df is None or df.empty:
        return df

    if COL_DATE not in df.columns or COL_CAT not in df.columns or COL_AMOUNT not in df.columns:
        return df

    # 1. Відокремлення 3-х груп транзакцій
    mask_withdrawals = (df[COL_CAT] == 'зняття готівки') & (df[COL_AMOUNT] < 0)
    mask_deposits = (df[COL_CAT] == 'поповнення готівкою') & (df[COL_AMOUNT] > 0)

    others_df = df[~(mask_withdrawals | mask_deposits)].copy()
    withdrawals_df = df[mask_withdrawals].sort_values(by=COL_DATE, ascending=True).copy()
    deposits_df = df[mask_deposits].sort_values(by=COL_DATE, ascending=True).copy()

    if withdrawals_df.empty or deposits_df.empty:
        return df.sort_values(by=COL_DATE, ascending=False).reset_index(drop=True)

    def to_naive(t):
        if hasattr(t, 'tzinfo') and t.tzinfo is not None:
            return t.replace(tzinfo=None)
        return t

    # 2. Трекери для депозитів та зняття
    deposit_tracker = {}
    for idx, row in deposits_df.iterrows():
        dep_id = row.get(COL_ID, idx)
        if pd.isna(dep_id) or str(dep_id) == '':
            dep_id = str(idx)
        else:
            dep_id = str(dep_id)
        dep_date = to_naive(row[COL_DATE])
        dep_amount = float(row[COL_AMOUNT] or 0.0)
        deposit_tracker[idx] = {
            'id': dep_id,
            'date': dep_date,
            'date_str': dep_date.strftime('%Y-%m-%d %H:%M:%S') if hasattr(dep_date, 'strftime') else str(dep_date),
            'year': dep_date.year,
            'month': dep_date.month,
            'day': dep_date.day,
            'initial_amount': dep_amount,
            'remaining_amount': dep_amount,
            'orig_row': row.copy(),
            'splits': []
        }

    withdrawal_tracker = {}
    for idx, row in withdrawals_df.iterrows():
        w_id = row.get(COL_ID, idx)
        if pd.isna(w_id) or str(w_id) == '':
            w_id = str(idx)
        else:
            w_id = str(w_id)
        w_date = to_naive(row[COL_DATE])
        w_amount_abs = abs(float(row[COL_AMOUNT] or 0.0))
        withdrawal_tracker[idx] = {
            'id': w_id,
            'date': w_date,
            'date_str': w_date.strftime('%Y-%m-%d %H:%M:%S') if hasattr(w_date, 'strftime') else str(w_date),
            'year': w_date.year,
            'month': w_date.month,
            'initial_amount_abs': w_amount_abs,
            'remaining_amount_abs': w_amount_abs,
            'orig_row': row.copy(),
            'splits': []
        }

    # Отримуємо всі унікальні хронологічні місяці
    all_months = sorted(list(set(
        [(w['year'], w['month']) for w in withdrawal_tracker.values()] +
        [(d['year'], d['month']) for d in deposit_tracker.values()]
    )))

    # --- ЕТАП 1: Внутрішньомісячна FIFO-компенсація (Локальний пріоритет) ---
    for yr, mn in all_months:
        month_w_indices = [idx for idx, w in withdrawal_tracker.items() if w['year'] == yr and w['month'] == mn]
        month_d_indices = [idx for idx, d in deposit_tracker.items() if d['year'] == yr and d['month'] == mn]

        for w_idx in month_w_indices:
            w_info = withdrawal_tracker[w_idx]
            if w_info['remaining_amount_abs'] <= 0:
                continue

            for d_idx in month_d_indices:
                if w_info['remaining_amount_abs'] <= 0:
                    break

                dep_info = deposit_tracker[d_idx]
                if dep_info['remaining_amount'] > 0:
                    cleared_amount = round(min(w_info['remaining_amount_abs'], dep_info['remaining_amount']), 2)
                    if cleared_amount > 0:
                        dep_info['remaining_amount'] = round(dep_info['remaining_amount'] - cleared_amount, 2)
                        w_info['remaining_amount_abs'] = round(w_info['remaining_amount_abs'] - cleared_amount, 2)

                        w_info['splits'].append({
                            'dep_id': dep_info['id'],
                            'amount': cleared_amount
                        })
                        dep_info['splits'].append({
                            'with_id': w_info['id'],
                            'amount': cleared_amount
                        })

                        ReconciliationRegistry.register(
                            date_left=w_info['orig_row'][COL_DATE],
                            id_left=w_info['id'],
                            desc_left=w_info['orig_row'].get(COL_DESC, ''),
                            amount_left=w_info['orig_row'].get(COL_AMOUNT, 0.0),
                            date_right=dep_info['orig_row'][COL_DATE],
                            id_right=dep_info['id'],
                            desc_right=dep_info['orig_row'].get(COL_DESC, ''),
                            amount_right=dep_info['orig_row'].get(COL_AMOUNT, 0.0),
                            cleared_amount=cleared_amount,
                            remaining_left=w_info['remaining_amount_abs'],
                            clear_type='Cash Clearing (Готівка)',
                            card_left=w_info['orig_row'].get(COL_CARD, ''),
                            card_right=dep_info['orig_row'].get(COL_CARD, '')
                        )

                        logger.info(
                            f"CASH MATCH (Intra-month): Withdrawal {w_info['id']} ({w_info['date_str']}) matched with Deposit {dep_info['id']} ({dep_info['date_str']}) "
                            f"for {cleared_amount:.2f} грн. Remaining w: {w_info['remaining_amount_abs']:.2f} грн."
                        )

    # --- ЕТАП 2: Міжмісячна компенсація з 10-денним буфером (Month M ➔ Month M+1 до 10 числа) ---
    for yr, mn in all_months:
        next_yr = yr + 1 if mn == 12 else yr
        next_mn = 1 if mn == 12 else mn + 1

        rem_w_indices = [idx for idx, w in withdrawal_tracker.items() if w['year'] == yr and w['month'] == mn and w['remaining_amount_abs'] > 0]
        buffer_d_indices = [idx for idx, d in deposit_tracker.items() if d['year'] == next_yr and d['month'] == next_mn and d['day'] <= 10 and d['remaining_amount'] > 0]

        for w_idx in rem_w_indices:
            w_info = withdrawal_tracker[w_idx]
            if w_info['remaining_amount_abs'] <= 0:
                continue

            for d_idx in buffer_d_indices:
                if w_info['remaining_amount_abs'] <= 0:
                    break

                dep_info = deposit_tracker[d_idx]
                if dep_info['remaining_amount'] > 0:
                    cleared_amount = round(min(w_info['remaining_amount_abs'], dep_info['remaining_amount']), 2)
                    if cleared_amount > 0:
                        dep_info['remaining_amount'] = round(dep_info['remaining_amount'] - cleared_amount, 2)
                        w_info['remaining_amount_abs'] = round(w_info['remaining_amount_abs'] - cleared_amount, 2)

                        w_info['splits'].append({
                            'dep_id': dep_info['id'],
                            'amount': cleared_amount
                        })
                        dep_info['splits'].append({
                            'with_id': w_info['id'],
                            'amount': cleared_amount
                        })

                        ReconciliationRegistry.register(
                            date_left=w_info['orig_row'][COL_DATE],
                            id_left=w_info['id'],
                            desc_left=w_info['orig_row'].get(COL_DESC, ''),
                            amount_left=w_info['orig_row'].get(COL_AMOUNT, 0.0),
                            date_right=dep_info['orig_row'][COL_DATE],
                            id_right=dep_info['id'],
                            desc_right=dep_info['orig_row'].get(COL_DESC, ''),
                            amount_right=dep_info['orig_row'].get(COL_AMOUNT, 0.0),
                            cleared_amount=cleared_amount,
                            remaining_left=w_info['remaining_amount_abs'],
                            clear_type='Cash Clearing (Готівка)',
                            card_left=w_info['orig_row'].get(COL_CARD, ''),
                            card_right=dep_info['orig_row'].get(COL_CARD, '')
                        )

                        logger.info(
                            f"CASH MATCH (Cross-month Buffer): Withdrawal {w_info['id']} ({w_info['date_str']}) matched with Deposit {dep_info['id']} ({dep_info['date_str']}) "
                            f"for {cleared_amount:.2f} грн. Remaining w: {w_info['remaining_amount_abs']:.2f} грн."
                        )

    # 3. Генерація нових аналітичних рядків
    new_rows = []

    # а) Зняття готівки (Withdrawals)
    for w_idx, w_info in withdrawal_tracker.items():
        orig_row = w_info['orig_row']
        orig_desc = str(orig_row.get(COL_DESC, '') or '')
        orig_id = w_info['id']
        try:
            orig_amount = float(orig_row.get(COL_AMOUNT, 0.0) or 0.0)
        except (ValueError, TypeError):
            orig_amount = 0.0
        orig_amount_str = f"{orig_amount:.2f}"

        rem = round(w_info['remaining_amount_abs'], 2)
        total_rows = len(w_info['splits']) + (1 if rem > 0 else 0)
        is_split = total_rows > 1

        for split in w_info['splits']:
            row_split = orig_row.copy()
            row_split[COL_AMOUNT] = -round(split['amount'], 2)
            row_split[COL_CAT] = 'переказ на власний рахунок'
            row_split[COL_CLEARING_STATUS] = 'Готівка-Компенсовано'
            if is_split:
                row_split[COL_DESC] = f"[Оригінал: {orig_amount_str}] [Готівка-Компенсовано] {orig_desc}"
            else:
                row_split[COL_DESC] = f"[Готівка-Компенсовано] {orig_desc}"
            row_split[COL_ID] = f"{orig_id}_clear_{split['dep_id']}"
            new_rows.append(row_split)

        if rem > 0:
            row_rem = orig_row.copy()
            row_rem[COL_AMOUNT] = -rem
            row_rem[COL_CAT] = 'зняття готівки'
            row_rem[COL_CLEARING_STATUS] = '-'
            if is_split:
                row_rem[COL_DESC] = f"[Оригінал: {orig_amount_str}] {orig_desc}"
            else:
                row_rem[COL_DESC] = orig_desc
            row_rem[COL_ID] = orig_id
            new_rows.append(row_rem)

    # б) Поповнення готівкою (Deposits)
    for d_idx, dep_info in deposit_tracker.items():
        orig_row = dep_info['orig_row']
        orig_desc = str(orig_row.get(COL_DESC, '') or '')
        orig_id = dep_info['id']
        try:
            orig_amount = float(orig_row.get(COL_AMOUNT, 0.0) or 0.0)
        except (ValueError, TypeError):
            orig_amount = 0.0
        orig_amount_str = f"{orig_amount:.2f}"

        rem = round(dep_info['remaining_amount'], 2)
        total_rows = len(dep_info['splits']) + (1 if rem > 0 else 0)
        is_split = total_rows > 1

        for split in dep_info['splits']:
            row_split = orig_row.copy()
            row_split[COL_AMOUNT] = round(split['amount'], 2)
            row_split[COL_CAT] = 'переказ з власного рахунку'
            row_split[COL_CLEARING_STATUS] = 'Готівка-Компенсовано'
            if is_split:
                row_split[COL_DESC] = f"[Оригінал: {orig_amount_str}] [Готівка-Компенсовано] {orig_desc}"
            else:
                row_split[COL_DESC] = f"[Готівка-Компенсовано] {orig_desc}"
            row_split[COL_ID] = f"{orig_id}_clear_{split['with_id']}"
            new_rows.append(row_split)

        if rem > 0:
            row_rem = orig_row.copy()
            row_rem[COL_AMOUNT] = rem
            row_rem[COL_CAT] = 'поповнення готівкою'
            row_rem[COL_CLEARING_STATUS] = '-'
            if is_split:
                row_rem[COL_DESC] = f"[Оригінал: {orig_amount_str}] {orig_desc}"
            else:
                row_rem[COL_DESC] = orig_desc
            row_rem[COL_ID] = orig_id
            new_rows.append(row_rem)

    # 4. Об'єднання та сортування
    new_rows_df = pd.DataFrame(new_rows)

    if not new_rows_df.empty:
        for col in ['naive_date', 'w_year', 'w_month']:
            if col in new_rows_df.columns:
                new_rows_df = new_rows_df.drop(columns=[col])

    if 'naive_date' in others_df.columns:
        others_df = others_df.drop(columns=['naive_date'])

    final_df = pd.concat([others_df, new_rows_df], ignore_index=True)
    final_df = final_df.sort_values(by=COL_DATE, ascending=False).reset_index(drop=True)

    return final_df

def expand_commission_splits_for_reports(df: pd.DataFrame) -> pd.DataFrame:
    """
    Генерує аналітичний DataFrame для звітів, розщеплюючи транзакції переказів з комісією "на льоту".
    Для кожної пари внутрішнього переказу з комісією (наприклад, витрата -10 050.00 грн, прихід +10 000.00 грн):
    - Оригінальна витратна транзакція (ID '50461728') розщеплюється на два рядки:
        1. Основна сума: -10 000.00 грн, категорія 'переказ на власний рахунок', ID: '50461728_main'
        2. Комісія: -50.00 грн, категорія 'інші витрати', ID: '50461728_comm'
    - Оригінальний прихідний рядок залишається без змін з оригінальним ID.
    """
    if df is None or df.empty:
        return df

    df_out = df.copy()
    own_card_names = set(CARDS_DICTIONARY.values())

    def is_own_card(card_val):
        c_str = str(card_val)
        if c_str in own_card_names:
            return True
        for name in own_card_names:
            if name in c_str or c_str in name:
                return True
        for suffix in CARDS_DICTIONARY.keys():
            if suffix in c_str:
                return True
        return False

    def to_naive(t):
        return t.replace(tzinfo=None) if hasattr(t, 'tzinfo') and t.tzinfo is not None else t

    valid_mask = df_out[COL_AMOUNT].notna() & df_out[COL_DATE].notna()
    valid_df = df_out[valid_mask].copy()
    valid_df['abs_amount'] = valid_df[COL_AMOUNT].abs().round(2)
    valid_df = valid_df[valid_df['abs_amount'] > 0]
    valid_df['naive_date'] = pd.to_datetime(valid_df[COL_DATE]).apply(to_naive)

    COMMISSION_PCT  = 0.01   # 1%
    COMMISSION_FLAT = 100.0  # 100 грн

    pos_all = valid_df[(valid_df[COL_AMOUNT] > 0) & (valid_df[COL_CAT] == 'переказ з власного рахунку')].sort_values('naive_date')
    neg_all = valid_df[(valid_df[COL_AMOUNT] < 0) & (valid_df[COL_CAT] == 'переказ на власний рахунок')].sort_values('naive_date')

    already_matched = set()

    # --- Крок 1: Точні 1-в-1 збіги сум (комісія = 0.00 грн) ---
    # Спочатку знаходимо та виключаємо точні парні перекази без комісії,
    # щоб запобігти помилковому розщепленню чистих переказів (наприклад, -1300 та +1300)
    transfer_subset = valid_df[valid_df[COL_CAT].isin(['переказ на власний рахунок', 'переказ з власного рахунку'])]
    grouped = transfer_subset.groupby('abs_amount')

    for abs_amt, group in grouped:
        if len(group) < 2:
            continue
        pos_g = group[group[COL_AMOUNT] > 0]
        neg_g = group[group[COL_AMOUNT] < 0]
        if pos_g.empty or neg_g.empty:
            continue

        matched_pos_in_group = set()
        for neg_idx, neg_row in neg_g.iterrows():
            if neg_idx in already_matched:
                continue
            neg_time = neg_row['naive_date']
            neg_card = neg_row[COL_CARD]
            best_pos_idx = None
            best_time_diff = pd.Timedelta(days=99999)

            for pos_idx, pos_row in pos_g.iterrows():
                if pos_idx in matched_pos_in_group or pos_idx in already_matched:
                    continue
                if pos_row[COL_CARD] == neg_card:
                    continue
                time_diff = abs(neg_time - pos_row['naive_date'])
                if time_diff <= pd.Timedelta(minutes=5) and time_diff < best_time_diff:
                    best_time_diff = time_diff
                    best_pos_idx = pos_idx

            if best_pos_idx is not None:
                matched_pos_in_group.add(best_pos_idx)
                already_matched.add(neg_idx)
                already_matched.add(best_pos_idx)

    # --- Крок 2: М'який збіг із комісією для РЕШТИ незв'язаних транзакцій ---
    splits_to_apply = []

    for neg_idx, neg_row in neg_all.iterrows():
        if neg_idx in already_matched:
            continue
        abs_neg  = neg_row['abs_amount']
        neg_time = neg_row['naive_date']
        neg_card = neg_row[COL_CARD]

        if not is_own_card(neg_card):
            continue

        max_commission = max(abs_neg * COMMISSION_PCT, COMMISSION_FLAT)
        best_pos_idx = None
        best_time_diff = pd.Timedelta(days=99999)

        for pos_idx, pos_row in pos_all.iterrows():
            if pos_idx in already_matched:
                continue
            pos_card = pos_row[COL_CARD]
            if pos_card == neg_card:
                continue
            if not is_own_card(pos_card):
                continue

            abs_pos = pos_row['abs_amount']
            if not (abs_pos < abs_neg and (abs_neg - abs_pos) <= max_commission):
                continue

            time_diff = abs(neg_time - pos_row['naive_date'])
            if time_diff <= pd.Timedelta(minutes=5) and time_diff < best_time_diff:
                best_time_diff = time_diff
                best_pos_idx = pos_idx

        if best_pos_idx is not None:
            abs_pos = pos_all.loc[best_pos_idx, 'abs_amount']
            commission = round(abs_neg - abs_pos, 2)
            if commission > 0:
                splits_to_apply.append((neg_idx, abs_pos, commission))
            already_matched.add(neg_idx)
            already_matched.add(best_pos_idx)

    if not splits_to_apply:
        return df_out

    new_rows = []
    indices_to_drop = []

    for neg_idx, abs_pos, commission in splits_to_apply:
        orig_row = df_out.loc[neg_idx]
        orig_id = str(orig_row.get(COL_ID, ''))

        # 1. Основна сума
        main_row = orig_row.copy()
        main_row[COL_AMOUNT] = -abs_pos
        main_row[COL_CAT] = 'переказ на власний рахунок'
        main_row[COL_ID] = f"{orig_id}_main"

        # 2. Комісія
        comm_row = orig_row.copy()
        comm_row[COL_AMOUNT] = -commission
        comm_row[COL_CAT] = 'інші витрати'
        comm_row[COL_CLEARING_STATUS] = '-'
        comm_row[COL_ID] = f"{orig_id}_comm"

        new_rows.append(main_row)
        new_rows.append(comm_row)
        indices_to_drop.append(neg_idx)

    df_out = df_out.drop(index=indices_to_drop)
    new_df = pd.DataFrame(new_rows)
    df_out = pd.concat([df_out, new_df], ignore_index=True)
    df_out = df_out.sort_values(by=COL_DATE, ascending=False).reset_index(drop=True)

    return df_out


def process_transit_vika(df: pd.DataFrame) -> pd.DataFrame:
    """
    Маркування прихідних транзакцій від Віки для картки Monobank.
    Змінює категорію позитивних транзакцій з описом 'Від: Sidorska Viktoriia' на 'транзит Віка'.
    """
    if df is None or df.empty:
        return df

    df_out = df.copy()
    if COL_CLEARING_STATUS not in df_out.columns:
        df_out[COL_CLEARING_STATUS] = '-'

    for idx, row in df_out.iterrows():
        amount = float(row.get(COL_AMOUNT, 0.0) or 0.0)
        card_str = str(row.get(COL_CARD, '') or '')
        desc = str(row.get(COL_DESC, '') or '')
        cat = str(row.get(COL_CAT, '') or '')

        # Захист: якщо вже розпізнано як власний переказ, НЕ перезаписуємо
        if cat in ('переказ на власний рахунок', 'переказ з власного рахунку'):
            continue

        # Умови:
        # 1. Позитивна транзакція (Сума > 0)
        # 2. Картка містить у назві 'Monobank' або хвіст '7854'
        # 3. Опис операції містить "Від: Sidorska Viktoriia"
        if amount > 0 and ('monobank' in card_str.lower() or '7854' in card_str):
            if 'sidorska viktoriia' in desc.lower():
                df_out.loc[idx, COL_CAT] = 'транзит Віка'
                df_out.loc[idx, COL_CLEARING_STATUS] = 'Транзит Віка'

    return df_out


def process_mono_investments(df: pd.DataFrame) -> pd.DataFrame:
    """
    Маркування інвестиційних витрат для картки Monobank.
    Змінює категорію від'ємних транзакцій з категорією 'переказ на чужий рахунок' на 'інвестиції'.
    """
    if df is None or df.empty:
        return df

    df_out = df.copy()

    for idx, row in df_out.iterrows():
        amount = float(row.get(COL_AMOUNT, 0.0) or 0.0)
        card_str = str(row.get(COL_CARD, '') or '')
        cat = str(row.get(COL_CAT, '') or '')

        # Захист: якщо вже розпізнано як власний переказ, НЕ перезаписуємо
        if cat in ('переказ на власний рахунок', 'переказ з власного рахунку'):
            continue

        # Умови:
        # 1. Від'ємна транзакція (Сума < 0)
        # 2. Картка належить Monobank (назва містить 'Monobank' або хвіст '7854')
        # 3. Поточна категорія дорівнює 'переказ на чужий рахунок'
        if amount < 0 and ('monobank' in card_str.lower() or '7854' in card_str):
            if cat == 'переказ на чужий рахунок':
                df_out.loc[idx, COL_CAT] = 'інвестиції'

    return df_out


def process_investment_transit_clearing(df: pd.DataFrame) -> pd.DataFrame:
    """
    Динамічний FIFO-кліринг "Investment Transit Clearing" для картки Monobank Sid Чорна (7854).
    Зіставляє прихідний транзит Віки ('транзит Віка') з P2P-витратами інвестицій ('інвестиції').
    """
    if df is None or df.empty:
        return df

    df_out = df.copy()

    # Маска картки Monobank Sid Чорна (7854)
    mono_mask = df_out[COL_CARD].astype(str).str.contains('Monobank Sid Чорна|7854', case=False, regex=True, na=False)

    transit_mask = mono_mask & (df_out[COL_CAT] == 'транзит Віка') & (df_out[COL_AMOUNT] > 0)
    invest_mask = mono_mask & (df_out[COL_CAT] == 'інвестиції') & (df_out[COL_AMOUNT] < 0)

    if not transit_mask.any() or not invest_mask.any():
        return df_out

    others_df = df_out[~(transit_mask | invest_mask)].copy()

    df_transit = df_out[transit_mask].copy()
    df_invest = df_out[invest_mask].copy()

    df_transit['naive_date'] = pd.to_datetime(df_transit[COL_DATE])
    df_invest['naive_date'] = pd.to_datetime(df_invest[COL_DATE])

    # Сортування від найстаріших до найновіших (для FIFO)
    df_transit = df_transit.sort_values(by='naive_date', ascending=True)
    df_invest = df_invest.sort_values(by='naive_date', ascending=True)

    deposit_tracker = {}
    for d_idx, row in df_transit.iterrows():
        amount = float(row[COL_AMOUNT])
        deposit_tracker[d_idx] = {
            'id': str(row[COL_ID]),
            'date': row[COL_DATE],
            'amount': amount,
            'remaining_amount': amount,
            'splits': [],
            'orig_row': row
        }

    expense_tracker = {}
    for e_idx, row in df_invest.iterrows():
        amount_abs = abs(float(row[COL_AMOUNT]))
        expense_tracker[e_idx] = {
            'id': str(row[COL_ID]),
            'date': row[COL_DATE],
            'amount_abs': amount_abs,
            'remaining_amount_abs': amount_abs,
            'splits': [],
            'orig_row': row
        }

    # FIFO зіставляння: для кожної прихідної транзакції Віки компенсуємо витрати інвестицій хронологічно
    for d_idx, d_info in deposit_tracker.items():
        if d_info['remaining_amount'] <= 0:
            continue

        for e_idx, e_info in expense_tracker.items():
            if d_info['remaining_amount'] <= 0:
                break

            if e_info['remaining_amount_abs'] > 0:
                cleared_amount = round(min(d_info['remaining_amount'], e_info['remaining_amount_abs']), 2)
                if cleared_amount > 0:
                    d_info['remaining_amount'] = round(d_info['remaining_amount'] - cleared_amount, 2)
                    e_info['remaining_amount_abs'] = round(e_info['remaining_amount_abs'] - cleared_amount, 2)

                    e_info['splits'].append({
                        'dep_id': d_info['id'],
                        'amount': cleared_amount
                    })
                    d_info['splits'].append({
                        'exp_id': e_info['id'],
                        'amount': cleared_amount
                    })

                    ReconciliationRegistry.register(
                        date_left=e_info['orig_row'][COL_DATE],
                        id_left=e_info['id'],
                        desc_left=e_info['orig_row'].get(COL_DESC, ''),
                        amount_left=e_info['orig_row'].get(COL_AMOUNT, 0.0),
                        date_right=d_info['orig_row'][COL_DATE],
                        id_right=d_info['id'],
                        desc_right=d_info['orig_row'].get(COL_DESC, ''),
                        amount_right=d_info['orig_row'].get(COL_AMOUNT, 0.0),
                        cleared_amount=cleared_amount,
                        remaining_left=e_info['remaining_amount_abs'],
                        clear_type='Investment Transit (Віка)',
                        card_left=e_info['orig_row'].get(COL_CARD, ''),
                        card_right=d_info['orig_row'].get(COL_CARD, '')
                    )

                    logger.info(
                        f"INVESTMENT TRANSIT MATCH: Transit {d_info['id']} matched with Expense {e_info['id']} "
                        f"for {cleared_amount:.2f} грн. Remaining transit: {d_info['remaining_amount']:.2f} грн."
                    )

    # 3. Формуємо нові аналітичні рядки
    new_rows = []

    # а) Витрати інвестицій
    for e_idx, e_info in expense_tracker.items():
        orig_row = e_info['orig_row']
        orig_desc = str(orig_row.get(COL_DESC, '') or '')
        orig_id = e_info['id']
        try:
            orig_amount = float(orig_row.get(COL_AMOUNT, 0.0) or 0.0)
        except (ValueError, TypeError):
            orig_amount = 0.0
        orig_amount_str = f"{orig_amount:.2f}"

        rem = round(e_info['remaining_amount_abs'], 2)
        total_rows = len(e_info['splits']) + (1 if rem > 0 else 0)
        is_split = total_rows > 1

        for split in e_info['splits']:
            row_split = orig_row.copy()
            row_split[COL_AMOUNT] = -round(split['amount'], 2)
            row_split[COL_CAT] = 'інвестиції (транзит Віка)'
            row_split[COL_CLEARING_STATUS] = 'Транзит Віка'
            if is_split:
                row_split[COL_DESC] = f"[Оригінал: {orig_amount_str}] [Транзит Віка - Компенсовано] {orig_desc}"
            else:
                row_split[COL_DESC] = f"[Транзит Віка - Компенсовано] {orig_desc}"
            row_split[COL_ID] = f"{split['dep_id']}_clear_{orig_id}"
            new_rows.append(row_split)

        if rem > 0:
            row_rem = orig_row.copy()
            row_rem[COL_AMOUNT] = -rem
            row_rem[COL_CAT] = 'інвестиції'
            row_rem[COL_CLEARING_STATUS] = '-'
            if is_split:
                row_rem[COL_DESC] = f"[Оригінал: {orig_amount_str}] {orig_desc}"
            else:
                row_rem[COL_DESC] = orig_desc
            row_rem[COL_ID] = orig_id
            new_rows.append(row_rem)

    # б) Депозити транзиту Віки
    for d_idx, d_info in deposit_tracker.items():
        orig_row = d_info['orig_row']
        orig_desc = str(orig_row.get(COL_DESC, '') or '')
        orig_id = d_info['id']
        try:
            orig_amount = float(orig_row.get(COL_AMOUNT, 0.0) or 0.0)
        except (ValueError, TypeError):
            orig_amount = 0.0
        orig_amount_str = f"{orig_amount:.2f}"

        rem = round(d_info['remaining_amount'], 2)
        total_rows = len(d_info['splits']) + (1 if rem > 0 else 0)
        is_split = total_rows > 1

        for split in d_info['splits']:
            row_split = orig_row.copy()
            row_split[COL_AMOUNT] = round(split['amount'], 2)
            row_split[COL_CAT] = 'транзит Віка'
            row_split[COL_CLEARING_STATUS] = 'Транзит Віка'
            if is_split:
                row_split[COL_DESC] = f"[Оригінал: {orig_amount_str}] [Транзит Віка - Компенсовано] {orig_desc}"
            else:
                row_split[COL_DESC] = f"[Транзит Віка - Компенсовано] {orig_desc}"
            row_split[COL_ID] = f"{orig_id}_clear_{split['exp_id']}"
            new_rows.append(row_split)

        if rem > 0:
            row_rem = orig_row.copy()
            row_rem[COL_AMOUNT] = rem
            row_rem[COL_CAT] = 'транзит Віка'
            row_rem[COL_CLEARING_STATUS] = 'Транзит Віка'
            if is_split:
                row_rem[COL_DESC] = f"[Оригінал: {orig_amount_str}] {orig_desc}"
            else:
                row_rem[COL_DESC] = orig_desc
            row_rem[COL_ID] = orig_id
            new_rows.append(row_rem)

    # 4. Об'єднання та сортування
    new_rows_df = pd.DataFrame(new_rows)

    if not new_rows_df.empty and 'naive_date' in new_rows_df.columns:
        new_rows_df = new_rows_df.drop(columns=['naive_date'])

    if 'naive_date' in others_df.columns:
        others_df = others_df.drop(columns=['naive_date'])

    final_df = pd.concat([others_df, new_rows_df], ignore_index=True)
    final_df = final_df.sort_values(by=COL_DATE, ascending=False).reset_index(drop=True)

    return final_df

