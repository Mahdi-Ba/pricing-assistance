# Business Questions: Pricing Assistant MVP

Source: `pricing-assistant.html` (دستیار کارشناس قیمت‌گذاری سخت‌افزار, v1.0, 2026-10-18)
Change: `add-pricing-assistant-mvp`

## How to use this file

Every question below has a **default assumption**, and the current proposal, specs, design and tasks already use it. Please write your answer under **Answer**. If an answer differs from the default, the column **If different** shows how much would change:

- **Config**: only a setting changes; the plan stays the same.
- **Design**: the technical approach changes; specs stay the same.
- **Spec**: the required system behaviour changes; specs and tasks will be updated.

Questions marked **[Blocking]** must be answered before phase A (proof of data access) can start.

---

## 1. Product scope and users

### Q-B1. Who is this product for?
Is this a one-off build for one hardware retailer, or a product that will serve several retailers (multi-tenant SaaS)?
- **Default**: A multi-tenant product. The pilot has one retailer (one tenant). Data isolation per tenant is built in from day one.
- **If different**: Design (simpler if single-customer; billing and onboarding flows if SaaS).
- **Answer**: محصول را به‌صورت SaaS چندمشتری طراحی می‌کنیم؛ پایلوت فقط با یک فروشگاه شروع می‌شود. جداسازی داده‌ها، دسترسی‌ها و تنظیمات قیمت‌گذاریِ هر مستأجر از روز اول الزامی است. **وضعیت: تصمیم پیشنهادی برای MVP.**

### Q-B2. Who are the users, and who confirms uncertain product matches? [Blocking]
The PRD lists "who is responsible for confirming matches" as an open item. How many pricing experts and admins will use the pilot? Should experts confirm matches themselves, or a separate person (for example a category manager)?
- **Default**: 1–5 users. Two roles: `admin` (store manager) and `expert`. Experts confirm matches and decide prices.
- **If different**: Spec (a separate "match reviewer" role, or a four-eyes rule on match confirmation).
- **Answer**: پایلوت با ۱ تا ۵ کاربر و دو نقش `admin` (مدیر فروشگاه) و `expert` (کارشناس قیمت‌گذاری) اجرا شود. کارشناس تطبیق‌های نامطمئن را با مشاهده مشخصات و شواهد تأیید/رد می‌کند؛ مدیر به‌صورت نمونه‌ای کیفیت تطبیق‌ها را ممیزی می‌کند. نقش مستقل بازبین تطبیق فعلاً لازم نیست. **نیاز به تأیید: تعداد واقعی کاربران و معرفی مسئول در فروشگاه.**

### Q-B3. Does a manager need to approve price decisions?
For example: must decreases larger than X% or below a certain margin be approved by a manager before the expert changes the price in the store?
- **Default**: No. One expert decides and records the decision. Only a manual price **below the floor** needs an explicit override with a reason.
- **If different**: Spec (an approval step in `pricing-decisions`).
- **Answer**: برای تغییر قیمت عادی، تأیید دوم لازم نیست؛ تصمیم، دلیل و هویت کارشناس ثبت می‌شود و اعمال قیمت در فروشگاه در MVP دستی است. قیمت پایین‌تر از کف محاسبه‌شده خودکار پیشنهاد نمی‌شود. اگر فروشگاه بخواهد استثنا بدهد، بهتر است مجوز `admin` و دلیل آن ثبت شود؛ این یک **پیشنهاد تکمیلیِ نیازمند تغییر Spec** نسبت به پیش‌فرض فایل است.

### Q-B4. Notifications
Should experts receive alerts outside the app (Telegram, SMS, email) for urgent items, for example floor conflicts on tier-A products or a source going down?
- **Default**: No. In-app queue and summary cards only.
- **If different**: Spec (new notification capability).
- **Answer**: در MVP فقط صف اولویت‌بندی‌شده، کارت‌های خلاصه و نشان هشدار داخل برنامه داریم. پیامک، ایمیل و تلگرام به فاز بعد موکول شوند؛ خرابی منبع و تعارض با کف قیمت در صف به‌وضوح دیده شوند. **وضعیت: تصمیم پیشنهادی.**

