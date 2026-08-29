import os
import logging
from typing import Optional
import pandas as pd
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from config import (
    OUTPUT_FOLDER, OUTPUT_FILE, COL_DATE, COL_AMOUNT, COL_BALANCE, COL_ID, COL_CAT, COL_CARD, COL_DESC
)
from src.finance_logic import expand_commission_splits_for_reports

logger = logging.getLogger(__name__)

def generate_daily_dashboard(df_ledger: pd.DataFrame) -> pd.DataFrame:
    """Генерує щоденний дашборд за структурою ручного леджера (Витрати.csv) з 4 візуальними секціями."""
    if df_ledger is None or df_ledger.empty:
        return pd.DataFrame(columns=[
            'Місяць', 'Дата', 'План', 'Витрати', 'Дохід', 
            'Різниця за день', 'Різниця за місяць', 'Різниця загалом'
        ])
    
    df = expand_commission_splits_for_reports(df_ledger)
    df[COL_DATE] = pd.to_datetime(df[COL_DATE])
    # Localize to naive just in case
    if df[COL_DATE].dt.tz is not None:
        df[COL_DATE] = df[COL_DATE].dt.tz_localize(None)
        
    df['Дата_Норм'] = df[COL_DATE].dt.normalize()
    min_date = df['Дата_Норм'].min()
    max_date = df['Дата_Норм'].max()
    
    # Generate continuous dates
    all_dates = pd.date_range(start=min_date, end=max_date, freq='D')
    
    # Витрати: сума < 0 (зберігаємо як від'ємні числа)
    expenses_mask = (df[COL_AMOUNT] < 0) & (~df[COL_CAT].isin(['переказ на власний рахунок', 'зняття готівки']))
    df_expenses = df[expenses_mask].groupby('Дата_Норм')[COL_AMOUNT].sum()
    
    # Доходи: позитивні суми (Сума > 0)
    income_mask = (df[COL_AMOUNT] > 0) & (~df[COL_CAT].isin(['переказ з власного рахунку', 'поповнення готівкою']))
    df_income = df[income_mask].groupby('Дата_Норм')[COL_AMOUNT].sum()
    
    # Для закритих місяців рахуємо сумарні доходи по місяцях
    month_income_totals = {}
    for (yr, mn), group in df[income_mask].groupby([df[COL_DATE].dt.year, df[COL_DATE].dt.month]):
        month_income_totals[(yr, mn)] = group[COL_AMOUNT].sum()
        
    now = pd.Timestamp.now()
    plan_cache = {}
    
    ukr_months_nominative = {
        1: 'Січень', 2: 'Лютий', 3: 'Березень', 4: 'Квітень', 5: 'Травень', 6: 'Червень',
        7: 'Липень', 8: 'Серпень', 9: 'Вересень', 10: 'Жовтень', 11: 'Листопад', 12: 'Грудень'
    }
    
    rows = []
    for dt in all_dates:
        yr, mn = dt.year, dt.month
        days_in_month = pd.Period(year=yr, month=mn, freq='M').days_in_month
        
        # Дохідна логіка для дня
        daily_income = df_income.get(dt, 0.0)
        
        # План для дня
        if (yr, mn) not in plan_cache:
            is_closed = (yr < now.year) or (yr == now.year and mn < now.month)
            if is_closed:
                # План = Сума доходу за цей місяць / дні місяця
                tot_inc = month_income_totals.get((yr, mn), 0.0)
                plan_cache[(yr, mn)] = tot_inc / days_in_month
            else:
                # Відкритий місяць: прогноз 40000 / дні місяця
                plan_cache[(yr, mn)] = 40000.0 / days_in_month
                
        plan = plan_cache[(yr, mn)]
        daily_expense = df_expenses.get(dt, 0.0) # Вже від'ємне
        
        rows.append({
            'Місяць': f"{ukr_months_nominative[mn]} {yr}",
            'Дата': dt,
            'План': plan,
            'Витрати': daily_expense,
            'Дохід': daily_income
        })
        
    df_dash = pd.DataFrame(rows)
    
    # Різниця за день
    df_dash['Різниця за день'] = df_dash['План'] + df_dash['Витрати']
    
    # Різниця за місяць = cumulative sum of Різниця за день (reset every month)
    df_dash['Різниця за місяць'] = df_dash.groupby([df_dash['Дата'].dt.year, df_dash['Дата'].dt.month])['Різниця за день'].cumsum()
    
    # Різниця загалом = -48807.41 + cumulative sum of Різниця за день за весь період
    INITIAL_TOTAL_BALANCE = -48807.41
    df_dash['Різниця загалом'] = INITIAL_TOTAL_BALANCE + df_dash['Різниця за день'].cumsum()
    
    # Тимчасові стовпці для групування
    df_dash['temp_year'] = df_dash['Дата'].dt.year
    df_dash['temp_month'] = df_dash['Дата'].dt.month
    
    # Форматуємо 'Дата' як чистий рядок dd.mm.yyyy
    df_dash['Дата'] = df_dash['Дата'].dt.strftime('%d.%m.%Y')
    
    grouped = df_dash.groupby(['temp_year', 'temp_month'], sort=False)
    
    final_rows = []
    for (yr, mn), group in grouped:
        for idx, row in group.iterrows():
            final_rows.append(row.to_dict())
            
        # Розраховуємо суми за місяць
        sum_plan = group['План'].sum()
        sum_expenses = group['Витрати'].sum()
        sum_income = group['Дохід'].sum()
        
        # Беремо останні накопичувальні значення місяця
        last_day_row = group.iloc[-1]
        final_diff_month = last_day_row['Різниця за місяць']
        final_diff_total = last_day_row['Різниця загалом']
        
        # Створюємо підсумковий рядок РАЗОМ
        month_name = ukr_months_nominative[mn]
        rahom_row = {
            'Місяць': f"{month_name} {yr}",
            'Дата': f'РАЗОМ за {month_name} {yr}',
            'План': sum_plan,
            'Витрати': sum_expenses,
            'Дохід': sum_income,
            'Різниця за день': None,
            'Різниця за місяць': final_diff_month,
            'Різниця загалом': final_diff_total,
            'temp_year': yr,
            'temp_month': mn
        }
        final_rows.append(rahom_row)
        
    df_dash_final = pd.DataFrame(final_rows)
    df_dash_final = df_dash_final.drop(columns=['temp_year', 'temp_month'], errors='ignore')
    
    # Переконуємось у правильному порядку колонок
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

