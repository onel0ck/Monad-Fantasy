import math
import random
import time
import os
import threading
import concurrent.futures
from time import sleep
import requests
from web3 import Web3
from colorama import Fore
from src.api import FantasyAPI
from src.utils import error_log, info_log, success_log, rate_limit_log
from src.account_storage import AccountStorage

class RetryManager:
    def __init__(self, max_retries=3, success_threshold=0.9):
        self.failed_accounts = set()
        self.success_accounts = set()
        self.attempt_counter = {}
        self.stored_credentials_failed = set()
        self.max_retries = max_retries
        self.success_threshold = success_threshold
        self.lock = threading.Lock()
        self.processed_failures = set()
        self.final_failures = set()
        self.completed_accounts = set()

    def add_failed_account(self, account_data):
        with self.lock:
            if account_data in self.completed_accounts:
                return
                
            if account_data not in self.success_accounts:
                self.failed_accounts.add(account_data)
                if account_data not in self.attempt_counter:
                    self.attempt_counter[account_data] = 1
                else:
                    self.attempt_counter[account_data] += 1
                
                if self.attempt_counter[account_data] >= self.max_retries:
                    if account_data not in self.final_failures:
                        self.final_failures.add(account_data)
                        self._write_to_fail_file(account_data)

    def add_success_account(self, account_data):
        with self.lock:
            self.success_accounts.add(account_data)
            self.completed_accounts.add(account_data)
            if account_data in self.failed_accounts:
                self.failed_accounts.remove(account_data)
            if account_data in self.final_failures:
                self.final_failures.remove(account_data)
            if account_data in self.stored_credentials_failed:
                self.stored_credentials_failed.remove(account_data)
            self.processed_failures.add(account_data)

    def should_process(self, account_data):
        with self.lock:
            if account_data in self.completed_accounts:
                return False
            if account_data in self.attempt_counter and self.attempt_counter[account_data] >= self.max_retries:
                return False
            return True
            
    def _write_to_fail_file(self, account_data):
        try:
            _, private_key, wallet_address = account_data
            fail_file_path = "logs/failure_accounts.txt"
            
            existing_entries = set()
            if os.path.exists(fail_file_path):
                with open(fail_file_path, "r") as f:
                    existing_entries = set(f.readlines())
            
            new_entry = f"{private_key}:{wallet_address}\n"
            
            if new_entry not in existing_entries:
                with open(fail_file_path, "a") as f:
                    f.write(new_entry)
                
        except Exception as e:
            error_log(f"Error writing to fail file: {str(e)}")

    def mark_stored_credentials_failed(self, account_data):
        with self.lock:
            self.stored_credentials_failed.add(account_data)

    def should_try_stored_credentials(self, account_data):
        return account_data not in self.stored_credentials_failed

    def get_retry_accounts(self):
        with self.lock:
            return [acc for acc in self.failed_accounts 
                   if acc not in self.completed_accounts
                   and self.attempt_counter[acc] < self.max_retries 
                   and acc not in self.final_failures]

    def get_current_attempt(self, account_data):
        with self.lock:
            return self.attempt_counter.get(account_data, 0)

    def get_success_rate(self):
        total = len(self.success_accounts) + len(self.failed_accounts)
        return len(self.success_accounts) / total if total > 0 else 0

    def should_continue_retrying(self):
        return (self.get_success_rate() < self.success_threshold and 
                bool(self.get_retry_accounts()))

    def get_unprocessed_failures(self):
        with self.lock:
            return [acc for acc in self.failed_accounts 
                   if acc not in self.processed_failures
                   and acc not in self.completed_accounts]

