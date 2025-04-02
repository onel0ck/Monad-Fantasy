# Fantasy Manager
Automated tool for managing Fantasy accounts on Monad.

## Contacts
* Telegram Channel: [unluck_1l0ck](https://t.me/unluck_1l0ck)
* Telegram: @one_lock
* Twitter/X: [@1l0ck](https://x.com/1l0ck)

## Description
This script automates the processes of authorization and performing daily tasks for multiple Fantasy accounts. Main features:
- Authorization via private key
- Daily rewards claim
- "Onboarding" quest completion for new accounts
- Automatic tournament registration (Bronze, Silver, Gold, Elite)
- Automatic tournament rewards checking and claiming
- Using fragments for roulette spins
- Analysis of account results and statistics

## Setup
1. Create `data` and `logs` folders if they don't exist.
2. Add your private keys and addresses to the `data/keys_and_addresses.txt` file in the format:
   ```
   privateKey:walletAddress
   ```
3. Add proxies to the `data/proxys.txt` file (one per line)
4. Configure the `data/config.json` file according to your requirements

## Configuration
The following settings in `config.json` are currently working:
```json
{
    "app": {
        "threads": 5,              // Number of threads
        "keys_file": "data/keys_and_addresses.txt",
        "proxy_file": "data/proxys.txt",
        "success_file": "logs/success_accounts.txt",
        "failure_file": "logs/failure_accounts.txt",
        "result_file": "logs/result.txt",
        "log_file": "logs/app.log",
        "min_balance": 0.01
    },
    "rpc": {
        "url": "wss://ethereum-rpc.publicnode.com"
    },
    "monad_rpc": {
        "url": "https://solitary-shy-tab.monad-testnet.quiknode.pro/7da7ff09b16913dfc6a9d78c9c36554b0c08fe31/"
    },
    "info_check": true,             // Collect account information in result.txt
    "capmonster": {
        "enabled": true,            // Enable capmonster for captcha solving
        "api_key": "your-api-key"   // Your Capmonster API key https://capmonster.cloud/
    },
    "2captcha": {
        "enabled": false,
        "api_key": "key"
    },
    "daily": {
        "enabled": true             // Enable daily rewards claiming
    },
    "onboarding_quest": {
        "enabled": true,            // If true, will complete onboarding quests
        "ids": [
            "69e67d0a-0a08-4085-889f-58df15bdecb8",  // onboarding_signup
            "767636d2-2477-4d4a-9308-5c2d43a75e02",  // onboarding_profile
            "7beb55de-8067-4680-b3ad-ac397b90a55c",  // onboarding_shop
            "96e6f5f9-e187-4488-b8ee-61c412f7fa4b",  // onboarding_competition
            "66387328-ff2a-46a9-acb7-846b466934b6",  // onboarding_pack_opening
            "9c261493-d21f-4c0f-b182-7a8a3c3ccb1f",  // onboarding_deck
            "2a6ce72f-6352-487c-aa8b-29ba2d150259",  // onboarding_deposit
            "3681ad25-0130-4573-9235-1a658b3af60e",  // onboarding_wheel_share
            "4122dd9a-dc8f-4fab-970e-6de099673ab4",  // onboarding_free_tactic
            "535272d6-fbca-44c2-abf3-2c7316dc8f4c",  // onboarding_tactic
            "94484d32-aabf-47d0-a412-c5d0dfefeb44",  // onboarding_wheel_deposit
            "94807dbb-24fe-4055-986d-efd6212d28d5",  // onboarding_share
            "db5afa98-90fe-4e9c-9034-3fe1cf72683a",  // onboarding_wheel_free_tactic
            "e2f80666-40fe-47a5-804a-35646407312a"   // onboarding_gift
        ]
    },
    "starter_cards": {
        "enabled": true,
        "wait_time_after_claim": 5
    },
    "tournaments": {
        "enabled": true,            // Enable automatic tournament registration
        "types": {
            "bronze": {
                "enabled": true,    // Enable Bronze tournament registration
                "id": "a5a63d39-756f-4d6e-9796-0d9fc46b8d1f", // Current tournament ID
                "max_stars": 18     // Maximum number of stars for the tournament
            },
            "silver": {
                "enabled": false,   // Disabled
                "id": "",          // Specify Silver tournament ID
                "max_stars": 23
            },
            "gold": {
                "enabled": false,
                "id": "",          // Specify Gold tournament ID
                "max_stars": 25
            },
            "elite": {
                "enabled": false,
                "id": "",          // Specify Elite tournament ID
                "max_stars": 999
            }
        }
    },
    "fragment_roulette": {
        "enabled": true,           // Enable fragment roulette
        "min_fragments": 50        // Minimum fragments required for spinning
    },
    "retry_failed_accounts": true
}
```

## New Features

### Tournament Rewards Checking and Claiming
The script now automatically checks for tournament rewards and claims them. This feature is enabled by default with `"info_check": true` and doesn't require additional settings.


### Results Analysis
A new script `analyze_results.py` has been added to the `logs` folder, which allows you to analyze account information from the `result.txt` file. The script provides the following statistics:

- Total number of accounts, cards, fantasy points, fragments
- Average values of various metrics across accounts
- Statistics on accounts with rewards and packs
- List of accounts with tournament rewards and pending packs
- Top 5 accounts by various metrics

To run the analysis:
```bash
cd logs
python analyze_results.py
```

## Improvements in Account Information
Additional information is now recorded in the `result.txt` file:

- `tournament_rewards` - tournament rewards that have been received
- `pending_packs` - packs that have been received but not claimed
- `packs` - packs received from spinning the roulette
- `active_tournaments` - information about active tournaments and decks

Example entry in `result.txt`:
```
0x6Be3866Cb9eca40849189bA709Db5C111239496C:stars=0:gold="0":portfolio_value=1069.7:number_of_cards=17:fantasy_points=3840:fragments=5:onboarding_done=False:whitelist_tickets=2:gliding_score=6507.37:rewards=0:tournament_rewards=Tournament2:FAN(40),FRAGMENT(70),WHITELIST_TICKET(2):pending_packs=PACK(1)
```

## Tournament Registration
The tournament registration module allows automatic participation in various Fantasy Top tournaments. The functionality includes:

- Automatic retrieval of available cards on the account
- Smart selection of optimal combinations of 5 cards for each tournament type
- Consideration of star limitations: Bronze (18), Silver (23), Gold (25), Elite (no limit)
- Algorithm for selecting the most valuable cards considering rating and stars
- Multiple deck registrations for one tournament if the account has enough cards

### Important tournament features:

1. **Selecting only one tournament type**:
   - You can enable only one tournament type at a time (Bronze, Silver, Gold, or Elite)
   - If multiple tournaments are enabled in the configuration, the script will automatically choose only the first one
   - It's recommended to explicitly enable only one desired tournament, setting `"enabled": false` for others

2. **Registering multiple decks**:
   - The script automatically determines how many complete decks can be created from available cards
   - The maximum possible number of decks will be created for each tournament type, taking into account star restrictions
   - Each deck must consist of 5 unique cards
   - One card cannot be used in multiple decks

3. **Updating tournament IDs**:
   - Tournament IDs change for each new tournament
   - Be sure to update the IDs in the configuration before running
   - Tournament ID can be found in the tournament page URL or through the browser network debugger

## Installation

1. Clone the repository:
```bash
git clone https://github.com/onel0ck/Monad-Fantasy
cd Monad-Fantasy
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

## Running
```bash
python run.py
```
When starting, you can specify a delay before starting in seconds.

## Debugging
In the `utils.py` file, you can change the value of `DEBUG_MODE = True` to get detailed logs. By default, debug mode is disabled to minimize output.

## Logs
All operations are logged in the terminal and in the `logs/app.log` file:
- SUCCESS: successful operations (green color)
- ERROR: errors (red color)
- INFO: informational messages
- RATE LIMIT: rate limiting (yellow color)

Successful accounts are saved in `logs/success_accounts.txt`.
Failed attempts are recorded in `logs/failure_accounts.txt` for subsequent retries.