def save_final_ledger(df: pd.DataFrame, df_dash: pd.DataFrame, script_path: str, df_analytical: Optional[pd.DataFrame] = None):
    """Зберігає фінальний Excel з двома рівнями заголовків на вкладці Daily_Dashboard та колірним оформленням."""
    try:
        rotate_outputs()
        df_export = df.copy()
        df_export.insert(0, '№ п/п', range(1, len(df_export) + 1))
        
        ukr_months = {
            1: 'Січень', 2: 'Лютий', 3: 'Березень', 4: 'Квітень', 5: 'Травень', 6: 'Червень',
            7: 'Липень', 8: 'Серпень', 9: 'Вересень', 10: 'Жовтень', 11: 'Листопад', 12: 'Грудень'
        }
        df_export.insert(2, 'Місяць', df_export[COL_DATE].dt.month.map(ukr_months) + " " + df_export[COL_DATE].dt.year.astype(str))
        
        # Використовуємо наданий або базовий аналітичний DataFrame для вкладок Expenses та Income
        if df_analytical is None:
            df_analytical_base = df
        else:
            df_analytical_base = df_analytical

        df_analytical_processed = expand_commission_splits_for_reports(df_analytical_base)
        df_analytical_export = df_analytical_processed.copy()
        df_analytical_export.insert(0, '№ п/п', range(1, len(df_analytical_export) + 1))
        df_analytical_export.insert(2, 'Місяць', df_analytical_export[COL_DATE].dt.month.map(ukr_months) + " " + df_analytical_export[COL_DATE].dt.year.astype(str))

        df_income = df_analytical_export[df_analytical_export[COL_AMOUNT] > 0].copy()
        df_expenses = df_analytical_export[df_analytical_export[COL_AMOUNT] < 0].copy()
        
        cols_to_drop_analysis = ['№ п/п', 'Місяць']
        df_income = df_income.drop(columns=cols_to_drop_analysis, errors='ignore')
        df_expenses = df_expenses.drop(columns=cols_to_drop_analysis, errors='ignore')

        with pd.ExcelWriter(OUTPUT_FILE, engine='openpyxl', datetime_format='dd.mm.yyyy hh:mm:ss') as writer:
            df_export.to_excel(writer, index=False, sheet_name='Transactions')
            df_expenses.to_excel(writer, index=False, sheet_name='Expenses')
            df_income.to_excel(writer, index=False, sheet_name='Income')
            
            # Записуємо Daily_Dashboard з першого рядка з заголовками з DataFrame
            df_dash.to_excel(writer, index=False, sheet_name='Daily_Dashboard')

            # Отримуємо об'єкти листів
            for sheet_name in ['Transactions', 'Expenses', 'Income', 'Daily_Dashboard']:
                sheet = writer.sheets[sheet_name]
                
                if sheet_name != 'Daily_Dashboard':
                    # Стандартна стилізація для перших 3-х вкладок
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
                    split_fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
                    data_alignment = Alignment(vertical="center")

                    # Отримуємо індекс стовпця ID для підсвічування розщеплених рядків (тільки для аналітичних вкладок)
                    id_col_idx = None
                    if sheet_name in ('Expenses', 'Income'):
                        for c_idx in range(1, sheet.max_column + 1):
                            col_name = str(sheet.cell(row=1, column=c_idx).value or '').strip().lower()
                            if 'id' in col_name or col_name == COL_ID.lower():
                                id_col_idx = c_idx
                                break

                    prev_period = None
                    group_start = 2
                    for row_idx in range(2, sheet.max_row + 1):
                        curr_period = None
                        is_new_period = False
                        if sheet_name == 'Transactions':
                            curr_period = sheet.cell(row=row_idx, column=3).value
                            is_new_period = prev_period is not None and curr_period != prev_period
                        is_even = row_idx % 2 == 0

                        if is_new_period and sheet_name == 'Transactions':
                            if row_idx - 1 > group_start:
                                sheet.row_dimensions.group(group_start + 1, row_idx - 1, outline_level=1)
                            group_start = row_idx

                        # Безпечна перевірка суфіксів Twins-транзакцій (_main та _comm)
                        is_split_row = False
                        if id_col_idx:
                            val = str(sheet.cell(row=row_idx, column=id_col_idx).value or "")
                            if val.endswith('_main') or val.endswith('_comm'):
                                is_split_row = True

                        for col_idx in range(1, sheet.max_column + 1):
                            cell = sheet.cell(row=row_idx, column=col_idx)
                            top_s = thick_border_side if (sheet_name == 'Transactions' and is_new_period) else thin_grid_side
                            cell.border = Border(left=thin_grid_side, right=thin_grid_side, top=top_s, bottom=thin_grid_side)
                            
                            header_val = sheet.cell(row=1, column=col_idx).value
                            if header_val == 'Дата':
                                cell.alignment = Alignment(horizontal="center", vertical="center")
                            else:
                                cell.alignment = data_alignment
                            
                            if is_split_row:
                                cell.fill = split_fill
                            elif is_even:
                                cell.fill = zebra_fill
                        prev_period = curr_period


                    if sheet_name == 'Transactions' and sheet.max_row > group_start:
                        sheet.row_dimensions.group(group_start + 1, sheet.max_row, outline_level=1)
                        sheet.sheet_properties.outlinePr.summaryBelow = False

                    sheet.freeze_panes = "A2"
                    sheet.auto_filter.ref = sheet.dimensions

                else:
                    # Стилізація Daily_Dashboard
                    sheet.row_dimensions[1].height = 25
                    header_fill = PatternFill(start_color="D3D3D3", end_color="D3D3D3", fill_type="solid")

                    font_header = Font(bold=True, size=14, color="000000")
                    align_center = Alignment(horizontal="center", vertical="center")
                    thick_side = Side(style='thick', color="000000")
                    thin_side = Side(style='thin', color="A6A6A6")

                    # Дані з новими кольорами та вертикальним тонуванням (Зебра)
                    zebra_fill = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")
                    no_fill = PatternFill(fill_type=None)
                    rahom_fill = PatternFill(start_color="F9E79F", end_color="F9E79F", fill_type="solid")
                    
                    for row_idx in range(1, sheet.max_row + 1):
                        is_header = (row_idx == 1)
                        curr_val = sheet.cell(row=row_idx, column=2).value
                        is_rahom = isinstance(curr_val, str) and curr_val.startswith('РАЗОМ')
                        is_even = row_idx % 2 == 0
                        
                        # Групування рядків за місяцями
                        if not is_header:
                            if is_rahom:
                                sheet.row_dimensions[row_idx].outline_level = 0
                            else:
                                sheet.row_dimensions[row_idx].outline_level = 1
                        
                        for col_idx in range(1, 9):
                            cell = sheet.cell(row=row_idx, column=col_idx)
                            
                            # Визначаємо межі для поточної клітинки
                            l_b = thin_side
                            r_b = thin_side
                            t_b = thin_side
                            b_b = thin_side

                            # Зовнішній контур всієї таблиці (Outline)
                            if col_idx == 1:
                                l_b = thick_side
                            if col_idx == 8:
                                r_b = thick_side
                            if row_idx == 1:
                                t_b = thick_side
                            if row_idx == sheet.max_row:
                                b_b = thick_side

                            # Обведення всього рядка заголовків
                            if row_idx == 1:
                                b_b = thick_side

                            # Колонки 'Дата' (ліва та права межі)
                            if col_idx == 2:
                                l_b = thick_side
                                r_b = thick_side

                            # Кожна з трьох колонок з різницями
                            if col_idx in (6, 7, 8):
                                l_b = thick_side
                                r_b = thick_side

                            # Жирні межі для РАЗОМ
                            if is_rahom:
                                t_b = thick_side
                                b_b = thick_side
                            
                            cell.border = Border(left=l_b, right=r_b, top=t_b, bottom=b_b)
                            
                            if is_header:
                                cell.font = font_header
                                cell.alignment = align_center
                                cell.fill = header_fill
                            else:
                                # Налаштування кольору фону (zebra)
                                if is_rahom:
                                    cell.fill = rahom_fill
                                elif is_even:
                                    cell.fill = zebra_fill
                                else:
                                    cell.fill = no_fill
                                        
                                # Встановлення ієрархії шрифтів
                                if is_rahom:
                                    if col_idx == 6:
                                        cell.font = Font(bold=True, italic=True, size=10, color="000000")
                                    elif col_idx == 7:
                                        cell.font = Font(bold=True, italic=True, size=12, color="000000")
                                    elif col_idx == 8:
                                        cell.font = Font(bold=True, italic=True, size=14, color="000000")
                                    else:
                                        cell.font = Font(bold=True, italic=True, size=12, color="000000")
                                else:
                                    if col_idx == 6:
                                        cell.font = Font(size=10, color="000000")
                                    elif col_idx == 7:
                                        cell.font = Font(size=12, color="000000")
                                    elif col_idx == 8:
                                        cell.font = Font(size=14, color="000000")
                                    else:
                                        cell.font = Font(size=11, color="000000")

                                if col_idx in (1, 2):
                                    if is_rahom:
                                        cell.alignment = Alignment(horizontal="left", vertical="center")
                                    else:
                                        cell.alignment = Alignment(horizontal="center", vertical="center")
                                else:
                                    cell.alignment = Alignment(horizontal="right", vertical="center")

                    sheet.sheet_properties.outlinePr.summaryBelow = True
                    sheet.freeze_panes = "A2"
                    sheet.auto_filter.ref = sheet.dimensions

                # --- Налаштування ширини та форматів клітинок (для всіх вкладок) ---
                for col in sheet.columns:
                    col_letter = get_column_letter(col[0].column)
                    header_cell = col[0]
                    header_val = header_cell.value
                    
                    if header_val == 'Опис операції' or header_val == COL_DESC:
                        sheet.column_dimensions[col_letter].width = 20
                    else:
                        import datetime
                        max_len = 0
                        for cell in col:
                            if cell.value is not None:
                                val = cell.value
                                if isinstance(val, (int, float)):
                                    is_fin = header_val in (
                                        'Сума', COL_AMOUNT, 'Залишок', COL_BALANCE, 'План', 'Витрати', 
                                        'Дохід', 'Різниця за день', 'Різниця за місяць', 'Різниця загалом'
                                    )
                                    val_str = f"{val:,.2f}" if is_fin else f"{int(val)}" if val == int(val) else str(val)
                                elif isinstance(val, (datetime.datetime, pd.Timestamp)):
                                    val_str = val.strftime('%d.%m.%Y %H:%M:%S')
                                elif isinstance(val, datetime.date):
                                    val_str = val.strftime('%d.%m.%Y')
                                else:
                                    val_str = str(val)
                                
                                if len(val_str) > max_len:
                                    max_len = len(val_str)
                        sheet.column_dimensions[col_letter].width = max_len + 4

                    # Налаштування форматів чисел
                    start_r = 2
                    for row_idx in range(start_r, sheet.max_row + 1):
                        cell = sheet.cell(row=row_idx, column=col[0].column)
                        if header_val in (COL_DATE, 'Дата'):
                            cell.number_format = 'DD.MM.YYYY HH:mm:ss' if header_val == COL_DATE else 'DD.MM.YYYY'
                        elif header_val == COL_AMOUNT:
                            cell.number_format = '[Color 10]#,##0.00;-#,##0.00;0.00'
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
