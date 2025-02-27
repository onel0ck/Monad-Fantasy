import concurrent.futures
import os
import sys
from time import sleep
from colorama import init, Fore
from src.utils import (
    load_config, 
    read_proxies, 
    read_accounts, 
    ensure_directories, 
    countdown_timer,
    read_user_agents,
    error_log,
    info_log
)
from src.main import FantasyProcessor

def print_banner():
    banner = f"""
{Fore.CYAN}██╗   ██╗███╗   ██╗██╗     ╔███████╗ ██████╗██╗  ██╗
{Fore.CYAN}██║   ██║████╗  ██║██║     ██║   ██║██╔════╝██║ ██╔╝
{Fore.CYAN}██║   ██║██╔██╗ ██║██║     ██║   ██║██║     █████╔╝ 
{Fore.CYAN}██║   ██║██║╚██╗██║██║     ██║   ██║██║     ██╔═██╗ 
{Fore.CYAN}╚██████╔╝██║ ╚████║███████╗╚██████╔╝╚██████╗██║  ██╗
{Fore.CYAN} ╚═════╝ ╚═╝  ╚═══╝╚══════╝ ╚═════╝  ╚═════╝╚═╝  ╚═╝

{Fore.GREEN}Created by: {Fore.CYAN}@one_lock
{Fore.GREEN}Channel: {Fore.CYAN}https://t.me/unluck_1l0ck
{Fore.RESET}"""
    print(banner)

def get_start_delay():
    while True:
        try:
            delay = input(f"\n{Fore.YELLOW}Enter delay before start (in seconds): {Fore.RESET}")
            seconds = int(delay)
            if seconds < 0:
                print(f"{Fore.RED}Please enter a positive number{Fore.RESET}")
                continue
            return seconds
        except ValueError:
            print(f"{Fore.RED}Please enter a valid number{Fore.RESET}")

def start_countdown(seconds):
    if seconds <= 0:
        return
        
    print(f"\n{Fore.YELLOW}Starting in {seconds} seconds...")
    
    while seconds > 0:
        print(f"\r{Fore.YELLOW}Time remaining: {seconds:02d}s", end="")
        sleep(1)
        seconds -= 1
    
    print(f"\n{Fore.GREEN}Starting now!{Fore.RESET}")

def main():
    init()
    ensure_directories()
    print_banner()
    
    try:
        delay_seconds = get_start_delay()
        start_countdown(delay_seconds)
        
        config = load_config()
        proxies_dict, all_proxies = read_proxies(config['app']['proxy_file'])
        user_agents_cycle = read_user_agents()
        accounts = read_accounts(config['app']['keys_file'])
        
        total_accounts = len(accounts)
        if total_accounts == 0:
            error_log("No accounts found in the keys file")
            sys.exit(1)

        print(f"\n{Fore.YELLOW}Total accounts to process: {total_accounts}")
        print(f"{Fore.YELLOW}Number of threads: {config['app']['threads']}")
        print(f"{Fore.GREEN}Starting now!")

        processor = FantasyProcessor(
            config=config,
            proxies_dict=proxies_dict,
            all_proxies=all_proxies,
            user_agents_cycle=user_agents_cycle
        )

        with concurrent.futures.ThreadPoolExecutor(max_workers=config['app']['threads']) as executor:
            futures = []
            for account_number, account_data in accounts:
                if len(account_data) != 2:
                    error_log(f"Invalid account data format for account {account_number}")
                    continue
                    
                private_key, wallet_address = account_data
                future = executor.submit(
                    processor.process_account_with_retry,
                    account_number,
                    private_key,
                    wallet_address,
                    total_accounts
                )
                futures.append(future)

            concurrent.futures.wait(futures)

        processor.retry_failed_accounts()

        final_success_rate = processor.retry_manager.get_success_rate() * 100
        info_log(f"Final success rate: {final_success_rate:.2f}%")

    except KeyboardInterrupt:
        print(f"\n{Fore.RED}Script interrupted by user")
        sys.exit(0)
    except Exception as e:
        error_log(f"Critical error in main execution: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
