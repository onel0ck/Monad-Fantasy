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
    info_log,
    validate_tournament_config,
)
from src.main import FantasyProcessor
import random


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


def start_countdown(seconds):
    if seconds <= 0:
        return

    print(f"\n{Fore.YELLOW}Starting in {seconds} seconds...")

    while seconds > 0:
        print(f"\r{Fore.YELLOW}Time remaining: {seconds:02d}s", end="")
        sleep(1)
        seconds -= 1

    print(f"\n{Fore.GREEN}Starting now!{Fore.RESET}")


def clear_log_files(config):
    files_to_clear = [
        config["app"]["failure_file"],
        config["app"]["success_file"],
        config["app"]["log_file"],
        config["app"]["result_file"],
    ]

    for file_path in files_to_clear:
        try:
            if os.path.exists(file_path):
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write("")
                info_log(f"Cleared file: {file_path}")
        except Exception as e:
            error_log(f"Error clearing file {file_path}: {str(e)}")


def main():
    init()
    ensure_directories()
    print_banner()

    try:
        config = load_config()
        config = validate_tournament_config(config)

        clear_log_files(config)

        proxies_dict, all_proxies = read_proxies(config["app"]["proxy_file"])
        user_agents_cycle = read_user_agents()
        accounts = read_accounts(config["app"]["keys_file"])
        random.shuffle(accounts)

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
            user_agents_cycle=user_agents_cycle,
        )

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=config["app"]["threads"]
        ) as executor:
            futures = []
            for account_number, account_data in accounts:
                if len(account_data) != 2:
                    error_log(
                        f"Invalid account data format for account {account_number}"
                    )
                    continue

                private_key, wallet_address = account_data
                future = executor.submit(
                    processor.process_account_with_retry,
                    account_number,
                    private_key,
                    wallet_address,
                    total_accounts,
                )
                futures.append(future)

                if "acc_delays" in config["app"]:
                    delay_config = config["app"]["acc_delays"]
                    delay_sec = random.randint(delay_config[0], delay_config[1])
                    delay_task = executor.submit(sleep, delay_sec)
                    futures.append(delay_task)

            concurrent.futures.wait(futures)

        processor.retry_failed_accounts()

        final_success_rate = processor.retry_manager.get_success_rate() * 100
        info_log(f"Final success rate: {final_success_rate:.2f}%")

        completed_quests_count = len(processor.completed_quests)
        info_log(f"Total quests completed: {completed_quests_count}")

        successful_accounts = len(processor.retry_manager.success_accounts)
        info_log(
            f"Successfully processed accounts: {successful_accounts} / {total_accounts} ({successful_accounts/total_accounts*100:.2f}%)"
        )

    except KeyboardInterrupt:
        print(f"\n{Fore.RED}Script interrupted by user")
        sys.exit(0)
    except Exception as e:
        error_log(f"Critical error in main execution: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
