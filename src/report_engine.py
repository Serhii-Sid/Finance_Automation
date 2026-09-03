import os
import logging
from typing import Optional
import pandas as pd
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from config import (
    OUTPUT_FOLDER, OUTPUT_FILE, COL_DATE, COL_AMOUNT, COL_BALANCE, COL_ID, COL_CAT, COL_CARD, COL_DESC,
    COL_CLEARING_STATUS, COL_MCC
)
import datetime
from src.finance_logic import (
    expand_commission_splits_for_reports,
    detect_internal_transfers,
    process_cash_clearing,
    process_transit_vika,
    process_mono_investments,
    process_investment_transit_clearing,
    ReconciliationRegistry
)

logger = logging.getLogger(__name__)

def generate_daily_dashboard(df_ledger: pd.DataFrame) -> pd.DataFrame:
    """Генерує щоденний дашборд із групованими деталями оброблених транзакцій під кожним днем."""
    if df_ledger is None or df_ledger.empty:
        return pd.DataFrame(columns=[
            'Місяць', 'Дата', 'План', 'Витрати', 'Дохід', 
            'Різниця за день', 'Різниця за місяць', 'Різниця загалом'
        ])
    
    df = expand_commission_splits_for_reports(df_ledger)
    df[COL_DATE] = pd.to_datetime(df[COL_DATE])
    if df[COL_DATE].dt.tz is not None:
        df[COL_DATE] = df[COL_DATE].dt.tz_localize(None)
        
    df['Дата_Норм'] = df[COL_DATE].dt.normalize()
    min_date = df['Дата_Норм'].min()
    max_date = df['Дата_Норм'].max()
    
    all_dates = pd.date_range(start=min_date, end=max_date, freq='D')
    
    # Маски для фільтрації оброблених витрат та доходів (ті ж самі, що формують Income та Expenses)
    expenses_mask = (df[COL_AMOUNT] < 0) & (~df[COL_CAT].isin(['переказ на власний рахунок', 'зняття готівки', 'транзит Віка', 'інвестиції (транзит Віка)']))
    income_mask = (df[COL_AMOUNT] > 0) & (~df[COL_CAT].isin(['переказ з власного рахунку', 'поповнення готівкою', 'транзит Віка']))
    
    df_exp_grouped = df[expenses_mask].groupby('Дата_Норм')[COL_AMOUNT].sum()
    df_inc_grouped = df[income_mask].groupby('Дата_Норм')[COL_AMOUNT].sum()
    
    df_expenses_details = df[expenses_mask].copy()
    df_income_details = df[income_mask].copy()
    
    month_income_totals = {}
    for (yr, mn), group in df[income_mask].groupby([df[COL_DATE].dt.year, df[COL_DATE].dt.month]):
        month_income_totals[(yr, mn)] = group[COL_AMOUNT].sum()
        
    now = pd.Timestamp.now()
    plan_cache = {}
    
    ukr_months_nominative = {
        1: 'Січень', 2: 'Лютий', 3: 'Березень', 4: 'Квітень', 5: 'Травень', 6: 'Червень',
        7: 'Липень', 8: 'Серпень', 9: 'Вересень', 10: 'Жовтень', 11: 'Листопад', 12: 'Грудень'
    }
    
    daily_summary_rows = []
    for dt in all_dates:
        yr, mn = dt.year, dt.month
        days_in_month = pd.Period(year=yr, month=mn, freq='M').days_in_month
        
        daily_income = df_inc_grouped.get(dt, 0.0)
        
        if (yr, mn) not in plan_cache:
            is_closed = (yr < now.year) or (yr == now.year and mn < now.month)
            if is_closed:
                tot_inc = month_income_totals.get((yr, mn), 0.0)
                plan_cache[(yr, mn)] = tot_inc / days_in_month
            else:
                plan_cache[(yr, mn)] = 40000.0 / days_in_month
                
        plan = plan_cache[(yr, mn)]
        daily_expense = df_exp_grouped.get(dt, 0.0)
        
        daily_summary_rows.append({
            'dt_norm': dt,
            'temp_year': yr,
            'temp_month': mn,
            'Місяць': f"{ukr_months_nominative[mn]} {yr}",
            'Дата_Obj': dt,
            'План': plan,
            'Витрати': daily_expense,
            'Дохід': daily_income
        })
        
    df_dash_summary = pd.DataFrame(daily_summary_rows)
    df_dash_summary['Різниця за день'] = df_dash_summary['План'] + df_dash_summary['Витрати']
    df_dash_summary['Різниця за місяць'] = df_dash_summary.groupby(['temp_year', 'temp_month'])['Різниця за день'].cumsum()
    
    INITIAL_TOTAL_BALANCE = -48807.41
    df_dash_summary['Різниця загалом'] = INITIAL_TOTAL_BALANCE + df_dash_summary['Різниця за день'].cumsum()
    
    grouped_months = df_dash_summary.groupby(['temp_year', 'temp_month'], sort=False)
    
    final_rows = []
    for (yr, mn), group in grouped_months:
        for idx, row in group.iterrows():
            dt = row['dt_norm']
            
            # 1. Щоденний підсумковий рядок (Level 0)
            summary_dict = {
                'Місяць': row['Місяць'],
                'Дата': dt.strftime('%d.%m.%Y'),
                'План': row['План'],
                'Витрати': row['Витрати'],
                'Дохід': row['Дохід'],
                'Різниця за день': row['Різниця за день'],
                'Різниця за місяць': row['Різниця за місяць'],
                'Різниця загалом': row['Різниця загалом']
            }
            final_rows.append(summary_dict)
            
            # 2. Детальні рядки дня зі ВСІХ оброблених транзакцій (включаючи технічні та компенсовані)
            day_details = df[(df['Дата_Норм'] == dt) & (df[COL_AMOUNT] != 0)]
            
            if not day_details.empty:
                day_details_sorted = day_details.sort_values(COL_DATE)
                for _, d_row in day_details_sorted.iterrows():
                    amt = float(d_row.get(COL_AMOUNT, 0.0) or 0.0)
                    card = str(d_row.get(COL_CARD, '') or '').strip()
                    cat = str(d_row.get(COL_CAT, '') or '').strip()
                    desc = str(d_row.get(COL_DESC, '') or '').strip()
                    
                    is_comp_cat = cat in ['переказ на власний рахунок', 'переказ з власного рахунку', 'зняття готівки', 'поповнення готівкою', 'транзит Віка', 'інвестиції (транзит Віка)']
                    prefix = "   ↳ ⚙️ [Компенсовано] " if is_comp_cat else "   ↳ "
                    
                    detail_dict = {
                        'Місяць': f"{prefix}[{card}] {cat}: {desc}",
                        'Дата': '',
                        'План': None,
                        'Витрати': amt if amt < 0 else None,
                        'Дохід': amt if amt > 0 else None,
                        'Різниця за день': None,
                        'Різниця за місяць': None,
                        'Різниця загалом': None
                    }
                    final_rows.append(detail_dict)
            
        # 3. Підсумковий рядок місяця РАЗОМ за [Місяць] (виключає детальні рядки, запобігаючи подвійному підрахунку)
        sum_plan = group['План'].sum()
        sum_expenses = group['Витрати'].sum()
        sum_income = group['Дохід'].sum()
        
        last_day_row = group.iloc[-1]
        final_diff_month = last_day_row['Різниця за місяць']
        final_diff_total = last_day_row['Різниця загалом']
        
        month_name = ukr_months_nominative[mn]
        rahom_row = {
            'Місяць': f"{month_name} {yr}",
            'Дата': f'РАЗОМ за {month_name} {yr}',
            'План': sum_plan,
            'Витрати': sum_expenses,
            'Дохід': sum_income,
            'Різниця за день': None,
            'Різниця за місяць': final_diff_month,
            'Різниця загалом': final_diff_total
        }
        final_rows.append(rahom_row)
        
    df_dash_final = pd.DataFrame(final_rows)
    col_order = ['Місяць', 'Дата', 'План', 'Витрати', 'Дохід', 'Різниця за день', 'Різниця за місяць', 'Різниця загалом']
    df_dash_final = df_dash_final[col_order]
    
    return df_dash_final