### Q-B5. UI language
- **Default**: Persian only, RTL, Jalali dates, amounts in Toman.
- **If different**: Design (i18n framework for an English/German admin UI).
- **Answer**: فارسی، راست‌به‌چپ، تاریخ جلالی و نمایش مبلغ به تومان؛ نمایش مقادیر با جداکننده سه‌رقمی و برچسب صریح واحد. فعلاً چندزبانه‌بودن جزو دامنه نیست. **وضعیت: تصمیم پیشنهادی.**

---

## 2. Data sources and legal

### Q-L1. Legal permission for page extraction [Blocking]
Collecting prices from Digikala and specialist shop pages (path B in the PRD) may conflict with their terms of use. Who checks this and takes responsibility? Is written clearance needed per source before we turn it on?
- **Default**: The customer confirms permission per source. The source registry records who approved it, when and with what reference. A source cannot be set to `approved` without this record.
- **If different**: Spec (extra fields and rules in the source registry) or scope (some sources dropped).
- **Answer**: مسئول دریافت و تأیید مجوز هر منبع، مالک کسب‌وکار/مشتری با همکاری مسئول حقوقی است. در رجیستریِ منابع باید نام تأییدکننده، تاریخ، دامنه مجوز، مستند یا ارجاع و محدودیت تعداد درخواست ثبت شود. تا زمان احراز مجوز، جمع‌آوری خودکار آن منبع فعال نمی‌شود؛ ممنوعیت یا مسدودسازی را دور نمی‌زنیم. **نیاز به اقدام پیش از فاز A: تأیید منبع‌به‌منبع.**

### Q-S1. Which specialist online shops? [Blocking]
The PRD says 2–3 specialist shops are still to be chosen. Please list candidates (name and website). Also: for each shop, do we compare against the shop itself, or also against sellers listed inside it?
- **Default**: None yet. The qualification run evaluates whatever candidates you list.
- **If different**: Config.
- **Answer**: دو نامزد اولیه برای دسته قطعات کامپیوتر و سخت‌افزار: **لیون کامپیوتر** (`https://www.lioncomputer.com`) و **مقداد آی‌تی** (`https://meghdadit.com`). در هر دو فقط پیشنهاد فروش خود فروشگاه مبنای مقایسه است، نه فروشندگان ثالث. انتخاب نهایی وابسته به همپوشانی با کاتالوگ مشتری، مجوز دسترسی، موجودی و پایداری استخراج در فاز A است. **وضعیت: نامزد پیشنهادی، نه منبع تأییدشده.**

### Q-S2. Torob [Blocking]
1. Does the store already have a Torob Shop API account and credentials?
2. Torob's Shop API documents data for **our own shop**. Should Torob also be used to see **competitor** prices, for example by reading Torob product pages? (This raises the legal question in Q-L1 again.)
3. Should we watch our own listing on Torob to confirm the price change appeared there (PRD R07: "reflected in comparison channel")?
- **Default**: (1) unknown; (2) yes, Torob product pages are a candidate competitor source, subject to Q-L1; (3) yes.
- **If different**: Config or scope.
- **Answer**: ۱) وجود حساب و دسترسی فروشگاه به پنل/API ترب هنوز معلوم نیست و مدیر فروشگاه باید بررسی کند؛ هیچ اعتبارنامه‌ای را موجود فرض نمی‌کنیم. ۲) اطلاعات فروشگاه خودمان از اتصال رسمی/مجاز دریافت شود. صفحه‌های محصول ترب برای مشاهده قیمت رقبا فقط در صورت تأیید حقوقی و فنی منبع به‌عنوان گزینه فاز A بررسی می‌شوند؛ API فروشگاه خودمان را API عمومی رقبا فرض نمی‌کنیم. ۳) بله، بعد از تغییر دستی قیمت، نمایش قیمت جدید خودمان در ترب پایش شود و تأخیر آن جدا از تأخیر سایت خودمان گزارش شود. **نیاز به تأیید: دسترسی واقعی، مجوز و سازوکار پایش.**

### Q-S3. Digikala
Does the store sell on Digikala, and does it have seller-panel API access? Does any official or contractual data access to competitor prices exist?
- **Default**: No official access. Digikala is evaluated as a page-extraction candidate (path B).
- **If different**: Design (API connector instead of page extraction).
- **Answer**: فروش در دیجی‌کالا و دسترسی پنل فروشندگی هنوز نامعلوم است و باید از مشتری پرسیده شود. تا زمان اثبات دسترسی قراردادی/رسمی، روی API رقبا حساب نمی‌کنیم. مشاهده صفحات عمومی صرفاً نامزد ارزیابی فنی و حقوقی فاز A است؛ اگر مجوز فراهم نشود، منبع دیجی‌کالا از جمع‌آوری خودکار کنار گذاشته می‌شود. **وضعیت: وابسته به مشتری.**

