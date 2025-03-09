import os
import re
from datetime import datetime
from colorama import init, Fore, Style

init(autoreset=True)

def print_header(text):
    border = "=" * (len(text) + 4)
    print(f"\n{Fore.CYAN}{border}")
    print(f"{Fore.CYAN}| {Fore.YELLOW}{text} {Fore.CYAN}|")
    print(f"{Fore.CYAN}{border}{Style.RESET_ALL}")

def safe_float(value, default=0.0):
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        value = value.strip('"\'')
        if value.lower() in ('none', 'null', ''):
            return default
        try:
            return float(value)
        except ValueError:
            return default
    return default

def parse_result_file(file_path):
    accounts = []
    
    if not os.path.exists(file_path):
        print(f"{Fore.RED}Error: File {file_path} not found")
        return accounts
    
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
                
            parts = line.split(':')
            if len(parts) < 2:
                continue
                
            account = {'address': parts[0]}
            
            for part in parts[1:]:
                if '=' in part:
                    key, value = part.split('=', 1)
                    try:
                        if key in ['fantasy_points', 'fragments', 'number_of_cards', 'whitelist_tickets']:
                            if value.lower() in ('none', 'null', ''):
                                account[key] = 0
                            else:
                                account[key] = int(value)
                        elif key in ['gliding_score', 'portfolio_value']:
                            account[key] = safe_float(value)
                        elif key == 'gold':
                            account[key] = safe_float(value)
                        elif key == 'onboarding_done':
                            account[key] = value.lower() == 'true'
                        else:
                            account[key] = value
                    except ValueError:
                        account[key] = value
            
            accounts.append(account)
    
    return accounts

