# Group Late Bot — MVP

Легкий Telegram-бот (Stateless, без БД) для оповещения об опозданиях из Workpace API.

## Как работает
1. Бот не использует базу данных. Все данные о том, какие опоздания уже отправлены, хранятся в оперативной памяти (в `set` `sent_events_cache`).
2. На сервере должен работать cron/ping (например, через UptimeRobot), который каждые 5 минут стучится на `GET /jobs/poll-workpace?secret=...`.
3. Пинг не даёт приложению на Render уснуть (память не сбрасывается в течение дня).
4. Опоздания шлются в единый чат: `DEFAULT_TELEGRAM_CHAT_ID`.
5. Кнопка "Отбито" редактирует оригинальное сообщение (заменяя статус прямо в тексте), поэтому хранение стейта в базе не нужно.

## Деплой на Render
1. Создайте **Web Service** на Render (Free plan подходит).
2. Выберите этот репозиторий.
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. В разделе **Environment Variables** добавьте следующие переменные:

### ⚙️ Переменные окружения (Environment Variables)

| Переменная | Описание / Где взять | Пример значения |
| :--- | :--- | :--- |
| `PUBLIC_BASE_URL` | Базовый URL вашего развернутого приложения. После деплоя на Render вы получите ссылку. Скопируйте её **без слеша** на конце. | `https://my-late-bot.onrender.com` |
| `TELEGRAM_BOT_TOKEN` | Токен вашего бота. Зайдите в Telegram, напишите боту [@BotFather](https://t.me/BotFather), создайте нового бота (`/newbot`) и скопируйте выданный HTTP API Token. | `123456789:AABBccDDeeFFggHHiiJJ` |
| `DEFAULT_TELEGRAM_CHAT_ID` | ID чата или группы, куда бот будет присылать опоздания. <br><br>**Как получить:**<br>1. Добавьте бота в нужную группу.<br>2. Напишите в группе любую команду (например `/start`).<br>3. Перейдите по ссылке `https://api.telegram.org/bot<ВАШ_TELEGRAM_BOT_TOKEN>/getUpdates`<br>4. В ответе найдите `chat -> id` (если это группа, ID начинается с минуса). | `-100123456789` (группа) или `123456789` (личный чат) |
| `TELEGRAM_WEBHOOK_SECRET` | Секретный ключ для защиты вебхука от посторонних запросов. Просто придумайте случайный набор английских букв и цифр. | `my_super_secret_webhook_123` |
| `CRON_SECRET` | Секретный ключ для защиты endpoint'а проверки опозданий. Этот ключ вы будете вставлять в UptimeRobot. Придумайте любой случайный пароль. | `my_cron_secret_777` |
| `WORKPACE_LOGIN` | Логин (или email), с которым вы авторизуетесь в системе Workpace. | `admin@company.kz` |
| `WORKPACE_PASSWORD` | Ваш пароль от учетной записи Workpace. | `mYSecRetPass` |
| `WORKPACE_BASE_URL` | Базовый адрес API Workpace. Скорее всего, менять не нужно. | `https://api.workpace.kz` |
| `LATE_THRESHOLD_MINUTES` | С какого количества минут прихода считать это "опозданием"? Все, кто опоздал на 1 минуту и больше, будут отправлены в бот. | `1` |
| `TIMEZONE` | Ваш часовой пояс. Оставьте по умолчанию, если вы находитесь в Казахстане. | `Asia/Almaty` |

## Настройка UptimeRobot (Обязательно!)
Чтобы бот проверял опоздания, его нужно "дергать" каждые 5 минут.
1. Зарегистрируйтесь на [uptimerobot.com](https://uptimerobot.com).
2. Нажмите **Add New Monitor**.
3. **Monitor Type:** `HTTP(s)`
4. **URL (вставьте ссылку на свой Render и ваш CRON_SECRET):** `https://ВАШ_APP.onrender.com/jobs/poll-workpace?secret=ВАШ_CRON_SECRET`
5. **Monitoring Interval:** `5 minutes`
6. Сохраните.

Готово! Каждые 5 минут UptimeRobot будет запрашивать URL, бот пойдет в Workpace, проверит опоздания и пришлет в Telegram.