### Q-S4. Which competitors count?
On marketplaces (Digikala, Torob) many sellers offer the same product. Should the market price use **all sellers**, only a **selected list of competitors**, or exclude sellers with a low rating or new accounts?
- **Default**: The admin selects allowed sellers per source and category. If no selection is made, all sellers on approved sources count.
- **If different**: Spec (seller-quality filters).
- **Answer**: مدیر بتواند برای هر دسته/منبع فهرست فروشندگان مجاز را تنظیم کند. در نبود فهرست، همه پیشنهادهای **منابع تأییدشده** فقط پس از احراز یکسان‌بودن مدل، وضعیت نو، گارانتی، روش پرداخت، موجودی و تازگی قابل نمایش‌اند؛ پیشنهادهای مشکوک/پرت به تأیید دستی نیاز دارند و نباید به‌تنهایی کمینه بازار را جابه‌جا کنند. افزودن امتیاز/سابقه فروشنده به فیلتر قطعی را پس از دسترسی به داده معتبر بررسی می‌کنیم. **وضعیت: پیشنهاد با کنترل کیفیت.**

### Q-S5. How fresh must prices be?
The PRD treats "every 5–15 minutes for priority products" as an experiment, not a commitment. What freshness does the business actually need, per product importance?
- **Default**: Tier A every 15 min, tier B every 60 min, tier C every 6 h. Data older than 2 h (tier A) cannot support a recommendation.
- **If different**: Config, unless sub-minute freshness is required (that would be a design change).
- **Answer**: هدف آزمایشی: سطح A هر ۱۵ دقیقه، B هر ۶۰ دقیقه و C هر ۶ ساعت؛ این‌ها SLA قطعی نیستند و به مجوز و محدودیت منبع وابسته‌اند. داده سطح A با عمر بیش از ۲ ساعت به‌تنهایی مبنای پیشنهاد تغییر قیمت قرار نگیرد؛ برای سایر سطوح آستانه جداگانه تنظیم شود. زمان آخرین مشاهده و وضعیت «کهنه» باید دیده شود. **وضعیت: تنظیم اولیه قابل اصلاح پس از فاز A.**

### Q-S6. May the AI (LLM) help collect prices from websites?
The PRD names an HTML parser, structured page data and Playwright for collecting data (sections ۰۴ and ۰۶). It gives the AI a "limited and clear role" with three tasks: reading attributes from titles, suggesting matches and writing explanations. Reading prices from pages is not one of them. The PRD does not explicitly forbid it either. Which of these should the AI be allowed to do? (Several can be chosen.)

| Option | What the AI does | Risk |
|---|---|---|
| **A. Suggest extraction rules** | When a source is set up, or a site's layout changes, the AI reads sample pages and suggests the rules for finding price and stock. An admin approves them, and normal rule-based extraction then runs. | Low: the AI never touches live prices |
| **B. Find competitor product pages** | The AI searches a competitor site for the page selling our product and suggests links to track. An expert confirms each link. | Low to medium: the result is only a suggestion |
| **C. Read prices when the rules fail** | When rule-based extraction fails, the AI reads price and stock from the page text. | High: a wrong or manipulated price could reach a recommendation |

If C is chosen, these safeguards apply:
- An AI-read price is marked "unverified".
- The number must appear in the page text, and must be within a plausible range of the last known price.
- An AI-read price alone can never justify a suggested price change. The expert must confirm it, or a rule-based reading must agree with it.

- **Default**: None. All price collection uses rules only. The AI is used only for the three tasks the PRD lists, and only after Q-T2 is cleared.
- **Recommendation**: A and B. Add C only for a source that phase A shows cannot be read reliably with rules.
- **If different**: Spec (`llm-assistance` and `market-data-collection`; tasks added in groups 4, 6 and 8). Depends on Q-T2 (AI provider and compliance).
- **Answer**: گزینه‌های **A و B** را فقط به‌صورت کمکی و با تأیید انسانی مجاز می‌دانیم: پیشنهاد قواعد استخراج از نمونه‌صفحه و پیشنهاد URL تطبیق‌یافته محصول. گزینه **C در MVP غیرفعال** بماند. دریافت قیمت و موجودیِ عملیاتی باید قاعده‌محور و قابل بازبینی باشد؛ متن تولیدشده توسط مدل هرگز به‌تنهایی قیمت یا تطبیق قطعی ایجاد نکند. A/B نیز تنها پس از تأیید Q-T2 فعال شوند. **وضعیت: پیشنهاد تغییر Spec نسبت به پیش‌فرض بدون LLM.**