def analyze_accounts(accounts):
    if not accounts:
        print(f"{Fore.RED}No accounts found in result file")
        return
    
    total_accounts = len(accounts)
    total_cards = sum(account.get('number_of_cards', 0) for account in accounts)
    total_fantasy_points = sum(account.get('fantasy_points', 0) for account in accounts)
    total_fragments = sum(account.get('fragments', 0) for account in accounts)
    total_whitelist_tickets = sum(account.get('whitelist_tickets', 0) for account in accounts)
    
    total_portfolio_value = sum(safe_float(account.get('portfolio_value')) for account in accounts)
    total_gliding_score = sum(safe_float(account.get('gliding_score')) for account in accounts)
    
    accounts_with_rewards = sum(1 for account in accounts if account.get('rewards', '0') != '0')
    accounts_with_tournament_rewards = sum(1 for account in accounts if 'tournament_rewards' in account)
    accounts_with_pending_packs = sum(1 for account in accounts if 'pending_packs' in account)
    accounts_with_packs = sum(1 for account in accounts if 'packs' in account)
    accounts_with_active_tournaments = sum(1 for account in accounts if 'active_tournaments' in account)
    
    print_header("ACCOUNT SUMMARY")
    print(f"{Fore.GREEN}Total accounts: {Fore.WHITE}{total_accounts}")
    print(f"{Fore.GREEN}Total cards: {Fore.WHITE}{total_cards}")
    print(f"{Fore.GREEN}Total fantasy points: {Fore.WHITE}{total_fantasy_points}")
    print(f"{Fore.GREEN}Total fragments: {Fore.WHITE}{total_fragments}")
    print(f"{Fore.GREEN}Total whitelist tickets: {Fore.WHITE}{total_whitelist_tickets}")
    print(f"{Fore.GREEN}Total portfolio value: {Fore.WHITE}{total_portfolio_value:.2f}")
    print(f"{Fore.GREEN}Total gliding score: {Fore.WHITE}{total_gliding_score:.2f}")
    
    print_header("AVERAGE VALUES")
    print(f"{Fore.GREEN}Average cards per account: {Fore.WHITE}{total_cards / total_accounts:.2f}")
    print(f"{Fore.GREEN}Average fantasy points per account: {Fore.WHITE}{total_fantasy_points / total_accounts:.2f}")
    print(f"{Fore.GREEN}Average fragments per account: {Fore.WHITE}{total_fragments / total_accounts:.2f}")
    print(f"{Fore.GREEN}Average whitelist tickets per account: {Fore.WHITE}{total_whitelist_tickets / total_accounts:.2f}")
    print(f"{Fore.GREEN}Average portfolio value per account: {Fore.WHITE}{total_portfolio_value / total_accounts:.2f}")
    print(f"{Fore.GREEN}Average gliding score per account: {Fore.WHITE}{total_gliding_score / total_accounts:.2f}")
    
    print_header("REWARDS STATISTICS")
    print(f"{Fore.GREEN}Accounts with rewards: {Fore.WHITE}{accounts_with_rewards} ({accounts_with_rewards / total_accounts * 100:.2f}%)")
    print(f"{Fore.GREEN}Accounts with tournament rewards: {Fore.WHITE}{accounts_with_tournament_rewards} ({accounts_with_tournament_rewards / total_accounts * 100:.2f}%)")
    print(f"{Fore.GREEN}Accounts with pending packs: {Fore.WHITE}{accounts_with_pending_packs} ({accounts_with_pending_packs / total_accounts * 100:.2f}%)")
    print(f"{Fore.GREEN}Accounts with packs: {Fore.WHITE}{accounts_with_packs} ({accounts_with_packs / total_accounts * 100:.2f}%)")
    print(f"{Fore.GREEN}Accounts with active tournaments: {Fore.WHITE}{accounts_with_active_tournaments} ({accounts_with_active_tournaments / total_accounts * 100:.2f}%)")
    
    if accounts_with_rewards > 0:
        print_header("ACCOUNTS WITH REWARDS")
        for account in accounts:
            if account.get('rewards', '0') != '0':
                print(f"{Fore.YELLOW}Address: {Fore.WHITE}{account['address']} {Fore.YELLOW}Rewards: {Fore.WHITE}{account['rewards']}")
    
    if accounts_with_tournament_rewards > 0:
        print_header("ACCOUNTS WITH TOURNAMENT REWARDS")
        for account in accounts:
            if 'tournament_rewards' in account:
                print(f"{Fore.YELLOW}Address: {Fore.WHITE}{account['address']} {Fore.YELLOW}Rewards: {Fore.WHITE}{account['tournament_rewards']}")
    
    if accounts_with_pending_packs > 0:
        print_header("ACCOUNTS WITH PENDING PACKS")
        for account in accounts:
            if 'pending_packs' in account:
                print(f"{Fore.YELLOW}Address: {Fore.WHITE}{account['address']} {Fore.YELLOW}Pending Packs: {Fore.WHITE}{account['pending_packs']}")
    
    if accounts_with_packs > 0:
        print_header("ACCOUNTS WITH PACKS")
        for account in accounts:
            if 'packs' in account:
                print(f"{Fore.YELLOW}Address: {Fore.WHITE}{account['address']} {Fore.YELLOW}Packs: {Fore.WHITE}{account['packs']}")
    
    print_header("TOP 5 ACCOUNTS BY FANTASY POINTS")
    sorted_by_points = sorted(accounts, key=lambda x: x.get('fantasy_points', 0), reverse=True)
    for i, account in enumerate(sorted_by_points[:5], 1):
        print(f"{Fore.YELLOW}{i}. {Fore.WHITE}{account['address']} {Fore.YELLOW}Points: {Fore.WHITE}{account.get('fantasy_points', 0)}")
    
    print_header("TOP 5 ACCOUNTS BY GLIDING SCORE")
    sorted_by_score = sorted(accounts, key=lambda x: safe_float(x.get('gliding_score')), reverse=True)
    for i, account in enumerate(sorted_by_score[:5], 1):
        gliding_score = safe_float(account.get('gliding_score'))
        print(f"{Fore.YELLOW}{i}. {Fore.WHITE}{account['address']} {Fore.YELLOW}Score: {Fore.WHITE}{gliding_score:.2f}")

def main():
    print(f"{Fore.CYAN}===================================================")
    print(f"{Fore.CYAN}=== {Fore.YELLOW}Monad Fantasy Manager Result Analyzer {Fore.CYAN}===")
    print(f"{Fore.CYAN}===================================================")
    print(f"{Fore.CYAN}Run time: {Fore.WHITE}{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    result_file = 'result.txt'
    accounts = parse_result_file(result_file)
    analyze_accounts(accounts)
    
    print(f"\n{Fore.GREEN}Analysis complete!{Style.RESET_ALL}")

if __name__ == "__main__":
    main()