class FantasyProcessor:
    def __init__(self, config, proxies_dict, all_proxies, user_agents_cycle):
        self.config = config
        self.proxies = proxies_dict
        self.all_proxies = all_proxies
        self.user_agents_cycle = user_agents_cycle
        self.account_storage = AccountStorage()
        self.last_request_time = {}
        self.min_request_interval = 2
        self.lock = threading.Lock()
        self.retry_manager = RetryManager()
        self.retry_delay = 5
        self.max_proxy_retries = 5
        self.completed_quests = set()

    def _wait_rate_limit(self, thread_id):
        current_time = time.time()
        with self.lock:
            last_time = self.last_request_time.get(thread_id, 0)
            time_since_last = current_time - last_time
            if time_since_last < self.min_request_interval:
                sleep_time = self.min_request_interval - time_since_last
                sleep(sleep_time)
            self.last_request_time[thread_id] = time.time()

    def _get_random_proxy(self):
        with self.lock:
            return random.choice(self.all_proxies)

    def process_account_with_retry(self, account_number, private_key, wallet_address, total_accounts):
        account_data = (account_number, private_key, wallet_address)
        
        if not self.retry_manager.should_process(account_data):
            info_log(f"Skipping account {account_number}: already processed successfully or max retries reached")
            return
            
        proxy_retries = 0
        
        while proxy_retries < self.max_proxy_retries:
            try:
                success = self.process_account(account_number, private_key, wallet_address, total_accounts)
                if success:
                    self.retry_manager.add_success_account(account_data)
                    return
                proxy_retries += 1
                sleep(2)
            except requests.exceptions.RequestException as e:
                error_log(f"Network error for account {account_number}: {str(e)}")
                proxy_retries += 1
                sleep(2)
            except Exception as e:
                error_log(f"Error processing account {account_number}: {str(e)}")
                self.retry_manager.add_failed_account(account_data)
                return

        self.retry_manager.add_failed_account(account_data)

    def process_account(self, account_number, private_key, wallet_address, total_accounts):
        max_attempts = 3
        account_data = (account_number, private_key, wallet_address)
        current_attempt = self.retry_manager.get_current_attempt(account_data)
        
        while current_attempt < max_attempts:
            try:
                thread_id = threading.get_ident()
                self._wait_rate_limit(thread_id)
                
                session = requests.Session()
                api = None
                
                try:
                    proxy = self._get_random_proxy()
                    proxy_dict = {"http": proxy, "https": proxy}
                    
                    if current_attempt == 0:
                        info_log(f'Processing account {account_number}: {wallet_address}')
                    else:
                        info_log(f'Retrying account {account_number}: {wallet_address} (Attempt {current_attempt + 1}/{max_attempts})')
                    
                    with self.lock:
                        user_agent = next(self.user_agents_cycle)
                    
                    api = FantasyAPI(
                        web3_provider=self.config['rpc']['url'],
                        session=session,
                        proxies=proxy_dict,
                        all_proxies=self.all_proxies,
                        config=self.config,
                        user_agent=user_agent,
                        account_storage=self.account_storage
                    )

                    auth_data = None
                    token = None
                    
                    if current_attempt == 0:
                        stored_success, stored_token = api.token_manager.try_stored_credentials(wallet_address, account_number)
                        if stored_success:
                            info_log(f'Using stored credentials for account {account_number}')
                            token = stored_token

                    if not token:
                        auth_data = api.login(private_key, wallet_address, account_number)
                        if auth_data is False:
                            current_attempt += 1
                            session.close()
                            sleep(2)
                            continue
                        
                        if isinstance(auth_data, str) and "429" in auth_data:
                            info_log(f'Rate limit on login for account {account_number}, switching proxy...')
                            current_attempt += 1
                            session.close()
                            sleep(2)
                            continue

                        token = api.get_token(auth_data, wallet_address, account_number)
                        if not token:
                            current_attempt += 1
                            session.close()
                            sleep(2)
                            continue

                    tasks_completed = True

                    if self.config.get('starter_cards', {}).get('enabled', False):
                        account_info = None
                        if self.config['info_check']:
                            account_info = api.info(token, wallet_address, account_number)
                            if isinstance(account_info, str) and "429" in account_info:
                                info_log(f'Rate limit on info check, retrying...')
                                sleep(2)
                                continue
                                
                        card_count = 0
                        if isinstance(account_info, dict):
                            card_count = account_info.get('number_of_cards', 0)
                        elif os.path.exists(self.config['app']['result_file']):
                            with open(self.config['app']['result_file'], 'r') as f:
                                for line in f:
                                    if wallet_address in line:
                                        parts = line.strip().split(':')
                                        for part in parts:
                                            if part.startswith('number_of_cards='):
                                                try:
                                                    card_count = int(part.split('=')[1])
                                                except ValueError:
                                                    pass
                                        break
                        
                        if card_count >= 15:
                            info_log(f"Account {account_number}: Already has {card_count} cards, skipping starter cards claim")
                        else:
                            starter_cards_success = api.claim_starter_cards(token, wallet_address, account_number)
                            if isinstance(starter_cards_success, str) and "429" in starter_cards_success:
                                info_log(f'Rate limit on claiming starter cards for account {account_number}, retrying...')
                                sleep(2)
                                continue
                            if starter_cards_success:
                                success_log(f"Account {account_number}: Successfully claimed starter cards")
                                
                                if self.config.get('tournaments', {}).get('enabled', False):
                                    wait_time = self.config.get('starter_cards', {}).get('wait_time_after_claim', 10)
                                    info_log(f"Waiting {wait_time} seconds for transaction confirmation before tournament registration...")
                                    sleep(wait_time)
                                    
                                    account_info = api.info(token, wallet_address, account_number)
                                    if isinstance(account_info, str) and "429" in account_info:
                                        info_log(f'Rate limit on info check after claiming cards, continuing...')
                                    else:
                                        success_log(f"Account {account_number}: Updated info after claiming cards")
                            else:
                                info_log(f'Claiming starter cards skipped or failed for account {account_number}')
                    
                    if self.config['onboarding_quest']['enabled']:
                        onboarding_ids = self.config['onboarding_quest'].get('ids', [])
                        
                        if 'id' in self.config['onboarding_quest']:
                            single_id = self.config['onboarding_quest']['id']
                            if single_id and single_id not in onboarding_ids:
                                onboarding_ids.append(single_id)
                        
                        if not onboarding_ids:
                            info_log(f'No onboarding quest IDs configured for account {account_number}')
                        else:
                            for onboarding_id in onboarding_ids:
                                quest_key = f"{account_number}:{onboarding_id}"
                                if quest_key in self.completed_quests:
                                    continue
                                    
                                onboarding_success = api.onboarding_quest_claim(token, wallet_address, account_number, onboarding_id)
                                if onboarding_success:
                                    success_log(f"Successfully completed onboarding quest {onboarding_id} for account {account_number}")
                                    self.completed_quests.add(quest_key)
                                else:
                                    info_log(f'Onboarding quest {onboarding_id} skipped or failed for account {account_number}')

                    if self.config['daily']['enabled']:
                        daily_success = api.daily_claim(token, wallet_address, account_number)
                        if isinstance(daily_success, str) and "429" in daily_success:
                            info_log(f'Rate limit on daily claim for account {account_number}, retrying...')
                            sleep(2)
                            continue
                        if not daily_success:
                            tasks_completed = False
                        else:
                            success_log(f"Account {account_number}: Successfully claimed daily reward")

                    if self.config['fragments']['enabled']:
                        fragment_id = self.config['fragments']['id']
                        fragment_success = api.fragments_claim(token, wallet_address, account_number, fragment_id)
                        if not fragment_success:
                            tasks_completed = False
                    
                    if self.config.get('fragment_roulette', {}).get('enabled', False):
                        claim_packs = self.config.get('other_rewards', {}).get('claim_packs', False)
                        fragment_roulette_result = api.fragment_roulette(
                            token, 
                            wallet_address, 
                            account_number, 
                            private_key if claim_packs else None
                        )
                        if isinstance(fragment_roulette_result, str) and "429" in fragment_roulette_result:
                            info_log(f'Rate limit on fragment roulette for account {account_number}, retrying...')
                            sleep(2)
                            continue
                        if fragment_roulette_result and fragment_roulette_result.get('success', False):
                            prize = fragment_roulette_result.get('selectedPrize', {})
                            prize_type = prize.get('type', 'Unknown')
                            prize_amount = prize.get('text', 'Unknown')
                            success_log(f"Account {account_number}: Fragment roulette success - {prize_type}({prize_amount})")
                        else:
                            info_log(f"Account {account_number}: Fragment roulette skipped (not enough fragments or already claimed)")
                    
                    if self.config['quest']['enabled']:
                        for quest_id in self.config['quest']['ids']:
                            quest_key = f"{account_number}:{quest_id}"
                            if quest_key in self.completed_quests:
                                continue
                                
                            quest_success = api.quest_claim(token, wallet_address, account_number, quest_id)
                            if quest_success == "429":
                                info_log(f'Rate limit on quest claim for account {account_number}, retrying...')
                                sleep(2)
                                continue
                            if quest_success:
                                self.completed_quests.add(quest_key)
                            else:
                                tasks_completed = False

                    if self.config.get('tournaments', {}).get('enabled', False) and self.config.get('tournaments', {}).get('claim_rewards', False):
                        tournament_rewards = api.check_tournament_rewards(token, wallet_address, account_number)
                        if isinstance(tournament_rewards, str) and "429" in tournament_rewards:
                            info_log(f'Rate limit on checking tournament rewards for account {account_number}, retrying...')
                            sleep(2)
                            continue
                        
                        if tournament_rewards and 'tournamentRewards' in tournament_rewards and tournament_rewards['tournamentRewards']:
                            success_log(f"Account {account_number}: Found available tournament rewards")
                            
                            tournament_data = api.get_active_tournaments(token, wallet_address, account_number)
                            if isinstance(tournament_data, str) and "429" in tournament_data:
                                info_log(f'Rate limit on getting tournament data for account {account_number}, retrying...')
                                sleep(2)
                                continue
                            
                            if tournament_data and 'tournaments' in tournament_data:
                                tournament_ids = [t.get('id') for t in tournament_data.get('tournaments', [])]
                                
                                if tournament_ids:
                                    sleep(1)
                                    
                                    claim_result = api.claim_tournament_rewards(token, wallet_address, account_number, tournament_ids)
                                    
                                    if isinstance(claim_result, str) and "429" in claim_result:
                                        info_log(f'Rate limit on claiming tournament rewards for account {account_number}, retrying...')
                                        sleep(2)
                                        continue
                                    
                                    if claim_result:
                                        if isinstance(claim_result, dict):
                                            if 'claimed' in claim_result:
                                                rewards = claim_result.get('claimed', {})
                                                rewards_str = ", ".join([f"{k}: {v}" for k, v in rewards.items()])
                                                success_log(f"Account {account_number}: Successfully claimed tournament rewards: {rewards_str}")
                                            elif 'status' in claim_result and claim_result['status'] == 'already_claimed':
                                                success_log(f"Account {account_number}: Tournament rewards processing completed")
                                        else:
                                            info_log(f"Unexpected result type from claim_tournament_rewards for account {account_number}")
                                    else:
                                        info_log(f'Failed to claim tournament rewards for account {account_number}')
                                else:
                                    info_log(f'No tournament IDs found for account {account_number}')
                            else:
                                info_log(f'Tournament data unavailable for account {account_number}')
                        else:
                            info_log(f'No available tournament rewards found for account {account_number}')

                    if self.config.get('other_rewards', {}).get('enabled', False) and self.config.get('other_rewards', {}).get('claim_packs', False):
                        pack_processing_result = api.process_fragment_packs(token, wallet_address, account_number, private_key)
                        if isinstance(pack_processing_result, str) and "429" in pack_processing_result:
                            info_log(f'Rate limit on pack processing for account {account_number}, retrying...')
                            sleep(2)
                            continue
                        
                        if pack_processing_result:
                            success_log(f"Account {account_number}: Successfully processed fragment packs")
                        else:
                            info_log(f"Account {account_number}: No fragment packs to process or processing failed")

                    if self.config.get('other_rewards', {}).get('enabled', False):
                        other_rewards_result = api.check_other_rewards(token, wallet_address, account_number)
                        if isinstance(other_rewards_result, str) and "429" in other_rewards_result:
                            info_log(f'Rate limit on checking other rewards for account {account_number}, retrying...')
                            sleep(2)
                            continue
                        
                        if other_rewards_result:
                            success_log(f"Account {account_number}: Successfully processed other rewards")

                    if self.config['info_check']:
                        info_success = api.info(token, wallet_address, account_number)
                        if isinstance(info_success, str) and "429" in info_success:
                            info_log(f'Rate limit on info check for account {account_number}, retrying...')
                            current_attempt += 1
                            sleep(2)
                            continue
                        if not info_success:
                            tasks_completed = False

                    if self.config.get('tournaments', {}).get('enabled', False):
                        from src.tournament_manager import TournamentManager
                        tournament_manager = TournamentManager(api, self.config)
                        
                        tournament_ids = {}
                        for t_type, t_config in self.config['tournaments']['types'].items():
                            if t_config.get('enabled', False) and t_config.get('id'):
                                tournament_ids[t_type] = t_config['id']
                        
                        if tournament_ids:
                            info_log(f"Registering account {account_number} in tournaments: {', '.join(tournament_ids.keys())}")
                            tournament_results = tournament_manager.register_in_tournaments(
                                token, wallet_address, account_number, tournament_ids
                            )
                            
                            success_tournaments = [t_type for t_type, result in tournament_results.items() if result]
                            if success_tournaments:
                                success_log(f"Account {account_number}: Successfully registered in {', '.join(success_tournaments)} tournaments")
                            
                            failed_tournaments = [t_type for t_type, result in tournament_results.items() if not result]
                            if failed_tournaments:
                                info_log(f"Account {account_number}: Failed to register in {', '.join(failed_tournaments)} tournaments")
                    
                    if tasks_completed:
                        self._write_success(private_key, wallet_address)
                        success_log(f"Account {account_number}: {wallet_address} - All tasks completed successfully")
                        self.retry_manager.add_success_account(account_data)
                        return True
                    else:
                        current_attempt += 1
                        session.close()
                        sleep(2)
                        continue

                except requests.exceptions.RequestException as e:
                    if "429" in str(e):
                        info_log(f'Rate limit exception for account {account_number}, retrying...')
                        current_attempt += 1
                        sleep(2)
                        continue
                    error_log(f'Request error for account {account_number}: {str(e)}')
                    current_attempt += 1
                    session.close()
                    sleep(2)
                    continue
                    
                finally:
                    if session:
                        session.close()

            except Exception as e:
                error_log(f"Error processing account {account_number}: {str(e)}")
                current_attempt += 1
                sleep(2)
                continue

        error_log(f'All attempts exhausted for account {account_number}')
        self._write_failure(private_key, wallet_address)
        self.retry_manager.add_failed_account(account_data)
        return False

    def retry_failed_accounts(self):
        if not self.config['app'].get('retry_failed_accounts', True):
            info_log("Retry failed accounts feature is disabled in config. Skipping.")
            return
            
        while self.retry_manager.should_continue_retrying():
            retry_accounts = self.retry_manager.get_retry_accounts()
            if retry_accounts:
                info_log(f"Retrying {len(retry_accounts)} accounts from current session. Success rate: "
                        f"{self.retry_manager.get_success_rate()*100:.2f}%")
                
                with concurrent.futures.ThreadPoolExecutor(max_workers=self.config['app']['threads']) as executor:
                    futures = []
                    for account_number, private_key, wallet_address in retry_accounts:
                        sleep(self.retry_delay)
                        future = executor.submit(
                            self.process_account_with_retry,
                            account_number,
                            private_key,
                            wallet_address,
                            len(retry_accounts)
                        )
                        futures.append(future)
                    concurrent.futures.wait(futures)

        try:
            if os.path.exists(self.config['app']['failure_file']):
                with open(self.config['app']['failure_file'], 'r') as f:
                    failed_accounts = []
                    seen_accounts = set()
                    
                    for line in f:
                        if line.strip():
                            try:
                                private_key, wallet_address = line.strip().split(':')
                                if wallet_address not in seen_accounts:
                                    failed_accounts.append((private_key, wallet_address))
                                    seen_accounts.add(wallet_address)
                            except ValueError:
                                error_log(f"Invalid line format in failure_accounts.txt: {line.strip()}")
                                continue
                if failed_accounts:
                    info_log(f"Processing {len(failed_accounts)} unique accounts from failure_accounts.txt...")
                    
                    with concurrent.futures.ThreadPoolExecutor(max_workers=self.config['app']['threads']) as executor:
                        futures = []
                        for idx, (private_key, wallet_address) in enumerate(failed_accounts, 1):
                            sleep(self.retry_delay)
                            future = executor.submit(
                                self.process_account_with_retry,
                                idx,
                                private_key,
                                wallet_address,
                                len(failed_accounts)
                            )
                            futures.append(future)
                        concurrent.futures.wait(futures)
                    
                    success_rate = self.retry_manager.get_success_rate() * 100
                    info_log(f"Final success rate for failure_accounts.txt: {success_rate:.2f}%")
                else:
                    info_log("No valid accounts found in failure_accounts.txt")
                    
                open(self.config['app']['failure_file'], 'w').close()
                
        except Exception as e:
            error_log(f"Error processing failure_accounts.txt: {str(e)}")

    def _write_success(self, private_key, wallet_address):
        with self.lock:
            try:
                with open(self.config['app']['success_file'], 'a') as f:
                    f.write(f'{private_key}:{wallet_address}\n')
                info_log(f'Successfully wrote {wallet_address} to success file')
            except Exception as e:
                error_log(f'Error writing to success file: {str(e)}')

    def _write_failure(self, private_key, wallet_address):
        with self.lock:
            try:
                existing_entries = set()
                if os.path.exists(self.config['app']['failure_file']):
                    with open(self.config['app']['failure_file'], 'r') as f:
                        existing_entries = {line.strip() for line in f}

                new_entry = f"{private_key}:{wallet_address}"
                
                if new_entry not in existing_entries:
                    with open(self.config['app']['failure_file'], 'a') as f:
                        f.write(f'{new_entry}\n')
                    info_log(f'Wrote {wallet_address} to failure file')
            except Exception as e:
                error_log(f'Error writing to failure file: {str(e)}')