---

## 3. Catalog, cost and confidentiality

### Q-D1. Current store platform [Blocking]
Which platform runs the store today (WooCommerce, a custom system, an Iranian store builder such as Portal/Mihanstore, a marketplace seller panel, …)? Does it have a **read-only** API for products, stock and prices?
- **Default**: MVP imports catalog data from CSV/XLSX files. A read-only platform connector is a later addition. Our own live price is read from our storefront pages.
- **If different**: Design and tasks (add a read-only store connector in MVP).
- **Answer**: پلتفرم واقعی فروشگاه هنوز مشخص نیست؛ در پایلوت دریافت کاتالوگ، موجودی، قیمت فعلی و شناسه کالا با CSV/XLSX کافی است و قیمت منتشرشده از صفحه عمومی خود فروشگاه راستی‌آزمایی می‌شود. اتصال API فقط پس از معرفی پلتفرم و تأیید دسترسی read-only اضافه شود. **نیاز به پاسخ مشتری: نام پلتفرم، نمونه خروجی فایل و دسترسی‌ها.**

### Q-D2. What is "effective cost"? [Blocking]
The PRD says effective cost = purchase price + business-defined costs. Which costs exactly?
- **Fixed per unit**: shipping, customs, warehousing, packaging, overhead allocation?
- **Percentage of selling price**: marketplace commission, payment gateway fee, tax/VAT?
- Are the prices we compare **including VAT**?
- **Default**: Fixed components and percentage fees are admin-configured lists. All compared prices are final consumer prices including VAT.
- **If different**: Config, unless costs vary per order (that would be a spec change).
- **Answer**: «بهای تمام‌شده مؤثر هر واحد» = قیمت خرید + حمل/بیمه/ترخیص و گمرکِ تخصیص‌یافته + انبارش/بسته‌بندی و هزینه ثابت قابل‌انتساب؛ کارمزد مارکت‌پلیس، پرداخت و سایر هزینه‌های وابسته به مبلغ فروش، جداگانه به‌صورت درصدی وارد فرمول کف می‌شوند تا دوباره‌شماری رخ ندهد. قیمت رقیب و قیمت پیشنهادی در یک مبنای واحد، ترجیحاً مبلغ نهایی پرداخت مشتری با مالیات، مقایسه شوند. مالیات قابل‌استرداد نباید هزینه واقعی تلقی شود و فرمول سود/کف باید با وضعیت مالیاتی فروشگاه تطبیق داده شود. **نیاز به تأیید: اقلام واقعی هزینه، نرخ‌ها و نحوه حسابداری VAT.**

### Q-D3. Confidentiality and data location [Blocking]
Purchase costs and margins are sensitive.
1. Where may this data be stored (country, cloud provider, on-premises)?
2. How long must we keep page evidence (HTML or screenshots) and price history?
- **Default**: (1) Stored only inside the deployment's own database, never sent to external services such as the LLM. (2) Page evidence 90 days, price history indefinitely.
- **If different**: Design (hosting) or Config (retention).
- **Answer**: بهای خرید، سود و حاشیه سود فقط در پایگاه داده اختصاصی استقرار نگهداری شود و به مدل زبانی یا سرویس بیرونی ارسال نشود. مکان نهایی استقرار (ایران/سرور مشتری/زیرساخت مجاز بهره‌بردار) پس از بررسی محرمانگی و دسترسی شبکه تصویب شود. شواهد صفحه ۹۰ روز و تاریخچه قیمت دست‌کم در طول پایلوت و پس از آن طبق سیاست نگهداری مشتری باقی بماند؛ پیش‌فرض محصول تاریخچه قیمت نامحدود است، با امکان اعمال محدودیت/حذف دوره‌ای. **نیاز به تأیید: محل داده و دوره نگهداری.**