def rotate_outputs():
    """Керування версіями файлу Ledger."""
    base_name = "Total_Ledger_v{}.xlsx"
    for i in [2, 1]:
        old_v = os.path.join(OUTPUT_FOLDER, base_name.format(i))
        new_v = os.path.join(OUTPUT_FOLDER, base_name.format(i+1))
        if os.path.exists(old_v): os.replace(old_v, new_v)
    if os.path.exists(OUTPUT_FILE): 
        os.replace(OUTPUT_FILE, os.path.join(OUTPUT_FOLDER, base_name.format(1)))

def save_final_ledger(df: pd.DataFrame, df_dash: Optional[pd.DataFrame] = None, script_path: str = "", df_analytical: Optional[pd.DataFrame] = None):
    """Зберігає фінальний Excel з 5 листами (Total_Ledger, Income, Reconciliation_Audit, Expenses, Daily_Dashboard)."""
    try:
        rotate_outputs()

        from src.finance_logic import detect_internal_transfers, process_cash_clearing, ReconciliationRegistry

        # 1. Сирий недоторканий DataFrame для листа 'Total_Ledger'
        df_export = df.copy()
        df_export = df_export.drop(columns=[COL_CLEARING_STATUS], errors='ignore')
        df_export.insert(0, '№ п/п', range(1, len(df_export) + 1))
        
        ukr_months = {
            1: 'Січень', 2: 'Лютий', 3: 'Березень', 4: 'Квітень', 5: 'Травень', 6: 'Червень',
            7: 'Липень', 8: 'Серпень', 9: 'Вересень', 10: 'Жовтень', 11: 'Листопад', 12: 'Грудень'
        }
        df_export.insert(2, 'Місяць', df_export[COL_DATE].dt.month.map(ukr_months) + " " + df_export[COL_DATE].dt.year.astype(str))
        
        # 2. Формування df_analytical та збір аудиторського реєстру ReconciliationRegistry
        if df_analytical is None:
            df_analytical = detect_internal_transfers(df.copy())
            df_analytical = process_transit_vika(df_analytical)
            df_analytical = process_mono_investments(df_analytical)
            df_analytical = process_investment_transit_clearing(df_analytical)
            df_analytical = process_cash_clearing(df_analytical)

        # 3. Дашборд
        if df_dash is None or df_dash.empty:
            df_dash = generate_daily_dashboard(df_analytical)

        # 4. Підготовка експорту для вкладок Income та Expenses
        df_analytical_processed = expand_commission_splits_for_reports(df_analytical)
        df_analytical_export = df_analytical_processed.copy()
        df_analytical_export.insert(0, '№ п/п', range(1, len(df_analytical_export) + 1))
        df_analytical_export.insert(2, 'Місяць', df_analytical_export[COL_DATE].dt.month.map(ukr_months) + " " + df_analytical_export[COL_DATE].dt.year.astype(str))

        df_income = df_analytical_export[df_analytical_export[COL_AMOUNT] > 0].copy()
        df_expenses = df_analytical_export[df_analytical_export[COL_AMOUNT] < 0].copy()
        
        cols_to_drop_analysis = ['№ п/п', 'Місяць']
        df_income = df_income.drop(columns=cols_to_drop_analysis, errors='ignore')
        df_expenses = df_expenses.drop(columns=cols_to_drop_analysis, errors='ignore')

        desired_order = [COL_ID, COL_DATE, COL_CLEARING_STATUS, COL_CAT, COL_CARD, COL_DESC, COL_AMOUNT, COL_BALANCE, COL_MCC]
        income_cols = [c for c in desired_order if c in df_income.columns] + [c for c in df_income.columns if c not in desired_order]
        expenses_cols = [c for c in desired_order if c in df_expenses.columns] + [c for c in df_expenses.columns if c not in desired_order]
        df_income = df_income[income_cols]
        df_expenses = df_expenses[expenses_cols]

        # Заготовка порожньої структури для Reconciliation_Audit
        df_audit_header = pd.DataFrame(columns=[
            'Дата', 'Операція / ID', 'Картка / Опис',
            'Оригінальна сума', 'Скомпенсовано', 'Залишок (Витрати)', 'Деталі звірки'
        ])

        # Запис п'яти листів у суворо визначеному порядку:
        # 1. Total_Ledger, 2. Income, 3. Expenses, 4. Reconciliation_Audit, 5. Daily_Dashboard
        with pd.ExcelWriter(OUTPUT_FILE, engine='openpyxl', datetime_format='dd.mm.yyyy hh:mm:ss') as writer:
            df_export.to_excel(writer, index=False, sheet_name='Total_Ledger')
            df_income.to_excel(writer, index=False, sheet_name='Income')
            df_expenses.to_excel(writer, index=False, sheet_name='Expenses')
            df_audit_header.to_excel(writer, index=False, sheet_name='Reconciliation_Audit')
            df_dash.to_excel(writer, index=False, sheet_name='Daily_Dashboard')

            # Стилізація листів
            for sheet_name in ['Total_Ledger', 'Income', 'Expenses', 'Reconciliation_Audit', 'Daily_Dashboard']:
                sheet = writer.sheets[sheet_name]
                sheet.views.sheetView[0].showGridLines = True
                
                if sheet_name in ('Total_Ledger', 'Income', 'Expenses'):
                    # Стандартна стилізація для основних таблиць
                    sheet.row_dimensions[1].height = 30
                    header_fill = PatternFill(start_color="5A5A5A", end_color="5A5A5A", fill_type="solid")
                    header_font = Font(bold=True, color="FFFFFF", size=12)
                    header_alignment = Alignment(horizontal="center", vertical="center")
                    thin_side = Side(style='thin', color="000000")
                    header_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

                    for cell in sheet[1]:
                        if cell.value is not None:
                            cell.font = header_font
                            cell.fill = header_fill
                            cell.alignment = header_alignment
                            cell.border = header_border

                    # Сітка та Зебра
                    thin_grid_side = Side(style='thin', color="A6A6A6")
                    thick_border_side = Side(style='medium', color="000000")
                    zebra_fill = PatternFill(start_color="E9E9E9", end_color="E9E9E9", fill_type="solid")
                    data_alignment = Alignment(vertical="center")

                    prev_period = None
                    group_start = 2
                    for row_idx in range(2, sheet.max_row + 1):
                        curr_period = None
                        is_new_period = False
                        if sheet_name == 'Total_Ledger':
                            curr_period = sheet.cell(row=row_idx, column=3).value
                            is_new_period = prev_period is not None and curr_period != prev_period
                        is_even = row_idx % 2 == 0

                        if is_new_period and sheet_name == 'Total_Ledger':
                            if row_idx - 1 > group_start:
                                sheet.row_dimensions.group(group_start + 1, row_idx - 1, outline_level=1)
                            group_start = row_idx

                        for col_idx in range(1, sheet.max_column + 1):
                            cell = sheet.cell(row=row_idx, column=col_idx)
                            top_s = thick_border_side if (sheet_name == 'Total_Ledger' and is_new_period) else thin_grid_side
                            cell.border = Border(left=thin_grid_side, right=thin_grid_side, top=top_s, bottom=thin_grid_side)
                            
                            header_val = sheet.cell(row=1, column=col_idx).value
                            if header_val == 'Дата':
                                cell.alignment = Alignment(horizontal="center", vertical="center")
                            else:
                                cell.alignment = data_alignment
                            
                            if is_even:
                                cell.fill = zebra_fill
                        prev_period = curr_period

                    if sheet_name == 'Total_Ledger' and sheet.max_row > group_start:
                        sheet.row_dimensions.group(group_start + 1, sheet.max_row, outline_level=1)
                        sheet.sheet_properties.outlinePr.summaryBelow = False

                    sheet.freeze_panes = "A2"
                    sheet.auto_filter.ref = sheet.dimensions

                elif sheet_name == 'Reconciliation_Audit':
                    # --- Карта компенсацій (Reconciliation Dashboard) ---
                    sheet.row_dimensions[1].height = 24
                    sheet.row_dimensions[2].height = 24

                    header_fill_audit = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
                    header_font_audit = Font(bold=True, color="FFFFFF", size=11)
                    header_alignment = Alignment(horizontal="center", vertical="center")
                    thin_grid_side = Side(style='thin', color="A6A6A6")
                    thick_grid_side = Side(style='medium', color="000000")
                    header_border = Border(left=thin_grid_side, right=thin_grid_side, top=thin_grid_side, bottom=thin_grid_side)

                    # Заголовки першого рівня (Групування)
                    sheet.merge_cells('A1:A2')
                    sheet.cell(row=1, column=1, value="Тип клірингу")

                    sheet.merge_cells('B1:E1')
                    sheet.cell(row=1, column=2, value="ДЖЕРЕЛО (ОРИГІНАЛЬНА ОПЕРАЦІЯ)")

                    sheet.merge_cells('F1:I1')
                    sheet.cell(row=1, column=6, value="КОМПЕНСАЦІЯ (ЗІСТАВЛЕНА ОПЕРАЦІЯ)")

                    sheet.merge_cells('J1:J2')
                    sheet.cell(row=1, column=10, value="Різниця (Комісія)")

                    # Заголовки другого рівня
                    headers_r2 = {
                        2: "Дата", 3: "Картка", 4: "Опис", 5: "Сума",
                        6: "Дата", 7: "Картка", 8: "Опис", 9: "Сума"
                    }
                    for c_idx, text in headers_r2.items():
                        sheet.cell(row=2, column=c_idx, value=text)

                    # Стилізація заголовків (Row 1 & Row 2)
                    for r_idx in (1, 2):
                        for c_idx in range(1, 11):
                            cell = sheet.cell(row=r_idx, column=c_idx)
                            cell.font = header_font_audit
                            cell.fill = header_fill_audit
                            cell.alignment = header_alignment
                            cell.border = header_border

                    # Отримуємо реєстр збережених компенсацій
                    df_audit_data = ReconciliationRegistry.get_df()

                    align_center = Alignment(horizontal="center", vertical="center")
                    align_left = Alignment(horizontal="left", vertical="center")
                    align_right = Alignment(horizontal="right", vertical="center")

                    zebra_fill = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")
                    no_fill = PatternFill(fill_type=None)

                    current_row = 3
                    if not df_audit_data.empty:
                        for pair_idx, row in df_audit_data.iterrows():
                            clear_type_raw = str(row.get('Тип компенсації', '') or '')
                            if 'Cash' in clear_type_raw or 'Готівка' in clear_type_raw:
                                clear_type = 'Готівка'
                            elif 'Transit' in clear_type_raw or 'Віка' in clear_type_raw:
                                clear_type = 'Транзит Віка'
                            elif 'Twins' in clear_type_raw or 'Картка' in clear_type_raw:
                                clear_type = 'Внутрішній переказ'
                            else:
                                clear_type = clear_type_raw

                            date_src = row.get('Дата зняття')
                            card_src = str(row.get('Картка джерела', '') or row.get('Опис зняття', '')).strip()
                            desc_src = str(row.get('Опис зняття', '') or '')
                            amt_src = abs(float(row.get('Сума зняття', 0.0) or 0.0))

                            date_dst = row.get('Дата поповнення')
                            card_dst = str(row.get('Картка отримувача', '') or row.get('Опис поповнення', '')).strip()
                            desc_dst = str(row.get('Опис поповнення', '') or '')
                            cleared_amt = float(row.get('Сума компенсації', 0.0) or 0.0)

                            # Для транзиту Віки джерелом є прихід від Віки (date_right), а компенсацією є інвестиція (date_left)
                            if clear_type == 'Транзит Віка':
                                date_src, date_dst = date_dst, date_src
                                card_src, card_dst = card_dst, card_src
                                desc_src, desc_dst = desc_dst, desc_src
                                amt_src = float(row.get('Сума поповнення', 0.0) or 0.0)

                            delta = round(amt_src - cleared_amt, 2)
                            if abs(delta) < 1e-5:
                                delta = 0.00

                            vals = [
                                clear_type,
                                date_src,
                                card_src,
                                desc_src,
                                amt_src,
                                date_dst,
                                card_dst,
                                desc_dst,
                                cleared_amt,
                                delta
                            ]

                            is_even = (pair_idx % 2 == 0)
                            row_fill = zebra_fill if is_even else no_fill

                            sheet.row_dimensions[current_row].height = 22
                            for c_idx, val in enumerate(vals, 1):
                                cell = sheet.cell(row=current_row, column=c_idx, value=val)
                                cell.fill = row_fill

                                l_side = thick_grid_side if c_idx in (1, 2, 6, 10) else thin_grid_side
                                r_side = thick_grid_side if c_idx in (1, 5, 9, 10) else thin_grid_side
                                cell.border = Border(left=l_side, right=r_side, top=thin_grid_side, bottom=thin_grid_side)

                                if c_idx in (1, 2, 6):
                                    cell.alignment = align_center
                                    if c_idx in (2, 6) and isinstance(val, (datetime.datetime, pd.Timestamp)):
                                        cell.number_format = 'DD.MM.YYYY HH:mm:ss'
                                elif c_idx in (5, 9, 10):
                                    cell.alignment = align_right
                                    cell.number_format = '#,##0.00 "грн."'
                                else:
                                    cell.alignment = align_left

                            current_row += 1

                    sheet.freeze_panes = "A3"
                    if sheet.max_row >= 2 and sheet.max_column >= 1:
                        sheet.auto_filter.ref = f"A2:J{sheet.max_row}"

                else:
                    # Стилізація Daily_Dashboard
                    sheet.row_dimensions[1].height = 25
                    header_fill = PatternFill(start_color="D3D3D3", end_color="D3D3D3", fill_type="solid")

                    font_header = Font(bold=True, size=14, color="000000")
                    align_center = Alignment(horizontal="center", vertical="center")
                    align_left = Alignment(horizontal="left", vertical="center")
                    align_right = Alignment(horizontal="right", vertical="center")
                    thick_side = Side(style='thick', color="000000")
                    thin_side = Side(style='thin', color="A6A6A6")
                    light_grid_side = Side(style='thin', color="D9D9D9")

                    zebra_fill = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")
                    no_fill = PatternFill(fill_type=None)
                    rahom_fill = PatternFill(start_color="F9E79F", end_color="F9E79F", fill_type="solid")
                    
                    # Кнопка відкриття підсумовуючих деталей відображається НАД деталями (на щоденному підсумковому рядку)
                    sheet.sheet_properties.outlinePr.summaryBelow = False

                    daily_summary_count = 0
                    for row_idx in range(1, sheet.max_row + 1):
                        is_header = (row_idx == 1)
                        val1 = str(sheet.cell(row=row_idx, column=1).value or '')
                        val2 = str(sheet.cell(row=row_idx, column=2).value or '')
                        curr_val = val1 if '↳' in val1 else val2
                        is_rahom = val2.startswith('РАЗОМ') or val1.startswith('РАЗОМ')
                        is_detail = '↳' in val1 or '↳' in val2

                        if is_header or is_rahom:
                            sheet.row_dimensions[row_idx].outline_level = 0
                        elif is_detail:
                            sheet.row_dimensions[row_idx].outline_level = 1
                            sheet.row_dimensions[row_idx].hidden = True
                            # Об'єднуємо комірки A та B (стовпчики "Місяць" та "Дата") для детального рядка
                            sheet.merge_cells(start_row=row_idx, start_column=1, end_row=row_idx, end_column=2)
                        else:
                            sheet.row_dimensions[row_idx].outline_level = 0
                            daily_summary_count += 1

                        is_even = (daily_summary_count % 2 == 0) if not is_detail else False

                        for col_idx in range(1, 9):
                            cell = sheet.cell(row=row_idx, column=col_idx)
                            
                            if is_header:
                                cell.font = font_header
                                cell.alignment = align_center
                                cell.fill = header_fill
                                cell.border = Border(left=thick_side if col_idx == 1 else thin_side,
                                                     right=thick_side if col_idx == 8 else thin_side,
                                                     top=thick_side, bottom=thick_side)
                            elif is_detail:
                                is_comp = '⚙️' in curr_val or '[Компенсовано]' in curr_val or any(c in curr_val for c in [
                                    'переказ на власний рахунок', 'переказ з власного рахунку', 
                                    'зняття готівки', 'поповнення готівкою', 
                                    'транзит Віка', 'інвестиції (транзит Віка)'
                                ])
                                if is_comp:
                                    cell.font = Font(name="Calibri", size=9, italic=True, color="A0A0A0")
                                else:
                                    cell.font = Font(name="Calibri", size=10, italic=False, color="000000")
                                cell.fill = no_fill
                                cell.border = Border(left=thick_side if col_idx == 1 else light_grid_side,
                                                     right=thick_side if col_idx == 8 else light_grid_side,
                                                     top=light_grid_side, bottom=light_grid_side)
                                if col_idx in (1, 2):
                                    cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
                                else:
                                    cell.alignment = align_right
                            else:
                                l_b = thick_side if col_idx in (1, 2, 6, 7, 8) else thin_side
                                r_b = thick_side if col_idx in (2, 6, 7, 8) else thin_side
                                t_b = thick_side if (is_rahom or row_idx == sheet.max_row) else thin_side
                                b_b = thick_side if (is_rahom or row_idx == sheet.max_row) else thin_side

                                cell.border = Border(left=l_b, right=r_b, top=t_b, bottom=b_b)
                                
                                if is_rahom:
                                    cell.fill = rahom_fill
                                    cell.font = Font(bold=True, italic=True, size=10, color="000000") if col_idx == 6 else Font(bold=True, size=11, color="000000")
                                else:
                                    cell.fill = zebra_fill if is_even else no_fill
                                    cell.font = Font(size=11, color="000000")

                                if col_idx in (1, 2):
                                    cell.alignment = align_left if is_rahom else align_center
                                else:
                                    cell.alignment = align_right

                    # Групуємо детальні рядки кожного дня
                    curr_start = None
                    for row_idx in range(2, sheet.max_row + 1):
                        val1 = str(sheet.cell(row=row_idx, column=1).value or '')
                        val2 = str(sheet.cell(row=row_idx, column=2).value or '')
                        is_det = '↳' in val1 or '↳' in val2
                        if is_det:
                            if curr_start is None:
                                curr_start = row_idx
                        else:
                            if curr_start is not None:
                                sheet.row_dimensions.group(curr_start, row_idx - 1, outline_level=1, hidden=True)
                                curr_start = None
                    if curr_start is not None:
                        sheet.row_dimensions.group(curr_start, sheet.max_row, outline_level=1, hidden=True)

                    sheet.freeze_panes = "A2"
                    sheet.auto_filter.ref = sheet.dimensions

                # --- Налаштування ширини та форматів клітинок (для всіх вкладок) ---
                # 1. Знаходимо стовпчик «Категорія» та вираховуємо max_category_width як ліміт для даного листа
                category_col = None
                for col in sheet.columns:
                    header_val_str = str(col[0].value or '').strip()
                    if header_val_str in ('Категорія', COL_CAT):
                        category_col = col
                        break

                def _get_val_str(val, header_val, col_idx):
                    if val is None or pd.isna(val):
                        return ""
                    if isinstance(val, (int, float)):
                        import math
                        if math.isnan(val):
                            return ""
                        is_fin = (
                            header_val in (
                                'Сума', COL_AMOUNT, 'Залишок', COL_BALANCE, 'План', 'Витрати', 
                                'Дохід', 'Різниця за день', 'Різниця за місяць', 'Різниця загалом',
                                'Оригінальна сума', 'Скомпенсовано', 'Залишок (Витрати)', 'Різниця (Комісія)'
                            ) or (sheet_name == 'Reconciliation_Audit' and col_idx in (5, 9, 10))
                        )
                        try:
                            return f"{val:,.2f}" if is_fin else (f"{int(val)}" if val == int(val) else str(val))
                        except Exception:
                            return str(val)
                    elif isinstance(val, (datetime.datetime, pd.Timestamp)):
                        return val.strftime('%d.%m.%Y %H:%M:%S')
                    elif isinstance(val, datetime.date):
                        return val.strftime('%d.%m.%Y')
                    else:
                        return str(val)

                if category_col is not None:
                    cat_max_len = 0
                    cat_header_val = str(category_col[0].value or '').strip()
                    for cell in category_col:
                        val_s = _get_val_str(cell.value, cat_header_val, category_col[0].column)
                        if len(val_s) > cat_max_len:
                            cat_max_len = len(val_s)
                    max_category_width = max(cat_max_len + 4, 12)
                else:
                    max_category_width = 35

                for col in sheet.columns:
                    col_letter = get_column_letter(col[0].column)
                    header_cell = col[0]
                    header_val = header_cell.value
                    col_idx = col[0].column
                    
                    max_len = 0
                    for cell in col:
                        val_s = _get_val_str(cell.value, header_val, col_idx)
                        if len(val_s) > max_len:
                            max_len = len(val_s)
                    
                    dynamic_width = max_len + 4
                    col_width = min(dynamic_width, max_category_width)
                    col_width = max(col_width, 12)
                    sheet.column_dimensions[col_letter].width = col_width

                    # Налаштування форматів чисел
                    start_r = 3 if sheet_name == 'Reconciliation_Audit' else 2
                    for row_idx in range(start_r, sheet.max_row + 1):
                        cell = sheet.cell(row=row_idx, column=col[0].column)
                        if sheet_name == 'Reconciliation_Audit':
                            if col_idx in (2, 6):
                                cell.number_format = 'DD.MM.YYYY HH:mm:ss'
                            elif col_idx in (5, 9, 10):
                                cell.number_format = '#,##0.00 "грн."'
                        elif header_val in (COL_DATE, 'Дата', 'Дата зняття', 'Дата поповнення', 'Дата відправки/зняття', 'Дата отримання/поповнення'):
                            cell.number_format = 'DD.MM.YYYY HH:mm:ss' if header_val not in ('Дата') or sheet_name != 'Daily_Dashboard' else 'DD.MM.YYYY'
                        elif header_val in (COL_AMOUNT, 'Сума зняття', 'Сума поповнення', 'Сума компенсації', 'Залишок зняття', 'Сума джерела', 'Сума отримувача', 'Залишок джерела'):
                            cell.number_format = '#,##0.00' if header_val != COL_AMOUNT else '[Color 10]#,##0.00;-#,##0.00;0.00'
                        elif header_val == COL_BALANCE:
                            cell.number_format = '#,##0.00'
                        elif header_val in ('План', 'Витрати', 'Дохід'):
                            cell.number_format = '#,##0.00'
                        elif header_val in ('Різниця за день', 'Різниця за місяць', 'Різниця загалом'):
                            cell.number_format = '[Color 10]#,##0.00;[Red]-#,##0.00;0.00'

        logger.info(f"Базу оновлено успішно. Разом транзакцій: {len(df)}")
    except PermissionError:
        logger.error(f"Файл {OUTPUT_FILE} відкритий. Будь ласка, закрийте Excel.")
    except Exception as e:
        logger.error(f"Помилка при збереженні: {e}", exc_info=True)
