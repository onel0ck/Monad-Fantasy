import json
import os
from datetime import datetime
from colorama import Fore, init
from itertools import cycle
from time import sleep

init(autoreset=True)

DEBUG_MODE = True

def get_current_time():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def write_to_log_file(log_message: str):
    with open("logs/app.log", "a") as log_file:
        log_file.write(log_message + "\n")

def error_log(message: str):
    current_time = get_current_time()
    log_message = f">> ERROR | {current_time} | {message}"
    print(Fore.RED + log_message)
    write_to_log_file(log_message)

def debug_log(message: str):
    if DEBUG_MODE:
        current_time = get_current_time()
        log_message = f">> DEBUG | {current_time} | {message}"
        print(Fore.LIGHTBLACK_EX + log_message)
        write_to_log_file(log_message)

def success_log(message: str):
    current_time = get_current_time()
    log_message = f">> SUCCESS | {current_time} | {message}"
    print(Fore.GREEN + log_message)
    write_to_log_file(log_message)

def info_log(message: str):
    if not DEBUG_MODE and message.startswith('[DEBUG]'):
        return
        
    current_time = get_current_time()
    log_message = f">> INFO | {current_time} | {message}"
    print(Fore.LIGHTBLACK_EX + log_message)
    write_to_log_file(log_message)

def ensure_directories():
    directories = ['data', 'logs']
    for directory in directories:
        os.makedirs(directory, exist_ok=True)

def rate_limit_log(message: str):
    current_time = get_current_time()
    log_message = f">> RATE LIMIT | {current_time} | {message}"
    print(Fore.YELLOW + log_message)
    write_to_log_file(log_message)

def load_config():
    config_path = 'data/config.json'
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"Config file not found at {config_path}")

def read_proxies(proxy_file):
    proxies_dict = {}
    all_proxies = []
    
    with open(proxy_file, 'r') as f:
        for idx, line in enumerate(f.readlines(), 1):
            if line.strip():
                proxies_dict[idx] = line.strip()
                all_proxies.append(line.strip())
    
    return proxies_dict, all_proxies

def read_user_agents():
    return cycle(get_user_agents())

def read_accounts(file_path):
    unique_accounts = {}
    with open(file_path, 'r') as f:
        for line in f:
            if line.strip():
                try:
                    private_key, wallet_address = line.strip().split(':')
                    if wallet_address not in unique_accounts:
                        unique_accounts[wallet_address] = private_key
                except ValueError:
                    continue
                    
    return [(i, (private_key, address)) 
            for i, (address, private_key) 
            in enumerate(unique_accounts.items(), 1)]

def countdown_timer(seconds):
    for i in range(seconds, 0, -1):
        print(f"\r{Fore.YELLOW}Starting in: {i} seconds", end="")
        sleep(1)
    print(f"\r{Fore.GREEN}Starting now!" + " " * 20)

def validate_tournament_config(config):
    if not config.get('tournaments', {}).get('enabled', False):
        return config
    
    tournament_types = config['tournaments']['types']
    enabled_tournaments = []
    
    for t_type, t_config in tournament_types.items():
        if t_config.get('enabled', False) and t_config.get('id'):
            enabled_tournaments.append(t_type)
    
    if not enabled_tournaments:
        info_log("No active tournaments found in configuration")
        return config
    
    if len(enabled_tournaments) == 1:
        info_log(f"Active tournament: {enabled_tournaments[0].capitalize()}")
        return config
    
    primary_tournament = enabled_tournaments[0]
    info_log(f"Multiple tournaments enabled. Using only: {primary_tournament.capitalize()}")
    
    for t_type in enabled_tournaments[1:]:
        config['tournaments']['types'][t_type]['enabled'] = False
        info_log(f"Disabled tournament: {t_type.capitalize()}")
    
    return config


def get_platform(user_agent):
    low_ua = user_agent.lower()
    if "win" in low_ua:
        return '"Windows"'
    elif "mac" in low_ua:
        return '"macOS"'
    elif "linux" in low_ua:
        return '"Linux"'
    else:
        return '"Windows"'


def get_chrome_version(user_agent) -> str:
    return user_agent.split("Chrome/")[1].split(".")[0]


def get_sec_ch_ua(user_agent) -> str:
    chrome_version = get_chrome_version(user_agent)
    return f'"Not_A Brand";v="8", "Chromium";v="{chrome_version}", "Google Chrome";v="{chrome_version}"'


def get_user_agents():
    return [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36 Edg/134.0.0.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36 Edg/134.0.0.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    ]