### Q-D4. Product identifiers
Does your catalog include manufacturer part numbers (MPN) or barcodes (EAN/GTIN) for most products?
- **Default**: Only for some products. Matching is automatic only when the identifier and all conditions are identical; everything else needs expert confirmation.
- **If different**: Config (higher automatic match rate if identifiers are common).
- **Answer**: وجود MPN/EAN/GTIN برای همه کالاها را فرض نمی‌کنیم. تطبیق خودکار فقط با شناسه معتبر و برابری کامل ویژگی‌های مهم (مدل، پارت‌نامبر، ظرفیت، رنگ/نسخه، گارانتی و وضعیت) انجام شود؛ موارد دیگر در صف تأیید کارشناس بمانند. **وضعیت: تصمیم پیشنهادی؛ کیفیت شناسه‌ها با نمونه کاتالوگ سنجیده شود.**

### Q-D5. Currency in your data
Are prices and costs in your files and systems in Toman or Rial?
- **Default**: Toman. Everything is stored internally in Rial and shown in Toman.
- **If different**: Config.
- **Answer**: نمایش برای کارشناس به تومان و ذخیره داخلی به ریال؛ در هر ورودی فایل، واحد پول صریح و تبدیل کنترل‌شده باشد تا خطای ده‌برابری رخ ندهد. واحد فایل‌های واقعی مشتری هنوز باید تأیید شود. **وضعیت: تنظیم پیشنهادی.**

### Q-D6. How often do costs change?
How often are purchase costs updated (each purchase, daily, weekly)? Who uploads them?
- **Default**: The admin uploads a file when costs change, at most daily.
- **If different**: Design (scheduled import or platform connector).
- **Answer**: مدیر فروشگاه هنگام تغییر قیمت خرید، فایل جدید را بارگذاری می‌کند؛ در MVP حداکثر روزانه یک بار کافی است، اما هر تغییر پرریسک باید قبل از پیشنهاد جدید لحاظ شود. تاریخ و مسئول آپلود، نسخه فایل و هزینه قبلی ثبت شود. **نیاز به تأیید: چرخه واقعی تغییر قیمت خرید.**

---

## 4. Pricing rules

### Q-P1. What is "the market price"?
When several qualifying competitors sell the same product under the same conditions, which value is the reference?
- **Default**: The **lowest** price among confirmed, in-stock, fresh offers from the selected competitors. The median is shown alongside.
- **If different**: Spec (`price-recommendation`: market reference rule).
- **Answer**: مرجع عملیاتی، کمترین قیمت از میان پیشنهادهای **تأییدشده، موجود، تازه و از نظر شرایط فروش معادل** است؛ میانه قیمت‌های معتبر نیز برای تشخیص بازار و قیمت‌های پرت نمایش داده شود. اگر پیشنهاد معتبر کافی وجود ندارد، سیستم «داده ناکافی» اعلام کند و توصیه قطعی صادر نکند. **وضعیت: تصمیم پیشنهادی.**

### Q-P2. Pricing strategy [Blocking]
The PRD demo suggests 8,550,000 Toman against a market price of 8,600,000, which is a 50,000 Toman undercut.
1. Should we **undercut** by a fixed amount, **match** the market, or undercut by a percentage?
2. When we are **cheaper** than the market by more than the tolerance, should the system suggest an **increase** up to just below the market?
3. What tolerance counts as "close enough" to hold the price?
- **Default**: (1) Fixed undercut amount, configurable per category (default 50,000 Toman). (2) Yes. (3) 1%.
- **If different**: Config for different values; Spec for a different strategy type (for example "follow competitor X").
- **Answer**: ۱) سیاست پایه، قیمت‌گذاری اندکی پایین‌تر از مرجع بازار با **مقدار ثابت قابل تنظیم به‌ازای دسته** است؛ مقدار شروع آزمایشی ۵۰٬۰۰۰ تومان. ۲) بله، اگر قیمت فعلی ما بیش از دامنه تحمل پایین‌تر از بازار باشد، افزایش تا اندکی پایین‌تر از مرجع هم پیشنهاد شود؛ فقط کارشناس تصمیم نهایی می‌گیرد. ۳) دامنه بی‌عملی پیش‌فرض ۱٪ است. همه پیشنهادها تابع کف سود و کنترل تازگی/تطبیق‌اند؛ مقادیر با داده پایلوت تنظیم شوند. **وضعیت: تنظیم اولیه، نه سیاست تأییدشده تجاری.**

