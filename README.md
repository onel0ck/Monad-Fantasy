# Fantasy Manager
Автоматизированный инструмент для управления аккаунтами Fantasy на Monad.

## Contacts
* Telegram Channel: [unluck_1l0ck](https://t.me/unluck_1l0ck)
* Telegram: @one_lock
* Twitter/X: [@1l0ck](https://x.com/1l0ck)

## Описание
Данный скрипт автоматизирует процессы авторизации и выполнения ежедневных заданий для множества аккаунтов Fantasy. Основные функции:
- Авторизация через приватный ключ
- Получение ежедневных наград (daily claim)
- Выполнение квеста "onboarding" для новых аккаунтов
- Автоматическая регистрация в турнирах (Bronze, Silver, Gold, Elite)

## Настройка
1. Создайте папки `data` и `logs`, если они не существуют.
2. Добавьте ваши приватные ключи и адреса в файл `data/keys_and_addresses.txt` в формате:
   ```
   privateKey:walletAddress
   ```
3. Добавьте прокси в файл `data/proxys.txt` (по одному на строку)
4. Настройте файл `data/config.json` согласно вашим требованиям

## Конфигурация
Основные параметры в `config.json`:
```json
{
    "app": {
        "threads": 10,              // Количество потоков
        "keys_file": "data/keys_and_addresses.txt",
        "proxy_file": "data/proxys.txt",
    },
    "capmonster": {
        "enabled": true,            // Включить capmonster для решения капчи
        "api_key": "your-api-key"   // Ваш API ключ Capmonster
    },
    "daily": {
        "enabled": true             // Включить получение ежедневных наград
    },
    "onboarding_quest": {
        "enabled": false,           // Если true, выполнит onboarding квест
        "id": "69e67d0a-0a08-4085-889f-58df15bdecb8"
    },
    "tournaments": {
        "enabled": true,            // Включить автоматическую регистрацию в турнирах
        "types": {
            "bronze": {
                "enabled": true,    // Включить регистрацию в бронзовом турнире
                "id": "a5a63d39-756f-4d6e-9796-0d9fc46b8d1f", // ID текущего турнира
                "max_stars": 18     // Максимальное количество звезд для турнира
            },
            "silver": {
                "enabled": true,
                "id": "",          // Укажите ID серебряного турнира
                "max_stars": 23
            },
            "gold": {
                "enabled": false,
                "id": "",          // Укажите ID золотого турнира
                "max_stars": 25
            },
            "elite": {
                "enabled": false,
                "id": "",          // Укажите ID элитного турнира
                "max_stars": 999
            }
        }
    }
}
```

Вот все "onboarding_quest":
```
"onboarding_quest": {
    "enabled": true,
    "ids": [
        "69e67d0a-0a08-4085-889f-58df15bdecb8",  // onboarding_signup - Регистрация
        "767636d2-2477-4d4a-9308-5c2d43a75e02",  // onboarding_profile - Заполнение профиля
        "7beb55de-8067-4680-b3ad-ac397b90a55c",  // onboarding_shop - Посещение магазина
        "96e6f5f9-e187-4488-b8ee-61c412f7fa4b",  // onboarding_competition - Просмотр соревнований
        "66387328-ff2a-46a9-acb7-846b466934b6",  // onboarding_pack_opening - Открытие пака
        "9c261493-d21f-4c0f-b182-7a8a3c3ccb1f",  // onboarding_deck - Создание колоды
        "2a6ce72f-6352-487c-aa8b-29ba2d150259",  // onboarding_deposit - Депозит
        "3681ad25-0130-4573-9235-1a658b3af60e",  // onboarding_wheel_share - Поделиться колесом
        "4122dd9a-dc8f-4fab-970e-6de099673ab4",  // onboarding_free_tactic - Бесплатная тактика
        "535272d6-fbca-44c2-abf3-2c7316dc8f4c",  // onboarding_tactic - Тактика
        "94484d32-aabf-47d0-a412-c5d0dfefeb44",  // onboarding_wheel_deposit - Депозит для колеса
        "94807dbb-24fe-4055-986d-efd6212d28d5",  // onboarding_share - Поделиться
        "db5afa98-90fe-4e9c-9034-3fe1cf72683a",  // onboarding_wheel_free_tactic - Бесплатная тактика через колесо
        "e2f80666-40fe-47a5-804a-35646407312a"   // onboarding_gift - Подарок
    ]
}
```
## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/fantasy-manager.git
cd fantasy-manager
```

2. Create virtual environment:
```bash
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux/Mac
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```
При запуске вы можете указать задержку перед началом в секундах.

## Отладка
В файле `utils.py` можно изменить значение `DEBUG_MODE = True` для получения подробных логов. По умолчанию режим отладки отключен для минимизации вывода.

## Функции
### Авторизация
Скрипт автоматически авторизуется через Privy используя SIWE (Sign-In With Ethereum). Для каждого аккаунта сохраняется токен и куки для повторного использования.

### Daily Claim
После успешной авторизации скрипт получает ежедневную награду. Если включено, эта функция будет вызываться для каждого аккаунта автоматически. В логах отображается:
- Текущая серия (streak)
- День в серии
- Тип и размер полученной награды

### Onboarding Quest
Если в `config.json` включена опция `onboarding_quest`, скрипт выполнит квест Onboarding для новых аккаунтов. Данный квест выполняется один раз для каждого аккаунта.

### Регистрация в турнирах
Модуль регистрации в турнирах позволяет автоматически участвовать в различных турнирах Fantasy Top. Функциональность включает:

- Автоматическое получение списка доступных карт на аккаунте
- Умный выбор оптимальных комбинаций 5 карт для каждого типа турнира
- Учет ограничений по звездам: Bronze (18), Silver (23), Gold (25), Elite (без ограничений)
- Алгоритм выбора наиболее ценных карт с учетом рейтинга и звезд
- Приоритезация распределения карт от элитных к бронзовым турнирам

Для использования регистрации в турнирах:
1. Включите опцию `tournaments.enabled` в config.json
2. Для каждого типа турнира, в котором хотите участвовать:
   - Установите `enabled` в `true`
   - Укажите актуальный ID турнира в поле `id`
   - ID турнира можно найти в URL на странице турнира или через отладчик сети браузера

**Важно**: ID турниров меняются для каждого нового турнира. Обязательно обновляйте ID в конфигурации перед запуском.

## Логи
Все операции логируются в терминале и в файле `logs/app.log`:
- SUCCESS: успешные операции (зеленый цвет)
- ERROR: ошибки (красный цвет) 
- INFO: информационные сообщения
- RATE LIMIT: ограничения по частоте запросов (желтый цвет)

Успешные аккаунты сохраняются в `logs/success_accounts.txt`.
Неудачные попытки записываются в `logs/failure_accounts.txt` для последующего повторения.
