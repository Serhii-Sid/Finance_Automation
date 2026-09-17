# 📊 Finance Automation & Wealth Management Tracker

[ 🇬🇧 English ](#-finance-automation--wealth-management-tracker) | [ 🇺🇦 Читати українською ](#-finance-automation--wealth-management-tracker---українська-версія)

<a id="english"></a>
![Python Version](https://img.shields.io/badge/python-3.12-blue.svg) ![Pandas](https://img.shields.io/badge/pandas-2.2-150458.svg) ![Excel](https://img.shields.io/badge/Excel-openpyxl-1F4E78.svg) ![License](https://img.shields.io/badge/license-MIT-green.svg) ![Build](https://img.shields.io/badge/build-passing-brightgreen.svg)

**Finance Automation** is a local engineering ETL pipeline (Extract, Transform, Load) designed for automatic family finance consolidation and real **Net Worth** analysis based on raw statements from Ukrainian banks. Built for personal wealth management, the system solves the chaos of handling **12+ unique cards across 5+ Ukrainian banks** (PrivatBank, Monobank, PUMB, A-Bank, Bank Alliance). Instead of a monthly manual routine of moving transactions into Excel, this Python engine parses PDF/Excel files in seconds, performs deduplication, intelligently cleanses "financial noise", and builds two-layer management reporting.

 ---

## 💻 Tech Stack
* **Programming Language:** Python 3.12
* **Data Processing & Analysis:** Pandas, NumPy
* **PDF & Excel Parsing:** `pdfplumber`, `openpyxl`, `xlrd`, `Regex`
* **Data Engineering:** MD5 Vector Hashing, `datetime` module
* **Algorithms & Financial Logic:** "Twins" Algorithm, Pandas Time-Window Matching, Dynamic Commission Splitter, FIFO Cash Clearing
* **Presentation Layer (UI):** Microsoft Excel (PivotTables, PivotCharts, Slicers, Timeline)


## 🏗 System Architecture (Data Pipeline)

```mermaid
flowchart TD
    subgraph INGESTION["1. Data Sources (Raw Ingestion)"]
        A1["📄 PDF Statements (Mono, PUMB, Alliance, A-Bank)"]
        A2["📊 Excel Statements (PrivatBank)"]
    end

    subgraph PARSERS["2. Parsers Module (parsers/)"]
        B["⚙️ BaseParser (Abstract Class)"]
        A1 --> B
        A2 --> B
        B --> C["Standardized DataFrame"]
    end

    subgraph ETL["3. ETL Phase & Categorization (src/data_manager.py)"]
        C --> D["🔑 Vector MD5-ID (make_short_id_vectorized)"]
        D --> E["🧹 Description Cleaning (_normalize_text)"]
        E --> F["🎯 Two-Mode Categorization (Keyword First ➡️ MCC Map)"]
        F --> G["🔍 Incremental Merge & Deduplication (reconcile_and_merge)"]
    end

    subgraph CLEARING["4. Analytical 3-Level Clearing (src/finance_logic.py)"]
        G --> H1["👥 Twins Algorithm (Internal Transfers + Fees)"]
        G --> H2["💵 Cash Clearing (ATM Offset)"]
        G --> H3["🚀 Investments & Transit (Investment & Transit Flow)"]
    end

    subgraph STORAGE["5. Data Layer (src/report_engine.py)"]
        H1 --> I
        H2 --> I
        H3 --> I
        I["💾 output/Total_Ledger.xlsx"]
        I --> I1["📋 Transactions (Raw Data Lake)"]
        I --> I2["🟢 Income and 🔴 Expenses (Data Marts with Dynamic Split)"]
        I --> I3["📊 Daily_Dashboard (Daily Ledger & Net Worth)"]
    end

    subgraph PRESENTATION["6. Presentation Layer (Excel UI)"]
        I3 --> J["📈 output/Dashboard.xlsx (KPIs, Slicers, PivotCharts)"]
    end

    style INGESTION fill:#e1f5fe,stroke:#0288d1,stroke-width:2px
    style PARSERS fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style ETL fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style CLEARING fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px
    style STORAGE fill:#fffde7,stroke:#fbc02d,stroke-width:2px
    style PRESENTATION fill:#e0f2f1,stroke:#00796b,stroke-width:2px
```


## 🎯 Key Features, Goal & Business Value

### Problem Statement & Goal
When managing a personal or family budget across multiple bank cards, the primary hurdles are chaotic statement formats, double accounting during transfers between own accounts, hidden bank fees, and distorted asset balances caused by credit limits.
**Project Goal** — full automation of financial flow collection and analysis: transforming fragmented PDF/Excel files into a deduplicated database and a ready-to-use Excel management dashboard in just a few minutes.

## 💼 Business Impact & Analytical Value

* **⚡ Significant Time Savings**: Consolidating multi-month bank statements from 5 different banks (PrivatBank, Monobank, PUMB, A-Bank, Bank Alliance) takes no more than **a few minutes**.
* **📅 End-to-End Chronological Ledger**: Automatically merges transactions from **5 banks and 12 unique cards** into a single linear timeline with duplicate detection and strict temporal sorting.
* **📈 Transparent Net Worth**: Automatically accounts for bank credit limits to calculate real net asset volume in real time.
* **🧼 Financial Noise Reduction**: The intelligent "Twins" algorithm automatically finds and links internal transfers between family accounts, cleansing financial analytics from double turnover.
* **📊 Ready Management Reporting**: Automatic generation of an interactive **Daily Dashboard** with monthly sub-totals and cumulative asset balances.

---

## 📥 Primary Dataset: Parsing, Standardization & Cleaning

### 📸 Data Transformation Preview

| 📄 BEFORE: Raw Fragmented Statements | 📊 AFTER: Unified Consolidated Dataset (Data Lake) |
| :---: | :---: |
| ![Monobank Raw](docs/mono_screen.PNG)<br>![PrivatBank Raw](docs/private_screen.PNG)<br>![PUMB Raw](docs/pumb_screen.PNG) | ![Cleaned Ledger](docs/Dataset.PNG) |
| *Unstructured PDF/Excel files from various banks (Monobank, PrivatBank, PUMB)* | *Standardized database with MD5 hashes, removed duplicates, and auto-categorization* |

---

### 📥 Multi-Bank Parsing Engine
The system is built on an abstract `BaseParser` class defining a unified parsing lifecycle for any bank statement (Read ➔ Identify ➔ Standardize ➔ Adjust). Custom logic is implemented for each statement type:

* **🟢 PrivatParser (Excel)** — dynamically maps variable PrivatBank columns and identifies card type via metadata.
* **🟨 MonoParser (PDF)** — extracts transaction tables, automatically detects IBAN, and adjusts credit limits from the header.
* **🔵 PumbParser (PDF)** — intelligently merges multi-line transaction descriptions (often split during PDF export) and restores exact operation timestamps.
* **🟪 AllianceParser (PDF)** — uses regular expressions (Regex) to instantly locate 4-digit card tails in technical text.
* **🟧 AbankParser (PDF)** — dynamically detects IBAN in the statement header and enforces card assignment for all transactions.

---

## 🔄 ETL Phase: Configuration, Cleansing & DataFrame Preparation

Before applying financial analytics, all information passes through an end-to-end ETL pipeline (Extract, Transform, Load) converting raw statements into a standardized data array.

#### 1. Schema & Numeric Normalization
* **Unified Column Standard (Schema)**: Every read file is coerced into a strict schema: `ID_Транзакції` (Transaction ID), `Дата` (Date), `Категорія` (Category), `Картка` (Card), `Опис операції` (Description), `Сума` (Amount), and `Залишок` (Balance).
* **Type Transformation (Float Normalization)**: Via `clean_and_transform`, all amounts and balances are stripped of thousand separators (spaces), commas are replaced with dots, and technical currency symbols are trimmed using regex `(-?\d+\.?\d*)` before converting to `float`.

#### 2. Intelligent Linguistic Description Normalization (`_normalize_text`)
Before categorization, transaction text is thoroughly cleaned of technical noise:
* Text is converted to lowercase, replacing Latin `i` with Ukrainian `і` for keyboard layout unification.
* Textual noise and filler words are removed: `uah`, `грн`, `покупка` (purchase), `оплата` (payment), `переказ` (transfer), `списання` (charge).
* Random technical digits (authorization numbers, receipt IDs) that interfere with keyword matching are stripped.
* **Contact Preservation**: Phone numbers in `+380` formats are temporarily masked under a `plusua` marker. This saves them from numeric digit stripping and turns them into a reliable `plus380` marker for mobile top-up auto-detection.

#### 3. Vectorized Transaction ID Generation (`make_short_id_vectorized`)
Since banks do not provide global transaction IDs, the system creates a deterministic 8-digit ID:
1. Constructs a unique string: `[Date YYYY-MM-DD HH:MM:SS] + " *" + [Card Name] + "* " + [Amount {:.2f}]`.
2. Encodes the string into an MD5 hash.
3. Takes the first 8 hex characters and converts them to decimal modulo $10^8$ with left zero-padding.

![Deterministic ID Generation Demo](docs/ID.PNG)

#### 4. Incremental Merge & Deduplication (`reconcile_and_merge`)
* Newly ingested statements may overlap existing historical periods. The system computes IDs for new rows and compares them against `Total_Ledger.xlsx`.
* Duplicate entries are filtered out, while new unique records are appended.
* The final DataFrame is re-sorted chronologically by date and time.

#### 5. Card Balance Reconstruction
* PDF credit card statements from certain banks lack per-transaction running balances.
* `apply_bank_specific_post_processing` detects such cards and automatically reconstructs the cumulative balance for each operation based on known statement opening/closing balances and transaction amounts.

![Card Running Balance Calculation Demo](docs/funds_balance.PNG)

#### 6. Account Identity Detection & Credit Limit Adjustments
* **Account Identity Detector (`detect_account_identity`)**: Reads statement metadata using a strict hierarchy (IBAN regex `UA` + 27 digits ➔ 4-digit card tail) to assign the correct card name and owner from config.

![Card Naming Standardization Demo](docs/Card_Naming.PNG)

* **Credit Limit Adjustment**: Upon detecting bank credit limits (e.g. Monobank or Alliance), the system automatically subtracts the credit limit from the card balance. This prevents Net Worth distortion by separating bank credit lines from actual owned assets.

#### 7. Two-Mode Auto-Categorization ("Keyword First")

To prevent financial chaos and duplicate synonym categories (e.g., simultaneous existence of "groceries", "food products", or "supermarkets"), the system enforces a **strict target category list** (6 for income and 17 for expenses). All operations are forcibly categorized using the "Keyword First" algorithm:

1. **Stage 1: Keyword Search (`CATEGORIES_KEYWORDS`)** — normalized transaction description is matched against key brand markers (e.g. `atb` or `silpo` are mapped to `groceries`).
2. **Stage 2: MCC Code Lookup (`MCC_MAP`)** — if keywords are absent or ambiguous (`AMBIGUOUS_CATEGORIES` like "payment" or "transfer"), the category is determined by the Merchant Category Code (e.g. MCC `5411` ➔ `groceries`).
3. **🛡️ Fallback Logic for Unrecognized Transactions**:
    * Uncategorized expense (Amount < 0) ➔ assigned to **`other expenses`**.
    * Uncategorized income (Amount > 0) ➔ assigned to **`other income`**.

---

### 📊 Analytical Core: Flow Distribution & 3-Level Clearing Engine

After data cleansing and standardization, the analytical engine `report_engine.py` and financial logic `finance_logic.py` execute two key tasks: data flow separation and financial noise elimination.

#### 1. 📂 Data Structuring: Income and Expense Ledgers
For analytical clarity, the final Excel workbook is split into two independent chronological ledgers (sheets) operating with categories from `config.py`:

* **🟢 Income Ledger**: accumulates positive transactions (Amount > 0) across 6 categories: *salary & payouts, bonuses & cashback, cash deposits, external transfers, other income*, and technical *internal transfer (incoming)*.
* **🔴 Expenses Ledger**: contains all debit transactions (Amount < 0) across 17 expense categories, grouped by type (from *utilities* and *groceries* to technical *ATM cash withdrawals* or *internal transfers (outgoing)*).

![Income Ledger Distribution Demo](docs/Income.PNG)

![Expenses Ledger Distribution Demo](docs/Expences.PNG)

#### 2. 🛡️ Three-Level Automatic Clearing Engine
The core engineering value of the project is mathematical modeling of actual money movement. To prevent multi-card statements from distorting real consumption analytics, the system automatically offsets counter-transactions across three levels:

##### 👥 Level 1: Internal Transfers Between Own Accounts (Twins Algorithm)
When money is transferred between accounts tracked in the system (e.g., from Serhii's card to Olenka's card), banks log two separate operations: an expense in one bank and income in another. Unadjusted, family budget turnover would be artificially inflated by this amount.
* **Solution**: The "Twins" algorithm searches for opposite transactions within a short time window. Upon a match (e.g., Olenka received the amount Serhii just sent), the system labels these operations with technical categories *internal transfer (outgoing)* / *internal transfer (incoming)*, excluding them from net consumer expense calculations.
* **🛠️ Bank Fee Handling**: Transfers are often accompanied by fees (e.g., Serhii sent `10 050.00` UAH, while Olenka received `10 000.00` UAH). A naive algorithm would fail to match these due to sum mismatch.
    * *Our Solution*: The system detects the delta, automatically splits the transfer transaction on-the-fly, isolates `50.00` UAH as *other expenses* (bank fee), and successfully links the remaining `10 000.00` UAH as a clean internal transfer. Ledger balance remains perfectly reconciled.

| 📄 BEFORE: Debit of 3065.25 and Credit of 3050.00 (Fee 15.25) | 📊 AFTER: Debit transaction split into 2: 3050.00 (transfer body) + 15.25 (bank fee) |
| :---: | :---: |
| ![Original Transactions](docs/Comission1.PNG) | ![Split Transactions](docs/Comission2.PNG) |
| *Original Transactions* | *Split Transactions (Note the matching IDs)* |


### 3.2. ATM Cash Offset (Cash Clearing & ATM-Noise Reduction)

#### ❓ Business Problem
ATM cash withdrawals and subsequent cash deposits via terminals onto another card do not constitute real consumer expenses or income. Without processing, these transactions create artificial transit turnover, inflating financial reporting numbers.

#### ⚙️ `process_cash_clearing` Logic
The `finance_logic.py` module executes automatic mutual offsetting of cash flows using **Local FIFO Priority**:

1. **Intra-Month FIFO Clearing:** Within each calendar month, ATM cash withdrawals and deposits are mutually offset strictly via FIFO up to the limit.
2. **Inter-Month Buffer (Up to the 10th):** Unused cash deposits made by the 10th of the month offset remaining cash withdrawals from the previous month.
3. **Dynamic Boundary Splitting:** A transaction landing on the limit boundary is automatically split into separate rows sharing timestamps and IDs.
4. **Unmatched Balance Allocation:** Withdrawals exceeding the offset limit are re-categorized into *`other expenses`*, while remaining deposits become *`other income`*.
5. **Raw Data First Principle:** All manipulations occur "on-the-fly" during analytical `df_analytical` generation for Daily Dashboard, keeping `Total_Ledger.xlsx` 100% untouched.

#### 📸 Cash Clearing Visual Preview

| 📄 BEFORE: Raw withdrawal/deposit transactions | 📊 AFTER: `process_cash_clearing` result |
| :---: | :---: |
| ![Cash Clearing Before](docs/Cash1.PNG) | ![Cash Clearing After](docs/Cash2.PNG) |
| *ATM Cash Withdrawal of 16000.00 UAH* | *Allocation of 16000.00 UAH across deposit transactions. Transit turnover eliminated, deltas re-categorized* |


##### 🚀 Level 3: Transit Operations & "Investments" Category
* **Transit Operations**: Tracks targeted fund movement through transit accounts (e.g. term deposits, savings vaults, or temporary safes).
* **"Investments" Logic**: Large outgoing transit flows (e.g. foreign currency purchases, broker transfers, or bond purchases) are not treated as consumer burn rate (like food or clothing). Such transactions pass through a specialized filter and are classified as **`investments`** (assets). This preserves accurate monthly consumption tracking (Burn Rate) and net wealth accumulation.

---

### 📊 Analytics Module & Visual Dashboard (`report_engine.py`)

The daily analytics module transforms the consolidated transaction array into a visual daily management report following classic financial ledger architecture. The output is an interactive **Daily_Dashboard** tab in `Total_Ledger.xlsx`.

#### 1. Daily Dashboard Structure
Aggregates financial flows by calendar day and compares actual expenses against planned daily budget limits across 8 columns:
1. **Month** — calendar month and year (e.g., March 2026).
2. **Date** — specific day in DD.MM.YYYY format.
3. **Plan** — daily budget limit allocated for the family.
4. **Expenses** — total actual daily expenses (negative value or `0.00`).
5. **Income** — total actual daily income receipts.
6. **Daily Budget Variance** — net financial result of the day against the plan.
7. **Monthly Cumulative Balance** — cumulative savings or overspend balance within the current month.
8. **Net Worth / Cumulative Asset Balance** — global net worth progression accounting for initial balance and bank credit limits.

#### 2. Mathematical Calculation Model
For each calendar day, the system computes:
* **Daily Budget Variance**:
    $$\text{Daily Budget Variance} = \text{Plan} + \text{Expenses} + \text{Income}$$
    *(Since expenses are negative in DataFrame, addition computes the net variance)*.
* **Monthly Cumulative Balance**:
    Cumulative sum of daily variances within a calendar month. Resets on the 1st of each month to show intermediate budget performance:
    $$\text{Monthly Cumulative Balance}_{d} = \sum_{i=1}^{d} \text{Daily Budget Variance}_{i}$$
* **Net Worth / Cumulative Asset Balance**:
    End-to-end cumulative total from ledger inception, reflecting actual family net wealth in real time:
    $$\text{Net Worth / Cumulative Asset Balance}_{t} = \text{Initial Balance} + \sum_{i=1}^{t} \text{Daily Budget Variance}_{i}$$

#### 3. Row Grouping & Professional Styling (openpyxl)
* **Monthly Subtotal Rows**: Automatically inserts a **"TOTAL for [Month YYYY]"** summary row after each month's end. *Plan, Expenses*, and *Income* are summed, while *Monthly Cumulative Balance* and *Net Worth* capture the closing status.
* **Detail Row Grouping**: Individual transactions for each day are collapsible under Excel **"+"** outline grouping buttons inside each calendar day.
* **Dynamic Row Height & Text Wrap**: `wrap_text=True` is enabled for descriptions, with row height automatically adjusting to text length to prevent truncating long vendor names.
* **Visual Formatting**: Two-level header structure, bold monthly totals with colored fill, auto-fitted column widths, optimized for landscape printing.

![Monthly Dashboard Subtotals Preview](docs/dashboard.PNG)

---

### 📈 Data Visualization & Interactive Dashboard (`output/Dashboard.xlsx`)

For visual financial analysis, a **Decoupled Data & Presentation Layer** architecture is implemented. This separates automated Python data processing from Excel visual analytics, guaranteeing 100% preservation of formatting, custom pivot tables, and slicers.

#### 🏗 Solution Architecture:
1. **`output/Total_Ledger.xlsx` (Data Layer)** — local database (Data Lake / Marts), automatically generated and updated by Python.
2. **`output/Dashboard.xlsx` (Presentation Layer)** — interactive management dashboard containing analytical cards, charts, and slicers.

#### 📊 Key Dashboard Features:
* **KPI Cards**: highlight key financial metrics (total income, expenses, and net surplus/deficit).
![Visual KPI Cards Preview](docs/Cards.PNG)
* **Dynamic Slicers**: one-click interactive filtering of all charts and cards by selected months.
* **Drill-Down PivotCharts**: two-level date hierarchy (`Month` ➡️ `Date`) enabling toggling between high-level monthly trends and daily granularity.

* **PivotTable External Data Source**: pivot tables in `Dashboard.xlsx` are linked directly to column ranges in `Total_Ledger.xlsx`. New transactions processed by Python update the dashboard with a single **"Refresh All" (Data -> Refresh All)** click in Excel.

![Income and Expense Analysis Chart](docs/income_expenses_analysis.PNG)

![Financial Position Chart](docs/financial_condition.PNG)

![Expense Categories Breakdown](docs/report_expenses_categories.PNG)

---

### 💼 Deliverables & Customization

This project serves as a complete, flexible engineering framework for family or micro-office financial consolidation and wealth analytics.

#### End-User Deliverables:
1. **🧼 Clean Data**: Fully deduplicated, chronologically structured, and linguistically normalized transaction register in Excel.
2. **📊 Executive Reporting**: Automatically generated `Daily_Dashboard` with transaction drill-down, monthly subtotals, and Net Worth tracking.
3. **🛡️ Data Security**: Runs 100% locally — zero financial or personal data is transmitted to external cloud services.

#### 🔧 Customization Capabilities:
Modular architecture allows easy adaptation:
* **New Bank Integration**: Quick onboarding of statement formats for any financial institution worldwide (requires inheriting `BaseParser`).
* **Custom Category Tree**: Full customization for personal or small business chart of accounts.
* **Business Rule Configuration**: Flexible tuning of Twins transfer matching, credit limits, and daily expenditure targets.

---

### 📞 Let's Connect!

Looking for an automated solution to consolidate personal/family finances, cleanse unstructured banking data, or automate Excel management reporting? I'm available for engineering projects of any complexity!

* **💻 Upwork Profile:** [Order Development on Upwork](https://upwork.com/freelancers/your-profile)
* **🤝 LinkedIn:** [Connect on LinkedIn]
* **📧 Email:** [sid78rivne@gmail.com]
* **🐙 GitHub:** [https://github.com/Serhii-Sid]

<br>
<hr>
<br>

# 🇺🇦 Finance Automation & Wealth Management Tracker - Українська версія

[ ⬆️ Нагору / Back to Top ](#-finance-automation--wealth-management-tracker) | [ 🇬🇧 English ](#-finance-automation--wealth-management-tracker) | [ 🇺🇦 Читати українською ](#-finance-automation--wealth-management-tracker---українська-версія)

<a id="ukrainian"></a>
![Python Version](https://img.shields.io/badge/python-3.12-blue.svg) ![Pandas](https://img.shields.io/badge/pandas-2.2-150458.svg) ![Excel](https://img.shields.io/badge/Excel-openpyxl-1F4E78.svg) ![License](https://img.shields.io/badge/license-MIT-green.svg) ![Build](https://img.shields.io/badge/build-passing-brightgreen.svg)

**Finance Automation** — це локальний інженерний ETL-конвеєр (Extract, Transform, Load) для автоматичної консолідації сімейних фінансів та розрахунку реальних чистих активів (**Net Worth**) на основі сирих виписок з українських банків. Система розроблена для персонального використання та вирішує проблему хаосу при веденні бюджету з **12+ унікальних карток у 5+ банках України** (ПриватБанк, Monobank, ПУМБ, А-Банк, Банк Альянс). Замість щомісячної ручної рутини перенесення транзакцій в Excel, Python-скрипт за лічені секунди здійснює парсинг PDF/Excel файлів, дедуплікацію, інтелектуальне очищення від "фінансового шуму" та формує двошарову управлінську звітність.

 ---

## 💻 Технологічний стек (Tech Stack) 
* **Мова розробки:** Python 3.12 
* **Обробка та аналіз даних:** Pandas, NumPy
* **Парсинг PDF та Excel:** `pdfplumber`, `openpyxl`, `xlrd`, `Regex`
* **Інженерія даних:** Векторне хешування MD5, модуль `datetime`
* **Алгоритми та фінансова логіка:** Алгоритм "Twins", часові вікна Pandas (Time-Window Matching), Dynamic Commission Splitter, FIFO Cash Clearing
* **Шар презентації (UI):** Microsoft Excel (PivotTables, PivotCharts, Slicers, Timeline)


## 🏗 Загальна архітектура системи (Data Pipeline)

```mermaid
flowchart TD
    subgraph INGESTION["1. Джерела даних (Raw Ingestion)"]
        A1["📄 PDF-виписки (Mono, ПУМБ, Альянс, А-Банк)"]
        A2["📊 Excel-виписки (ПриватБанк)"]
    end

    subgraph PARSERS["2. Модуль Парсерів (parsers/)"]
        B["⚙️ BaseParser (Абстрактний клас)"]
        A1 --> B
        A2 --> B
        B --> C["Стандартизований DataFrame"]
    end

    subgraph ETL["3. Фаза ETL та Категоризація (src/data_manager.py)"]
        C --> D["🔑 Векторний MD5-ID (make_short_id_vectorized)"]
        D --> E["🧹 Очищення описів (_normalize_text)"]
        E --> F["🎯 Дворежимна категоризація (Keyword First ➡️ MCC Map)"]
        F --> G["🔍 Інкрементне злиття та дедуплікація (reconcile_and_merge)"]
    end

    subgraph CLEARING["4. Аналітичний 3-рівневий Кліринг (src/finance_logic.py)"]
        G --> H1["👥 Twins Algorithm (Внутрішні перекази + Комісії)"]
        G --> H2["💵 Cash Clearing (Компенсація готівки)"]
        G --> H3["🚀 Investments & Transit (Інвестиції та транзит)"]
    end

    subgraph STORAGE["5. Data Layer (src/report_engine.py)"]
        H1 --> I
        H2 --> I
        H3 --> I
        I["💾 output/Total_Ledger.xlsx"]
        I --> I1["📋 Transactions (Raw Data Lake)"]
        I --> I2["🟢 Income та 🔴 Expenses (Data Marts з Dynamic Split)"]
        I --> I3["📊 Daily_Dashboard (Щоденний леджер та Net Worth)"]
    end

    subgraph PRESENTATION["6. Presentation Layer (Excel UI)"]
        I3 --> J["📈 output/Dashboard.xlsx (KPIs, Slicers, PivotCharts)"]
    end

    style INGESTION fill:#e1f5fe,stroke:#0288d1,stroke-width:2px
    style PARSERS fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style ETL fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style CLEARING fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px
    style STORAGE fill:#fffde7,stroke:#fbc02d,stroke-width:2px
    style PRESENTATION fill:#e0f2f1,stroke:#00796b,stroke-width:2px
```


## 🎯 Загальний функціонал, мета та бізнес-цінність 

### Проблематика та мета
При веденні особистого бюджету з багатьох банківських карток головними перешкодами є хаос у форматах виписок, подвійний облік коштів при переказах між власними рахунками, приховані комісії та викривлення балансу через кредитні ліміти.
**Мета проєкту** — повна автоматизація збору та аналізу фінансових потоків: перетворення розрізнених PDF/Excel файлів у дедупліковану базу даних та готовий Excel-дашборд всього за кілька хвилин.

## 💼 Бізнес-результат та аналітична цінність

*   **⚡ Значна економія часу**: Консолідація виписок за кілька місяців з різних банків (ПриватБанк, Монобанк, ПУМБ, А-Банк, Альянс) займає не більше **кількох хвилин**.
*   **📅 Наскрізний хронологічний реєстр**: Автоматичне об'єднання транзакцій з **5 банків та 12 унікальних карт** в єдину лінійну стрічку із визначенням і відсіюванням дублікатів та суворим сортуванням за часом.
*   **📈 Наочний Net Worth (Чисті Активи)**: Автоматичний облік кредитних лімітів банків для розрахунку реального обсягу власних накопичень у реальному часі.
*   **🧼 Очищення від фінансового шуму**: Розумний алгоритм "Twins" автоматично знаходить та пов'язує внутрішні перекази між рахунками членів родини, очищаючи фінансову аналітику від подвійного обороту.
*   **📊 Готовий управлінський звіт**: Автоматична генерація інтерактивної вкладки щоденної аналітики (**Daily Dashboard**) з проміжними місячними підсумками та накопичувальним балансом.

---

## 📂 Архітектура репозиторію

```text
Finance_Automation/
├── parsers/               # Плагіни банківських парсерів (Privat, Mono, PUMB, Alliance, Abank)
├── src/                   # Аналітичне ядро системи
│   ├── data_manager.py    # Зчитування, нормалізація, MD5-хешування та дедуплікація
│   ├── finance_logic.py   # Кліринг, розщеплення комісій, кредитні ліміти
│   └── report_engine.py   # Двигун Daily_Dashboard та стилізація openpyxl
├── input_data/            # Директорія для сирих PDF/Excel виписок (у .gitignore)
├── output/                # Папка згенерованих звітів Total_Ledger.xlsx та Dashboard.xlsx
├── docs/                  # Скріншоти та медіа-матеріали для презентації
├── config.py              # Глобальні словники категорій, MCC, IBAN та колонок
├── process_privat.py      # Головний оркестратор запуску (вхідна точка)
├── requirements.txt       # Залежності проєкту (Pandas, openpyxl, pdfplumber)
└── README.md              # Головна документація проєкту
```

---

## 📥 Первинний датасет: Парсинг, Стандартизація та Очищення

### 📸 Наочна трансформація даних (Data Transformation Preview)

| 📄 БУЛО: Сирі розрізнені виписки (Raw Statements) | 📊 СТАЛО: Єдиний консолідований датасет (Data Lake) |
| :---: | :---: |
| ![Monobank Raw](docs/mono_screen.PNG)<br>![PrivatBank Raw](docs/private_screen.PNG)<br>![PUMB Raw](docs/pumb_screen.PNG) | ![Cleaned Ledger](docs/Dataset.PNG) |
| *Неструктуровані PDF/Excel із різних банків (Monobank, ПриватБанк, ПУМБ)* | *Стандартизована база з MD5-хешами, усуненими дублікатами та автокатегоризацією* |

---

### 📥 Мультибанківський парсинг сирих виписок (Multi-Bank Parsing Engine)
Система побудована на базі абстрактного класу `BaseParser`, що визначає єдиний життєвий цикл парсингу для будь-якого банку (зчитування ➔ ідентифікація ➔ стандартизація ➔ коригування). Для кожного типу виписки реалізовано індивідуальну логіку:

*   **🟢 PrivatParser (Excel)** — динамічно зіставляє та зчитує змінні колонки ПриватБанку, визначаючи тип картки за метаданими.
*   **🟨 MonoParser (PDF)** — вилучає таблиці транзакцій, автоматично розпізнає IBAN та коригує кредитний ліміт із шапки файлу.
*   **🔵 PumbParser (PDF)** — інтелектуально склеює багаторядкові описи транзакцій (які часто розриваються при експорті з ПУМБ) та відновлює точний час операцій.
*   **🟪 AllianceParser (PDF)** — використовує регулярні вирази для миттєвого пошуку 4-значного хвоста картки в технічному тексті виписки.
*   **🟧 AbankParser (PDF)** — динамічно визначає IBAN у заголовку виписки та примусово закріплює відповідну карту за всіма транзакціями у файлі.

---

## 🔄 Фаза ETL: Налаштування, Очищення та Підготовка DataFrame

Перед застосуванням фінансової аналітики вся інформація проходить через наскрізний ETL-конвеєр (Extract, Transform, Load), який перетворює сирі та розрізнені виписки в єдиний стандартизований масив даних.

#### 1. Уніфікація структури та числових показників
*   **Єдиний стандарт колонок (Schema)**: Кожен зчитаний файл приводиться до суворої структури: `ID_Транзакції`, `Дата`, `Категорія`, `Картка`, `Опис операції`, `Сума` та `Залишок`.
*   **Трансформація типів (Float Normalization)**: Через функцію `clean_and_transform` усі суми та баланси очищуються від розділювачів тисяч (пробілів), коми автоматично замінюються на крапки, а технічні символи валют відсікаються регулярним виразом `(-?\d+\.?\d*)` перед конвертацією в числовий тип `float`.

#### 2. Інтелектуальна лінгвістична нормалізація описів (`_normalize_text`)
Перед класифікацією текст транзакції повністю очищується від технічного сміття:
*   Текст переводиться у нижній регістр, виконується заміна латинської літери `i` на українську `і` для уніфікації розкладки.
*   Усувається текстовий шум та слова-парази: `uah`, `грн`, `покупка`, `оплата`, `переказ`, `списання`.
*   Вирізаються всі випадкові технічні цифри (номери авторизацій, чеків), які заважають пошуку по ключах.
*   **Збереження контактів**: Номери телефонів у форматах `+380` тимчасово маскуються під маркер `plusua`. Це рятує їх від видалення на етапі чистки цифр і в кінці перетворює на надійний маркер `plus380` для авторозпізнавання поповнень мобільних.

#### 3. Векторизована генерація ID транзакцій (`make_short_id_vectorized`)
Оскільки банки не надають глобального ID, система створює стабільний та відтворюваний 8-значний ID самостійно:
1.  Формується унікальний рядок транзакції: `[Дата YYYY-MM-DD HH:MM:SS] + " *" + [Назва карти] + "* " + [Сума {:.2f}]`.
2.  Рядок кодується в MD5-хеш.
3.  Перші 8 символів хешу перетворюються з шістнадцяткової системи в десяткову за модулем $10^8$ із доповненням нулями зліва.

![Демонстрація генерації унікальних ID транзакцій](docs/ID.PNG)

#### 4. Інкрементне злиття та дедуплікація (`reconcile_and_merge`)
*   Нові завантажені виписки можуть перекривати вже наявні періоди. Система розраховує ID для нових рядків і порівнює їх із базою `Total_Ledger.xlsx`.
*   Транзакції, які вже існують у базі, відсіюються як дублікати, а унікальні нові записи додаються.
*   Фінальний DataFrame примусово пересортовується в хронологічному порядку за датою та часом.

#### 5. Розрахунок залишків на картах
*   Виписки кредитних карток деяких банків у форматі PDF не містять поточного залишку для кожної транзакції.
*   Функція `apply_bank_specific_post_processing` виявляє картки таких банків і автоматично розраховує накопичувальний баланс для кожної операції на основі відомого стартового або фінального балансу виписки та сум транзакцій.

![Демонстрація розрахунку та відображення залишку коштів на карті](docs/funds_balance.PNG)

#### 6. Автодетекція рахунків та лімітів
*   **Детектор рахунків (`detect_account_identity`)**: Зчитує метадані виписки і за жорсткою ієрархією (IBAN регулярним виразом `UA` + 27 цифр -> 4-значний хвіст карти) автоматично підставляє правильну назву картки та власника з конфігурації.

![Демонстрація стандартизації назв карток](docs/Card_Naming.PNG)

*   **Коригування лімітів**: При виявленні кредитного ліміту у виписках, система автоматично віднімає суму ліміту від залишку на карті. Це дозволяє уникнути викривлення показника Net Worth, відокремлюючи кредитні кошти банку від реальних.

#### 7. Дворежимна автокатегоризація ("Keyword First")

Щоб уникнути фінансового хаосу та появи дублюючих категорій-синонімів (наприклад, одночасного існування "продукти", "продовольчі товари" чи "супермаркети"), у системі жорстко зафіксовано **обмежений перелік цільових категорій** (6 для доходів та 17 для витрат). Усі операції примусово розподіляються виключно в межах цього списку за дворежимним алгоритмом "Keyword First":

1.  **Етап 1: Пошук за ключовими словами (`CATEGORIES_KEYWORDS`)** — очищений опис транзакції зіставляється з текстовими маркерами (наприклад, `атб` чи `сільпо` примусово маркуються як `продукти`).
2.  **Етап 2: Пошук за MCC-кодами (`MCC_MAP`)** — якщо ключових слів немає або транзакція неоднозначна (`AMBIGUOUS_CATEGORIES` на кшталт "оплата" чи "переказ"), категорія визначається за кодом Merchant Category Code торгової точки (наприклад, MCC `5411` -> `продукти`).
3.  **🛡️ Обробка нерозпізнаних транзакцій (Fallback Logic)**: 
    *   Якщо система не може визначити категорію для витрати (Сума < 0), транзакції автоматично присвоюється категорія **`інші витрати`**.
    *   Якщо не вдалося визначити категорію для доходу (Сума > 0), транзакція маркується як **`інші надходження`**.

---

### 📊 Аналітичне Ядро: Розподіл потоків та 3-рівневий Кліринг (Clearing & Analytics)

Після очищення та стандартизації масиву даних система запускає аналітичний двигун `report_engine.py` та фінансову логіку `finance_logic.py`, які виконують дві ключові задачі: розділення потоків даних та усунення «фінансового шуму».

#### 1. 📂 Структурування даних: Таблиці Доходів та Витрат
Для зручності аналізу та побудови звітів фінальна книга Excel розділяється на два незалежних хронологічних реєстри (листи), які працюють із суворо визначеними категоріями з `config.py`:

*   **🟢 Лист Доходів (Income Ledger)**: акумулює лише позитивні транзакції (Сума > 0). Сюди потрапляють 6 фіксованих категорій: *зарплата і виплати, бонуси та кешбек, поповнення готівкою, перекази з чужого рахунку, інші надходження* та технічна категорія *переказ з власного рахунку*.
*   **🔴 Лист Витрат (Expenses Ledger)**: містить усі операції списання (Сума < 0). Сюди входять 17 категорій витрат родини, згрупованих за типом (від регулярних *компослуг* та *продуктів* до технічного *зняття готівки* чи *переказів на власний рахунок*).

![Демонстрація розподілу датасету на два з прихідними і розхідними транзакціями](docs/Income.PNG)

![Демонстрація розподілу датасету на два з прихідними і розхідними транзакціями](docs/Expences.PNG)

#### 2. 🛡️ Трирівнева система автоматичних компенсацій (The Clearing Engine)
Найбільша інженерна цінність проекту — це математичне моделювання реального руху грошей. Щоб виписки з різних карт не викривляли статистику реальних витрат сімейного бюджету, система автоматично гасить зустрічні транзакції на трьох рівнях:

##### 👥 Рівень 1: Внутрішні перекази між власними рахунками (Twins Algorithm)
Коли гроші переказуються між банківськими рахунками що вже зафіксовані в системі, наприклад, з картки Сергія на картку Оленки, для банків це дві окремі операції: витрата в одному банку та дохід в іншому. Якщо врахувати їх «як є», обіг сімейного бюджету штучно роздується на цю суму.
*   **Як це вирішено**: Алгоритм "Twins" аналізує протилежні транзакції у короткому часовому вікні. Якщо знайдено збіг (наприклад, Оленка отримала суму, яку Сергій щойно відправив), система маркує ці транзакції технічними категоріями *переказ на власний рахунок* / *переказ з власного рахунку*, виключаючи їх із одрахунків чистих споживчих витрат.
*   **🛠️ Проблема банківських комісій**: Часто перекази супроводжуються комісією (наприклад, Сергій відправив `10 050.00` грн, а Оленка отримала рівно `10 000.00` грн). Наївний алгоритм не зв'яже ці транзакції через різницю в сумах. 
    *   *Наше рішення*: Система виявляє розбіжність, автоматично розчіплює транзакцію, відокремлює `50.00` грн комісії, записує її в статтю *інші витрати*, а решту `10 000.00` грн успішно лінкує як чистий внутрішній переказ. Баланс леджера залишається ідеальним.

| 📄 БУЛО: Витратна транзакція на суму 3065,25 і дохідна на суму 3050,00 (комісія 15,25) | 📊 СТАЛО: Витратна транзакція розділилася на 2: 3050,00 - сума переказу, 15,25 - комісія банку |
| :---: | :---: |
| ![Оригінальні транзакції](docs/Comission1.PNG) | ![Розчеплені транзакції](docs/Comission2.PNG) |
| *Оригінальні транзакції* | *Розчеплені транзакції (Зверніть увагу на ID)* |


### 3.2. Компенсація готівкових операцій (Cash Clearing & ATM-noise Reduction)

#### ❓ Бізнес-проблема
Зняття готівки в банкоматі та її подальше внесення через термінал на іншу картку не є реальними споживчими витратами чи доходами. Без спеціальної обробки ці операції створюють штучний транзитний оборот, роздуваючи показники доходів та витрат у фінансовій звітності.

#### ⚙️ Логіка роботи функції `process_cash_clearing`
Модуль `finance_logic.py` реалізує автоматичне взаємне гасіння готівкових потоків за правилом **Локального пріоритету (FIFO)**:

1. **Внутрішньомісячний FIFO-кліринг:** У межах кожного календарного місяця суми зняття та поповнення готівкою взаємно погашаються строго FIFO до ліміту.
2. **Міжмісячний транзит (до 10-го числа):** Якщо у місяці наявні невикористані поповнення (здійснені до 10-го числа включно), вони спрямовуються на компенсацію залишків зняття з попереднього місяця.
3. **Динамічне розщеплення на межі:** Транзакція, що потрапляє на межу компенсаційного ліміту, автоматично розщеплюється на два або більше окремих рядків зі спільним часом та ID.
4. **Перерозподіл некомпенсованих залишків:** Обсяги зняття понад ліміт перекатегоризовуються в *`інші витрати`*, а залишкові поповнення — в *`інші надходження`*.
5. **Принцип Raw Data First:** Усі маніпуляції виконуються «на льоту» під час формування аналітичного `df_analytical` для Daily Dashboard, залишаючи первинний реєстр `Total_Ledger.xlsx` 100% незмінним.

#### 📸 Візуальна демонстрація клірингу

| 📄 БУЛО: Сирі транзакції зняття/поповнення | 📊 СТАЛО: Результат після `process_cash_clearing` |
| :---: | :---: |
| ![Cash Clearing Before](docs/Cash1.PNG) | ![Cash Clearing After](docs/Cash2.PNG) |
| *Транзакція зняття готівки на суму 16000,00* | *Розподіл цих коштів (16000,00) по прихідним транзакціям. Транзитний оборот погашено, залишкові суми ре-категоризовано* |


##### 🚀 Рівень 3: Транзитні операції та категорія "Інвестиції"
*   **Транзитні операції**: Логіка відстежує цільове переміщення коштів через транзитні рахунки (наприклад, депозити, накопичувальні «банки» або тимчасові сейфи).
*   **Логіка «Інвестицій»**: Будь-який великий вихідний транзитний потік (наприклад, купівля валюти, переказ на брокерський рахунок чи купівля облігацій) система не вважає повсякденною витратою (як-от купівля їжі чи одягу). Такі транзакції проходять через спеціальний фільтр і примусово класифікуються як **`інвестиції`** (активи). Це дозволяє зберегти правильний показник щомісячного споживання (Burn Rate) та обчислювати реальний Net Worth сімейного капіталу.

---

### 📊 Модуль Аналітики та Візуальний Дашборд (`report_engine.py`)

Модуль щоденної аналітики трансформує консолідований масив транзакцій у наочний щоденний управлінський звіт за структурою класичного фінансового леджера. Результатом роботи є інтерактивна вкладка **Daily_Dashboard** у фінальному файлі `Total_Ledger.xlsx`.

#### 1. Структура Daily Dashboard
Таблиця щоденної аналітики автоматично агрегує фінансові потоки у розрізі календарних днів та порівнює фактичні витрати із плановими щоденними лімітами. Вона складається з 8 ключових колонок:
1.  **Місяць** — календарний місяць та рік (наприклад, Березень 2026).
2.  **Дата** — конкретний день у форматі DD.MM.YYYY.
3.  **План** — щоденний бюджетний ліміт, виділений на родину на цей день.
4.  **Витрати** — сумарні фактичні витрати за день (від'ємне значення або `0.00`).
5.  **Дохід** — сумарні фактичні надходження коштів за день.
6.  **Різниця за день** — чистий фінансовий результат дня відносно ліміту.
7.  **Різниця за місяць** — накопичувальний баланс економії чи перевитрат у межах поточного місяця.
8.  **Різниця загалом** — глобальна динаміка чистих активів (Net Worth) з урахуванням початкового балансу.

#### 2. Математичний апарат розрахунків
Для кожного календарного дня система виконує обчислення за такими математичними формулами:
*   **Різниця за день (Daily Budget Variance)**:
    $$\text{Різниця за день} = \text{План} + \text{Витрати} + \text{Дохід}$$
    *(Оскільки витрати мають від'ємний знак у DataFrame, сума автоматично вираховує різницю)*.
*   **Різниця за місяць (Monthly Cumulative Balance)**:
    Накопичувальний підсумок різниць за день у межах календарного місяця. Першого числа кожного місяця цей показник обнуляється, показуючи проміжний баланс сімейного бюджету на будь-який день:
    $$\text{Різниця за місяць}_{d} = \sum_{i=1}^{d} \text{Різниця за день}_{i}$$
*   **Різниця загалом (Net Worth / Cumulative Asset Balance)**:
    Наскрізний накопичувальний підсумок від самого початку ведення леджера, що показує реальний обсяг власних накопичень родини у реальному часі з урахуванням кредитних лімітів:
    $$\text{Різниця загалом}_{t} = \text{Початковий баланс} + \sum_{i=1}^{t} \text{Різниця за день}_{i}$$

#### 3. Групування деталей та Професійна стилізація (openpyxl)
*   **Рядки проміжних підсумків**: Після останнього дня кожного місяця система автоматично вставляє підсумковий рядок **"РАЗОМ за [Місяць YYYY]"**. У ньому колонки *План, Витрати* та *Дохід* сумуються, а *Різниця за місяць* та *Різниця загалом* фіксують фінальний стан на кінець місяця.
*   **Групування детальних рядків**: Для максимальної читабельності всі детальні транзакції дня приховані під кнопками групування Excel **"+"** прямо всередині відповідного календарного дня.
*   **Динамічна висота та автоперенесення**: Для описів детальних транзакцій увімкнено автоперенесення тексту (`wrap_text=True`), а висота рядка адаптується автоматично під об'єм тексту, запобігаючи обрізанню довгих назв операцій.
*   **Візуальний стиль**: Заголовки мають дворівневу структуру, підсумкові рядки виділяються жирним шрифтом та кольоровою заливкою, а колонки автоматично підбирають свою ширину за довжиною значень. Таблиця повністю оптимізована під горизонтальний альбомний друк (Landscape).

![Демонстрація Дашборду з проміжними результатами по місяцям](docs/dashboard.PNG)

---

### 📈 Модуль Візуалізації та Інтерактивний Дашборд (`output/Dashboard.xlsx`)

Для наочного аналізу фінансових потоків реалізовано двофайлову архітектуру (**Decoupled Data & Presentation Layer**). Це розділяє автоматичну обробку даних Python та візуальну аналітику в Excel, забезпечуючи 100% збереження оформлення, кастомних зведених таблиць та слайсерів.

#### 🏗 Архітектура рішення:
1. **`output/Total_Ledger.xlsx` (Data Layer)** — локальна база даних (Data Lake / Marts), яка автоматично генерується та оновлюється Python-скриптом.
2. **`output/Dashboard.xlsx` (Presentation Layer)** — інтерактивний управлінський дашборд, що містить аналітичні панелі, графіки та зрізи.

#### 📊 Ключовий функціонал дашборду:
* **Картки показників (KPI Cards)**: фіксують ключові фінансові метрики (загальний дохід, витрати та поточний профіцит/дефіцит).
![Демонстрація візуалізацій](docs/Cards.PNG)
* **Динамічні зрізи (Slicers)**: інтерактивна фільтрація всіх графіків та карт за вибраними місяцями в один клік.
* **Ієрархічні діаграми (Drill-Down PivotCharts)**: дворічне групування дат (`Місяць` ➡️ `Дата`), що дозволяє переключатися між загальним місячним трендом та деталізацією по днях.

* **Пряме джерело даних (PivotTable External Data Source)**: зведені таблиці в `Dashboard.xlsx` прив'язані безпосередньо до колоночних діапазонів файлу `Total_Ledger.xlsx`. Завдяки цьому нові транзакції, оброблені Python, підтягуються на дашборд простою кнопкою **«Оновити все» (Data -> Refresh All)**.

![Демонстрація візуалізацій](docs/income_expenses_analysis.PNG)

![Демонстрація візуалізацій](docs/financial_condition.PNG)

![Демонстрація візуалізацій](docs/report_expenses_categories.PNG)

---

### 💼 Deliverables & Customization (Результати роботи)

Цей проект є повністю готовим і гнучким інженерним шаблоном сімейного або мікробізнес-офісу для консолідації та аналізу фінансових потоків.

#### Що отримує замовник як кінцевий результат (Deliverables):
1.  **🧼 Бездоганно чисті дані**: Повністю дедуплікований, хронологічно структурований та лінгвістично очищений реєстр усіх транзакцій у форматі Excel.
2.  **📊 Готову управлінську звітність**: Автоматично згенерований `Daily_Dashboard` із деталізацією, проміжними підсумками за місяць та розрахунком Net Worth.
3.  **🛡️ Безпеку даних**: Інструмент працює виключно локально — жоден байт ваших фінансових чи персональних даних не передається у хмару чи стороннім сервісам.

#### 🔧 Можливості кастомізації (Customization):
Система спроектована за принципами модульної архітектури, що дозволяє легко адаптувати її під індивідуальні вимоги.
*   **Інтеграція нових банків**: Швидке підключення виписок будь-яких фінансових установ світу (потрібно лише створити новий парсер на базі наявного `BaseParser`).
*   **Індивідуальна сітка категорій**: Повна кастомізація під структуру вашого особистого бюджету чи витрат бізнесу.
*   **Зміна бізнес-правил**: Гнучке налаштування алгоритму компенсацій близнюків, кредитних лімітів та лімітів щоденних витрат.

---

### 📞 Let's Connect! / Заклик до співпраці

Шукаєте надійне та автоматизоване рішення для аналізу ваших фінансів, очищення брудних даних або автоматизації бізнес-звітів в Excel? Я готовий допомогти вам реалізувати проект будь-якої складності!

*   **💻 Upwork Profile:** [Замовити розробку на Upwork](https://upwork.com/freelancers/your-profile)
*   **🤝 LinkedIn:** [Зв'язатися в LinkedIn]
*   **📧 Email:** [sid78rivne@gmail.com]
*   **🐙 GitHub:** [https://github.com/Serhii-Sid].