### Q-P3. Minimum margin and the floor formula [Blocking]
1. Is 10% minimum margin (from the PRD example) real? Does it differ by category?
2. Please confirm the floor formula: **floor = effective cost ÷ (1 − min margin − percentage fees)**. Example: cost 90M, margin 10%, fee 5% → floor ≈ 105.9M.
3. Are there **maximum prices** (ceilings) for any products?
- **Default**: (1) 10% default with category overrides. (2) Formula as stated. (3) No ceiling unless configured.
- **If different**: Config, unless the formula changes (that would be a spec change).
- **Answer**: ۱) ۱۰٪ را **پیش‌فرض آزمایشی** بگذاریم، نه واقعیت تأییدشده؛ هر دسته می‌تواند حداقل سود متفاوت داشته باشد. ۲) فرمول `floor = effective cost / (1 - min margin - percentage fees)` با فرض یکسان‌بودن مبنای مالیاتِ صورت/مخرج، تعریف حاشیه سود نسبت به فروش و نبود هزینه/مالیات دیگری قابل قبول است (مثال ۹۰، ۱۰٪، ۵٪: حدود ۱۰۵٫۹ میلیون). برای قیمت نهاییِ شامل VAT و مالیات قابل تهاتر، مدل مالی باید پیش از فعال‌سازی با حسابداری فروشگاه بازبینی شود؛ ممکن است فرمول لازم باشد اصلاح شود. ۳) سقف قیمت پیش‌فرض نداریم، اما امکان تنظیم سقف به‌ازای کالا/دسته لازم است. **نیاز به تأیید تجاری/مالی پیش از فاز B.**

### Q-P4. Price rounding
Are there price-ending conventions (for example round to 10,000 Toman, or end in …۹۰۰۰)?
- **Default**: Round **up** to the nearest 10,000 Toman (rounding up never goes below the floor).
- **If different**: Config.
- **Answer**: قیمت پیشنهادی به نزدیک‌ترین مضرب ۱۰٬۰۰۰ تومان **به بالا** گرد شود، به شرطی که از کف پایین‌تر نرود. پس از گردکردن، فاصله از بازار و دامنه تحمل دوباره بررسی شود؛ اگر قیمت دیگر هدف رقابتی را محقق نمی‌کند، تعارض به کارشناس نمایش داده شود. **وضعیت: تنظیم پیشنهادی.**

### Q-P5. Instalment, used and open-box offers
Our products are assumed to be **new, cash, official warranty**. Should offers with a different warranty, used or open-box condition, or instalment payment be ignored, shown for information only, or compared under a separate condition group?
- **Default**: Shown as evidence, but not used as the market reference unless an expert confirms they are equivalent (as in the RTX 4060 demo case).
- **If different**: Spec (`product-matching` / `price-recommendation`).
- **Answer**: مبنای قیمت‌گذاری کالاهای نو، فروش نقدی و گارانتی رسمی/معادل است. اقساطی، کارکرده، جعبه‌باز یا دارای گارانتی/شرایط تحویل متفاوت صرفاً در بخش شواهد دیده شوند و وارد مرجع بازار نشوند؛ معادل‌سازی استثنایی تنها با تأیید مستند کارشناس. **وضعیت: تصمیم پیشنهادی.**

### Q-P6. Should our stock level affect the suggestion?
For example: do not suggest a decrease when we have very little stock left, or suggest a decrease when stock is high and selling slowly.
- **Default**: No. Stock is only displayed in MVP.
- **If different**: Spec (new recommendation rules; sales data needed).
- **Answer**: موجودی در MVP نمایش داده شود ولی مستقیماً قیمت پیشنهادی را تغییر ندهد؛ قواعد موجودی زیاد/کم‌فروش یا کمبود کالا نیازمند داده فروش و سیاست موجودی هستند و به فاز بعد منتقل می‌شوند. **وضعیت: تصمیم پیشنهادی.**

### Q-P7. "Estimated profit"
The PRD says recommendations come with "estimated profit". Is **per-unit profit** enough, or do you expect a total based on expected sales volume?
- **Default**: Per-unit profit at the current and the suggested price.
- **If different**: Spec (requires sales-volume data input).
- **Answer**: سود و حاشیه سود تخمینی **برای هر واحد** در قیمت فعلی و پیشنهادی کافی است. اثر سود کل بر مبنای حجم فروش، بدون داده تقاضا و نرخ تبدیل، در MVP نمایش داده نشود. **وضعیت: تصمیم پیشنهادی.**

---

## 5. Daily workflow

### Q-W1. Daily cycle
Is the "daily queue" a list that is built once each morning, or a live queue that updates continuously during the day?
- **Default**: A live queue, ordered by priority. The summary cards show the current state.
- **If different**: Design (snapshot job and daily reset).
- **Answer**: صف زنده و اولویت‌دار باشد؛ با تغییر قیمت بازار، خرابی منبع، کهنگی داده، تعارض کف و تأیید/رد کارشناس به‌روزرسانی شود. داشبورد وضعیت لحظه فعلی را نشان دهد و تاریخچه تصمیم‌ها جدا ذخیره شود. **وضعیت: تصمیم پیشنهادی.**

### Q-W2. Verification window
After an expert reports a manual price change, how long does it normally take to show up on our site and on Torob?
- **Default**: The item returns to the queue as "verification overdue" if it is not seen on our site within 2 h.
- **If different**: Config.
- **Answer**: اگر پس از ثبت «قیمت در فروشگاه تغییر کرد» تا **۲ ساعت** قیمت جدید در سایت خودمان دیده نشد، وضعیت «راستی‌آزمایی معوق» به صف برگردد. انتشار در ترب جداگانه پایش شود و تأخیر آن بدون دانستن زمان واقعی همگام‌سازی، خطای فروشگاه تلقی نشود. **نیاز به سنجش در فاز A: تأخیر واقعی سایت و ترب.**

### Q-W3. Manual re-check limits
How many on-demand re-checks per expert per day are reasonable?
- **Default**: 50 per expert per day, always limited further by each source's request quota.
- **If different**: Config.
- **Answer**: سقف اولیه ۵۰ بازبینی درخواستی به‌ازای هر کارشناس در روز؛ علاوه بر آن سقف منبع، فاصله حداقلی درخواست‌ها و مجوزهای قانونی رعایت شود. امکان تغییر سقف برای مدیر فراهم باشد. **وضعیت: تنظیم پیشنهادی.**

---

## 6. Hosting, AI provider and compliance

### Q-T1. Hosting location and network [Blocking]
Many Iranian websites restrict or slow down traffic from outside Iran, and connectivity can be unstable. Where will the system run (an EU OpenShift platform, an Iranian cloud provider, the customer's own servers)? Can the data collectors use servers with Iranian network access?
- **Default**: The application runs on Kubernetes/OpenShift. The data-collection workers can be deployed separately where they have reliable access to the target sites. The design allows this split.
- **If different**: Design (deployment topology).
- **Answer**: معماری از جداسازی برنامه مرکزی و workerهای جمع‌آوری داده پشتیبانی کند. اگر زیرساخت Kubernetes/OpenShift موجود است، از آن استفاده کنیم؛ اما استقرار worker فقط در مکانی که **دسترسی پایدار و مجاز** به منابع دارد انجام شود، بدون تلاش برای دورزدن محدودیت‌های دسترسی. محل دقیق و مسیر ارتباط امن worker با پایگاه داده باید پس از تست منابع در فاز A تصویب شود. **نیاز به تصمیم فنی/حقوقی: میزبان و شبکه.**

### Q-T2. AI (LLM) provider and compliance [Blocking]
The design uses an LLM only to read product titles, suggest matches and reword explanations. It never handles prices or costs.
1. Is using an external LLM provider (default: Anthropic Claude) acceptable for this customer and region, after the operator's legal/export-compliance review for an Iranian-market deployment?
2. If not, is a self-hosted open-weights model acceptable, or should the pilot run with **no LLM** (rules plus human confirmation only)?
- **Default**: The system works fully without an LLM. The LLM is enabled only after the compliance review clears a provider.
- **If different**: Design (which adapter ships first).
- **Answer**: استفاده از Claude یا هر ارائه‌دهنده بیرونی را از پیش مجاز فرض نمی‌کنیم. نخست بررسی حقوقی، شرایط ارائه خدمت، محل داده و محرمانگی انجام شود؛ **کل MVP باید بدون LLM** (استخراج قاعده‌محور + تأیید انسانی) قابل اجرا باشد. در صورت منع سرویس بیرونی، مدل خودمیزبان تنها پس از ارزیابی هزینه/امنیت و کیفیت اختیاری است. در هر حالت بهای خرید، حاشیه سود و قیمت‌های محرمانه به مدل ارسال نشوند. **نیاز به تأیید compliance پیش از فعال‌سازی AI.**

### Q-T3. Login and identity
Does the customer have an existing single sign-on (SSO) system we must integrate with?
- **Default**: No. We operate a Keycloak instance (OIDC) for the pilot users.
- **If different**: Config.
- **Answer**: فعلاً SSO موجود فرض نمی‌شود و ورود از طریق Keycloak/OIDC با نقش‌های `admin` و `expert` انجام شود؛ امکان اتصال به SSO سازمانی در آینده محفوظ بماند. **نیاز به تأیید: وجود هویت‌سنجی سازمانی در فروشگاه.**

### Q-T4. Running-cost budget
Is there a monthly budget for infrastructure, LLM usage and any data or proxy services?
- **Default**: No fixed number. The system reports cost per source and LLM spend so the budget can be set after phase A.
- **If different**: Config (budgets and limits).
- **Answer**: برای پایلوت سقف ماهانه قطعی اعلام نمی‌کنیم؛ در فاز A هزینه هر منبع، ترافیک/اجرای worker، ذخیره‌سازی و هر استفاده مجاز از LLM اندازه‌گیری و سقف مصرف تعیین شود. هیچ خدمت پولیِ استخراج/پروکسی بدون تصویب بودجه فعال نشود. **نیاز به تأیید: بودجه ماهانه مشتری.**

---

## 7. Success measurement

### Q-K1. Baseline review time [Blocking for the pilot KPI]
The target is "at least 50% less review time than today." How long does checking one product take today, and can we measure it for one week before go-live?
- **Default**: The admin runs a one-week time study before the pilot and enters the baseline (minutes per product) in the system.
- **If different**: Config.
- **Answer**: پیش از شروع پایلوت، یک هفته زمان‌سنجی واقعی انجام شود؛ برای هر محصول زمان جست‌وجوی رقبا، تطبیق، محاسبه و تصمیم ثبت گردد. شاخص مقایسه، میانه دقیقه به‌ازای هر بررسیِ کامل است؛ هدف آزمایشی حداقل **۵۰٪ کاهش زمان** در همان ترکیب دسته‌هاست. **نیاز به داده پایه واقعی.**

### Q-K2. Match accuracy audit
Who audits the sample of confirmed matches for the ≥98% target, how often, and how large should the sample be?
- **Default**: The store manager audits 200 confirmed matches per pilot month (or all of them if there are fewer).
- **If different**: Config.
- **Answer**: مدیر فروشگاه ماهانه **۲۰۰ تطبیق تأییدشده** یا همه موارد اگر کمترند را ممیزی کند؛ نمونه به تفکیک دسته/منبع و اطمینان مدل انتخاب شود تا صرفاً موارد آسان سنجیده نشوند. هدف آزمایشی دقت حداقل **۹۸٪** در نمونه ممیزی‌شده و بازخورد اصلاحی برای خطاهاست. **وضعیت: پروتکل پیشنهادی.**

### Q-K3. Pilot timeline and exit criteria
What are the expected dates for phase A and phase B? Which results decide whether phase C (team roles, better prioritization, possibly a price-apply integration) starts?
- **Default**: Phase A takes 1–2 weeks of qualification after deployment, and phase B takes 4–8 weeks. The exit decision is based on the four pilot KPIs in the PRD.
- **If different**: Plan only.
- **Answer**: فاز A: حدود **۱–۲ هفته پس از آماده‌شدن دسترسی‌ها** برای احراز مجوز، پایداری منابع، کیفیت تطبیق و تخمین هزینه؛ فاز B: **۴–۸ هفته** پایلوت با کارشناس انسانی. ورود به فاز C منوط به چهار KPI نهایی PRD و حداقل این دو نتیجه قابل‌اندازه‌گیری است: **کاهش ≥۵۰٪ زمان بررسی** و **دقت ≥۹۸٪ تطبیق ممیزی‌شده**. برای دو KPI دیگر، شاخص‌های پیشنهادی «پوشش و تازگی داده در کالاهای A» و «قابل‌اعتمادبودن اجرای پیشنهاد/راستی‌آزمایی قیمت» هستند؛ آستانه‌هایشان پس از A تعیین و با PRD اصلی تطبیق شوند. **هیچ اعمال خودکار قیمت قبل از احراز کیفیت و کنترل کف انجام نشود.**
