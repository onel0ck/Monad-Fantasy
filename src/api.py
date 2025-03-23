import json
from time import sleep
import random
import requests
from web3 import Web3
from eth_account.messages import encode_defunct
from datetime import datetime, timedelta
from dateutil import parser
import pytz
import math
import os
import jwt
from typing import Dict, Optional, Tuple
from colorama import Fore
from .utils import error_log, success_log, info_log, rate_limit_log, debug_log
from capmonster_python import TurnstileTask
import threading
import time


class TokenManager:
    def __init__(self, account_storage, api_instance):
        self.account_storage = account_storage
        self.api = api_instance
        self.max_retries = 2
        self.rate_limit_delay = 3
        self.stored_credentials_failed = set()

    def validate_token(self, token: str) -> bool:
        try:
            decoded = jwt.decode(token, options={"verify_signature": False})
            exp_timestamp = decoded.get('exp')
            if not exp_timestamp:
                return False
            
            expiration = datetime.fromtimestamp(exp_timestamp, pytz.UTC)
            current_time = datetime.now(pytz.UTC)
            
            return current_time < (expiration - timedelta(minutes=5))
        except jwt.InvalidTokenError:
            return False

    def validate_cookies(self, cookies: dict) -> bool:
        required_cookies = {
            'privy-token',
            'privy-session',
            'privy-access-token',
            'privy-refresh-token'
        }
        return all(cookie in cookies for cookie in required_cookies)

    def check_stored_credentials(self, wallet_address: str) -> tuple[bool, Optional[str], Optional[dict]]:
        account_data = self.account_storage.get_account_data(wallet_address)
        if not account_data:
            return False, None, None

        token = account_data.get('token')
        cookies = account_data.get('cookies')

        if not token or not cookies:
            return False, None, None

        if not self.validate_token(token):
            return False, None, None

        if wallet_address in self.stored_credentials_failed:
            return False, None, None

        last_claim = account_data.get('last_daily_claim')
        if last_claim:
            try:
                last_claim_time = datetime.fromisoformat(last_claim)
                next_claim = last_claim_time + timedelta(hours=24)
                if datetime.now(pytz.UTC) < next_claim:
                    info_log(f"Account {wallet_address} cannot claim daily yet. Next claim at {next_claim}")
                    return False, None, None
            except ValueError:
                return False, None, None

        return True, token, cookies

    def _test_token(self, token: str, wallet_address: str, account_number: int) -> bool:
        headers = {
            'Accept': 'application/json, text/plain, */*',
            'Authorization': f'Bearer {token}',
            'Origin': 'https://fantasy.top',
            'Referer': 'https://fantasy.top/',
        }
        
        for attempt in range(2):
            try:
                response = self.api.session.get(
                    'https://fantasy.top/api/get-player-basic-data',
                    params={"playerId": wallet_address},
                    headers=headers,
                    proxies=self.api.proxies,
                    timeout=10
                )
                
                if response.status_code == 429:
                    rate_limit_log(f'Rate limit hit while testing token for account {account_number}')
                    sleep(self.rate_limit_delay)
                    continue
                    
                return response.status_code == 200
                
            except requests.exceptions.RequestException:
                sleep(1)
                continue
                
        return False

    def try_stored_credentials(self, wallet_address: str, account_number: int) -> Tuple[bool, Optional[str]]:
        is_valid, token, cookies = self.check_stored_credentials(wallet_address)
        if not is_valid:
            return False, None

        if cookies:
            for cookie_name, cookie_value in cookies.items():
                self.api.session.cookies.set(cookie_name, cookie_value)

        token_valid = self._test_token(token, wallet_address, account_number)
        if not token_valid:
            return False, None
            
        return True, token

    def mark_stored_credentials_failed(self, wallet_address: str):
        self.stored_credentials_failed.add(wallet_address)

    def should_try_stored_credentials(self, wallet_address: str) -> bool:
        return wallet_address not in self.stored_credentials_failed

    def update_credentials(self, wallet_address: str, token: str, cookies: dict):
        self.account_storage.update_account(
            wallet_address,
            self.account_storage.get_account_data(wallet_address)["private_key"],
            token=token,
            cookies=cookies
        )

    def invalidate_credentials(self, wallet_address: str):
        account_data = self.account_storage.get_account_data(wallet_address)
        if account_data:
            self.account_storage.update_account(
                wallet_address,
                account_data["private_key"],
                token=None,
                cookies=None
            )

class CaptchaTokenPool:
    def __init__(self, config):
        self.config = config
        self.current_token = None
        self.last_update = 0
        self.update_interval = 7
        self.lock = threading.Lock()

    def _get_new_token(self) -> Optional[str]:
        try:
            if self.config['capmonster']['enabled']:
                capmonster = TurnstileTask(self.config['capmonster']['api_key'])
                task_id = capmonster.create_task(
                    website_url="https://monad.fantasy.top",
                    website_key="0x4AAAAAAAM8ceq5KhP1uJBt"
                )
                result = capmonster.join_task_result(task_id)
                token = result.get('token')
                if token:
                    return token
            elif self.config.get('2captcha', {}).get('enabled', False):
                api_key = self.config['2captcha']['api_key']
                solver = requests.get(
                    f"https://2captcha.com/in.php?key={api_key}&method=turnstile&sitekey=0x4AAAAAAAM8ceq5KhP1uJBt&pageurl=https://monad.fantasy.top"
                )
                if solver.text.startswith('OK|'):
                    captcha_id = solver.text.split('|')[1]
                    for i in range(30):
                        time.sleep(5)
                        response = requests.get(
                            f"https://2captcha.com/res.php?key={api_key}&action=get&id={captcha_id}"
                        )
                        if response.text.startswith('OK|'):
                            return response.text.split('|')[1]
                        if response.text != 'CAPCHA_NOT_READY':
                            error_log(f"Error from 2captcha: {response.text}")
                            break
                    error_log("Timeout waiting for 2captcha solution")
        except Exception as e:
            error_log(f"Error getting captcha token: {e}")
        return None
        
    def get_token(self) -> Optional[str]:
        with self.lock:
            current_time = time.time()
            
            if self.current_token and current_time - self.last_update < self.update_interval:
                return self.current_token

            new_token = self._get_new_token()
            if new_token:
                self.current_token = new_token
                self.last_update = current_time
            return new_token

class FantasyAPI:
    def __init__(self, web3_provider, session, proxies, all_proxies, config, user_agent, account_storage):
        self.web3 = Web3(Web3.HTTPProvider(web3_provider))
        self.session = session
        self.proxies = proxies
        self.all_proxies = all_proxies
        self.config = config
        self.user_agent = user_agent
        self.base_url = "https://monad.fantasy.top"
        self.privy_url = "https://auth.privy.io"
        self.account_storage = account_storage
        self.token_manager = TokenManager(account_storage, self)
        self.captcha_pool = CaptchaTokenPool(config)
        
        info_log(f"[DEBUG] FantasyAPI initialized with base_url: {self.base_url}, privy_url: {self.privy_url}")

    def _get_captcha_token(self) -> Optional[str]:
        return self.captcha_pool.get_token()

    def login(self, private_key, wallet_address, account_number):
        max_retries = 3
        retry_delay = 2
        captcha_token = None
        
        info_log(f"Starting login process for account {account_number}: {wallet_address}")
        
        for attempt in range(max_retries):
            try:
                self.session.headers.update({
                    'Accept': 'application/json',
                    'Content-Type': 'application/json',
                    'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
                    'Origin': 'https://monad.fantasy.top',
                    'Referer': f'https://monad.fantasy.top/',
                    'User-Agent': self.user_agent,
                    'privy-app-id': 'cm6ezzy660297zgdk7t3glcz5',
                    'privy-client': 'react-auth:1.92.3',
                    'privy-client-id': 'client-WY5gEtuoV4UpG2Le3n5pt6QQD61Ztx62VDwtDCZeQc3sN',
                    'privy-ca-id': self.config['app'].get('privy_ca_id', '52bc773e-737a-4e32-bd36-7563dcef2de1'),
                    'Sec-Ch-Ua': '"Google Chrome";v="132", "Chromium";v="132", "Not_A Brand";v="8"',
                    'Sec-Ch-Ua-Mobile': '?0',
                    'Sec-Ch-Ua-Platform': '"Windows"',
                    'Sec-Fetch-Dest': 'empty',
                    'Sec-Fetch-Mode': 'cors',
                    'Sec-Fetch-Site': 'cross-site',
                    'Priority': 'u=1, i'
                })

                if captcha_token is None:
                    captcha_token = self._get_captcha_token()
                    if not captcha_token:
                        error_log(f'Failed to get captcha token for account {account_number}')
                        sleep(retry_delay)
                        continue

                debug_log(f"Requesting nonce for account {account_number}")
                init_response = self.session.post(
                    'https://auth.privy.io/api/v1/siwe/init', 
                    json={'address': wallet_address, 'token': captcha_token},
                    headers=self.session.headers,
                    proxies=self.proxies,
                    timeout=10
                )
                
                if init_response.status_code == 429:
                    info_log(f"Rate limit hit during nonce request for account {account_number}")
                    sleep(retry_delay)
                    continue
                    
                if init_response.status_code != 200:
                    info_log(f"Failed to get nonce, status: {init_response.status_code}")
                    captcha_token = self._get_captcha_token()
                    continue

                nonce_data = init_response.json()
                message = self._create_sign_message(wallet_address, nonce_data['nonce'])
                debug_log(f"Created sign message for account {account_number}")
                signed_message = self._sign_message(message, private_key)
                debug_log(f"Message signed successfully for account {account_number}")

                auth_payload = {
                    'chainId': 'eip155:1',
                    'connectorType': 'injected',
                    'message': message,
                    'signature': signed_message.signature.hex(),
                    'walletClientType': 'metamask',
                    'mode': 'login-or-sign-up'
                }

                debug_log(f"Sending authentication request for account {account_number}")
                auth_response = self.session.post(
                    'https://auth.privy.io/api/v1/siwe/authenticate',
                    json=auth_payload,
                    proxies=self.proxies,
                    timeout=10
                )
                
                if auth_response.status_code != 200:
                    error_log(f"Auth failed with status {auth_response.status_code} for account {account_number}")
                    if attempt < max_retries - 1:
                        proxy = random.choice(self.all_proxies)
                        self.proxies = {"http": proxy, "https": proxy}
                        info_log(f"Switching proxy for account {account_number}")
                        sleep(retry_delay)
                        continue
                    return False

                auth_data = auth_response.json()
                debug_log(f"Authentication successful, received token for account {account_number}")
                
                if 'token' in auth_data:
                    self.session.cookies.set('privy-token', auth_data['token'])
                    debug_log(f"Set privy-token cookie for account {account_number}")
                if auth_data.get('identity_token'):
                    self.session.cookies.set('privy-id-token', auth_data['identity_token'])
                    debug_log(f"Set privy-id-token cookie for account {account_number}")
                
                final_auth_payload = {"address": wallet_address}
                
                debug_log(f"Requesting application token for account {account_number}")
                final_auth_response = self.session.post(
                    'https://monad.fantasy.top/api/auth/privy',
                    json=final_auth_payload,
                    headers={
                        'Accept': 'application/json, text/plain, */*',
                        'Content-Type': 'application/json',
                        'Origin': 'https://monad.fantasy.top',
                        'Referer': 'https://monad.fantasy.top/',
                        'Authorization': f'Bearer {auth_data["token"]}'
                    },
                    proxies=self.proxies,
                    timeout=10
                )
                
                if final_auth_response.status_code != 200:
                    error_log(f"Failed to get application token, status: {final_auth_response.status_code}")
                    if attempt < max_retries - 1:
                        proxy = random.choice(self.all_proxies)
                        self.proxies = {"http": proxy, "https": proxy}
                        sleep(retry_delay)
                        continue
                    return False

                final_auth_data = final_auth_response.json()
                cookies_dict = {cookie.name: cookie.value for cookie in self.session.cookies}

                self.account_storage.update_account(
                    wallet_address,
                    private_key,
                    token=final_auth_data.get('token'),
                    cookies=cookies_dict
                )
                
                success_log(f"Account {account_number}: {wallet_address} Login done")
                return final_auth_data

            except Exception as e:
                error_log(f'Error during login attempt {attempt + 1}: {str(e)}')
                if attempt < max_retries - 1:
                    sleep(retry_delay)
                    continue

        return False

    def get_token(self, auth_data, wallet_address, account_number):
        try:
            if "token" in auth_data:
                token = auth_data["token"]
                self.account_storage.update_account(
                    wallet_address,
                    self.account_storage.get_account_data(wallet_address)["private_key"],
                    token=token
                )
                info_log(f'Token obtained for account {account_number}: {wallet_address}')
                return token
            
            error_log(f'No token found in auth_data for account {account_number}')
            return False

        except Exception as e:
            error_log(f'Token error for account {account_number}: {str(e)}')
            return False

    def check_tournament_rewards(self, token, wallet_address, account_number):
        try:
            privy_id_token = None
            for cookie in self.session.cookies:
                if cookie.name == 'privy-id-token':
                    privy_id_token = cookie.value
                    break
            
            auth_token = privy_id_token if privy_id_token else token
            
            headers = {
                'Accept': 'application/json, text/plain, */*',
                'Authorization': f'Bearer {auth_token}',
                'Origin': 'https://monad.fantasy.top',
                'Referer': 'https://monad.fantasy.top/',
                'User-Agent': self.user_agent
            }

            response = self.session.get(
                'https://secret-api.fantasy.top/player/player-rewards',
                headers=headers,
                proxies=self.proxies,
                timeout=10
            )
            
            if response.status_code == 401 and auth_token == privy_id_token and token:
                auth_token = token
                headers['Authorization'] = f'Bearer {auth_token}'
                response = self.session.get(
                    'https://secret-api.fantasy.top/player/player-rewards',
                    headers=headers,
                    proxies=self.proxies,
                    timeout=10
                )
            
            if response.status_code != 200:
                error_log(f"Failed to check tournament rewards: {response.status_code}")
                return None
            
            data = response.json()
            return data
            
        except Exception as e:
            error_log(f'Error checking tournament rewards: {str(e)}')
            return None

    def check_pending_packs(self, token, wallet_address, account_number):
        try:
            privy_id_token = None
            for cookie in self.session.cookies:
                if cookie.name == 'privy-id-token':
                    privy_id_token = cookie.value
                    break
            
            auth_token = privy_id_token if privy_id_token else token
            
            headers = {
                'Accept': 'application/json, text/plain, */*',
                'Authorization': f'Bearer {auth_token}',
                'Origin': 'https://monad.fantasy.top',
                'Referer': 'https://monad.fantasy.top/',
                'User-Agent': self.user_agent
            }

            response = self.session.get(
                'https://secret-api.fantasy.top/rewards/has-pending-cards-from-fragments',
                headers=headers,
                proxies=self.proxies,
                timeout=10
            )
            
            if response.status_code == 401 and auth_token == privy_id_token and token:
                auth_token = token
                headers['Authorization'] = f'Bearer {auth_token}'
                response = self.session.get(
                    'https://secret-api.fantasy.top/rewards/has-pending-cards-from-fragments',
                    headers=headers,
                    proxies=self.proxies,
                    timeout=10
                )
            
            if response.status_code != 200:
                error_log(f"Failed to check pending packs: {response.status_code}")
                return None
            
            data = response.json()
            return data
            
        except Exception as e:
            error_log(f'Error checking pending packs: {str(e)}')
            return None

    def get_active_tournaments(self, token, wallet_address, account_number):
        try:
            privy_id_token = None
            for cookie in self.session.cookies:
                if cookie.name == 'privy-id-token':
                    privy_id_token = cookie.value
                    break
            
            auth_token = privy_id_token if privy_id_token else token
            
            headers = {
                'Accept': 'application/json, text/plain, */*',
                'Authorization': f'Bearer {auth_token}',
                'Origin': 'https://monad.fantasy.top',
                'Referer': 'https://monad.fantasy.top/',
                'User-Agent': self.user_agent,
                'sec-ch-ua': '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"'
            }

            rewards_response = self.session.get(
                'https://secret-api.fantasy.top/player/player-rewards',
                headers=headers,
                proxies=self.proxies,
                timeout=10
            )
            
            if rewards_response.status_code == 401 and auth_token == privy_id_token and token:
                auth_token = token
                headers['Authorization'] = f'Bearer {auth_token}'
                rewards_response = self.session.get(
                    'https://secret-api.fantasy.top/player/player-rewards',
                    headers=headers,
                    proxies=self.proxies,
                    timeout=10
                )
            
            tournament_number = 3
            
            if rewards_response.status_code == 200:
                rewards_data = rewards_response.json()
                tournament_rewards = rewards_data.get('tournamentRewards', [])
                if tournament_rewards:
                    tournament_numbers = [reward.get('tournament_number', 0) for reward in tournament_rewards]
                    if tournament_numbers:
                        tournament_number = max(tournament_numbers)
                        debug_log(f"Tournament number determined: {tournament_number} for account {account_number}")
            
            debug_log(f"Getting tournament summary for account {account_number}, tournament number: {tournament_number}")
            response = self.session.get(
                f'https://secret-api.fantasy.top/tournaments/summary/{tournament_number}/player?playerId={wallet_address}',
                headers=headers,
                proxies=self.proxies,
                timeout=10
            )
            
            if response.status_code == 401 and auth_token == privy_id_token and token:
                auth_token = token
                headers['Authorization'] = f'Bearer {auth_token}'
                response = self.session.get(
                    f'https://secret-api.fantasy.top/tournaments/summary/{tournament_number}/player?playerId={wallet_address}',
                    headers=headers,
                    proxies=self.proxies,
                    timeout=10
                )
            
            if response.status_code != 200:
                error_log(f"Failed to get active tournaments: {response.status_code}")
                return None
            
            data = response.json()
            
            debug_log(f"Tournament summary response: {response.status_code}")
            
            if 'already_claimed' in data:
                debug_log(f"Already claimed status: {data['already_claimed']} for account {account_number}")
            
            if 'tournaments' in data:
                tournament_info = []
                for t in data['tournaments']:
                    tournament_info.append(f"{t.get('name', 'Unknown')}(#{t.get('tournament_number', 'N/A')})")
                
                if 'already_claimed' in data:
                    already_claimed = "Yes" if data.get('already_claimed', True) else "No"
                    info_log(f"Account {account_number}: Tournaments: {', '.join(tournament_info)}. Already claimed: {already_claimed}")
            
            return data
        except Exception as e:
            error_log(f'Error getting active tournaments: {str(e)}')
            return None

    def claim_tournament_rewards(self, token, wallet_address, account_number, tournament_ids):
        try:
            privy_id_token = None
            for cookie in self.session.cookies:
                if cookie.name == 'privy-id-token':
                    privy_id_token = cookie.value
                    break
            
            auth_token = privy_id_token if privy_id_token else token
            
            headers = {
                'Accept': 'application/json, text/plain, */*',
                'Authorization': f'Bearer {auth_token}',
                'Origin': 'https://monad.fantasy.top',
                'Referer': 'https://monad.fantasy.top/',
                'Content-Length': '0',
                'User-Agent': self.user_agent,
                'Priority': 'u=1, i',
                'Sec-Ch-Ua': '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
                'Sec-Ch-Ua-Mobile': '?0',
                'Sec-Ch-Ua-Platform': '"Windows"',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-site'
            }

            if isinstance(tournament_ids, list):
                tournament_ids_str = ",".join(tournament_ids)
            else:
                tournament_ids_str = tournament_ids

            debug_log(f"Claiming tournament rewards for account {account_number}: {tournament_ids_str}")
            
            response = self.session.post(
                f'https://secret-api.fantasy.top/rewards/tournament-rewards-claim/{tournament_ids_str}',
                headers=headers,
                data="",
                proxies=self.proxies,
                timeout=15
            )
            
            if response.status_code == 401 and auth_token == privy_id_token and token:
                auth_token = token
                headers['Authorization'] = f'Bearer {auth_token}'
                debug_log(f"Retrying claim with different token for account {account_number}")
                
                response = self.session.post(
                    f'https://secret-api.fantasy.top/rewards/tournament-rewards-claim/{tournament_ids_str}',
                    headers=headers,
                    data="",
                    proxies=self.proxies,
                    timeout=15
                )
            
            debug_log(f"Tournament claim response status: {response.status_code} for account {account_number}")
            
            if response.status_code == 400:
                try:
                    response_data = response.json()
                    info_log(f"Account {account_number}: Tournament rewards already claimed")
                    
                    self._clean_rewards_info(wallet_address)
                    
                    return {"status": "already_claimed", "message": "Tournament rewards were already claimed"}
                except Exception as e:
                    error_log(f"Error processing 400 response: {str(e)}")
                    return False
            
            if response.status_code not in [200, 201]:
                error_log(f"Failed to claim tournament rewards: {response.status_code}")
                try:
                    response_data = response.json()
                    error_log(f"Error details: {response_data}")
                except:
                    error_log(f"Response text: {response.text[:200]}")
                return False
            
            data = response.json()
            debug_log(f"Tournament claim response data: {data}")
            
            if "claimed" in data:
                rewards = data.get("claimed", {})
                rewards_str = ", ".join([f"{k}: {v}" for k, v in rewards.items()])
                success_log(f"Successfully claimed tournament rewards for account {account_number}: {rewards_str}")
                
                self._update_account_stats_after_claim(wallet_address, rewards)
                
                return data
            else:
                info_log(f"Unexpected response format from tournament reward claim: {data}")
                return False
                
        except Exception as e:
            error_log(f'Error claiming tournament rewards: {str(e)}')
            return False

    def _clean_rewards_info(self, wallet_address):
        try:
            result_file = self.config['app']['result_file']
            if not os.path.exists(result_file):
                return
                
            lines = []
            updated = False
            
            with open(result_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if wallet_address in line:
                        parts = line.strip().split(':')
                        
                        filtered_parts = []
                        for part in parts:
                            if not part.startswith('tournament_rewards='):
                                filtered_parts.append(part)
                        
                        parts = filtered_parts
                        line = ':'.join(parts) + '\n'
                        updated = True
                    
                    lines.append(line)
            
            if updated:
                with open(result_file, 'w', encoding='utf-8') as f:
                    f.writelines(lines)
                    debug_log(f"Cleaned tournament rewards info for {wallet_address}")
        
        except Exception as e:
            error_log(f"Error cleaning rewards info: {str(e)}")

    def _update_account_stats_after_claim(self, wallet_address, claimed_rewards):
        try:
            result_file = self.config['app']['result_file']
            if not os.path.exists(result_file):
                return
                
            lines = []
            updated = False
            
            with open(result_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if wallet_address in line:
                        parts = line.strip().split(':')
                        
                        if 'FAN' in claimed_rewards:
                            fan_points = claimed_rewards['FAN']
                            for i, part in enumerate(parts):
                                if part.startswith('fantasy_points='):
                                    try:
                                        current_points = int(part.split('=')[1])
                                        parts[i] = f"fantasy_points={current_points + fan_points}"
                                        updated = True
                                    except (ValueError, IndexError):
                                        pass
                        
                        if 'FRAGMENT' in claimed_rewards:
                            fragments = claimed_rewards['FRAGMENT']
                            for i, part in enumerate(parts):
                                if part.startswith('fragments='):
                                    try:
                                        current_fragments = int(part.split('=')[1])
                                        parts[i] = f"fragments={current_fragments + fragments}"
                                        updated = True
                                    except (ValueError, IndexError):
                                        pass
                        
                        if 'WHITELIST_TICKET' in claimed_rewards:
                            whitelist_tickets = claimed_rewards['WHITELIST_TICKET']
                            for i, part in enumerate(parts):
                                if part.startswith('whitelist_tickets='):
                                    try:
                                        current_tickets = int(part.split('=')[1])
                                        parts[i] = f"whitelist_tickets={current_tickets + whitelist_tickets}"
                                        updated = True
                                    except (ValueError, IndexError):
                                        pass
                        
                        filtered_parts = []
                        for part in parts:
                            if not part.startswith('tournament_rewards='):
                                filtered_parts.append(part)
                        
                        parts = filtered_parts
                        
                        line = ':'.join(parts) + '\n'
                    
                    lines.append(line)
            
            if updated:
                with open(result_file, 'w', encoding='utf-8') as f:
                    f.writelines(lines)
                    debug_log(f"Updated account stats after tournament reward claim for {wallet_address}")
        
        except Exception as e:
            error_log(f"Error updating account stats after tournament reward claim: {str(e)}")

    def claim_other_rewards(self, token, wallet_address, account_number, reward_id):
        try:
            privy_id_token = None
            for cookie in self.session.cookies:
                if cookie.name == 'privy-id-token':
                    privy_id_token = cookie.value
                    break
            
            auth_token = privy_id_token if privy_id_token else token
            
            headers = {
                'Accept': 'application/json, text/plain, */*',
                'Authorization': f'Bearer {auth_token}',
                'Origin': 'https://monad.fantasy.top',
                'Referer': 'https://monad.fantasy.top/',
                'Content-Length': '0',
                'User-Agent': self.user_agent,
                'Priority': 'u=1, i',
                'Sec-Ch-Ua': '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
                'Sec-Ch-Ua-Mobile': '?0',
                'Sec-Ch-Ua-Platform': '"Windows"',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-site'
            }

            response = self.session.post(
                f'https://secret-api.fantasy.top/rewards/rewards-claim/{reward_id}',
                headers=headers,
                data="",
                proxies=self.proxies,
                timeout=15
            )
            
            if response.status_code == 401 and auth_token == privy_id_token and token:
                auth_token = token
                headers['Authorization'] = f'Bearer {auth_token}'
                
                response = self.session.post(
                    f'https://secret-api.fantasy.top/rewards/rewards-claim/{reward_id}',
                    headers=headers,
                    data="",
                    proxies=self.proxies,
                    timeout=15
                )
            
            if response.status_code in [200, 201]:
                success_log(f"Successfully claimed other reward {reward_id} for account {account_number}")
                return True
            
            error_log(f"Failed to claim other reward {reward_id}: {response.status_code}")
            return False
                
        except Exception as e:
            error_log(f"Error claiming other reward: {str(e)}")
            return False

    def check_other_rewards(self, token, wallet_address, account_number):
        try:
            privy_id_token = None
            for cookie in self.session.cookies:
                if cookie.name == 'privy-id-token':
                    privy_id_token = cookie.value
                    break
            
            auth_token = privy_id_token if privy_id_token else token
            
            headers = {
                'Accept': 'application/json, text/plain, */*',
                'Authorization': f'Bearer {auth_token}',
                'Origin': 'https://monad.fantasy.top',
                'Referer': 'https://monad.fantasy.top/',
                'User-Agent': self.user_agent,
                'sec-ch-ua': '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"'
            }

            response = self.session.get(
                'https://secret-api.fantasy.top/player/player-rewards',
                headers=headers,
                proxies=self.proxies,
                timeout=10
            )
            
            if response.status_code == 401 and auth_token == privy_id_token and token:
                auth_token = token
                headers['Authorization'] = f'Bearer {auth_token}'
                response = self.session.get(
                    'https://secret-api.fantasy.top/player/player-rewards',
                    headers=headers,
                    proxies=self.proxies,
                    timeout=10
                )
            
            if response.status_code != 200:
                error_log(f"Failed to check other rewards: {response.status_code}")
                return False
            
            data = response.json()
            other_rewards = data.get('otherRewards', [])
            
            if not other_rewards:
                debug_log(f"No other rewards found for account {account_number}")
                return False
            
            success_log(f"Found {len(other_rewards)} other rewards for account {account_number}")
            
            claimed_rewards = 0
            for reward in other_rewards:
                reward_id = reward.get('id')
                reward_type = reward.get('type', 'UNKNOWN')
                reward_amount = reward.get('amount', '0')
                
                if not reward_id:
                    continue
                    
                info_log(f"Account {account_number}: Found reward {reward_type}({reward_amount}), ID: {reward_id}")
                
                claim_result = self.claim_other_rewards(token, wallet_address, account_number, reward_id)
                if claim_result:
                    claimed_rewards += 1
                    self._update_account_stats_after_reward_claim(wallet_address, reward_type, reward_amount)
                
                # Add a small delay between claims to avoid rate limiting
                import time
                time.sleep(1)
            
            if claimed_rewards > 0:
                success_log(f"Successfully claimed {claimed_rewards} other rewards for account {account_number}")
                return True
            return False
                
        except Exception as e:
            error_log(f"Error checking other rewards: {str(e)}")
            return False

    def _update_account_stats_after_reward_claim(self, wallet_address, reward_type, reward_amount):
        try:
            result_file = self.config['app']['result_file']
            if not os.path.exists(result_file):
                return
                
            lines = []
            updated = False
            
            with open(result_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if wallet_address in line:
                        parts = line.strip().split(':')
                        
                        if reward_type == 'FAN':
                            amount = int(reward_amount)
                            for i, part in enumerate(parts):
                                if part.startswith('fantasy_points='):
                                    try:
                                        current_points = int(part.split('=')[1])
                                        parts[i] = f"fantasy_points={current_points + amount}"
                                        updated = True
                                    except (ValueError, IndexError):
                                        pass
                        
                        elif reward_type == 'FRAGMENT':
                            amount = int(reward_amount)
                            for i, part in enumerate(parts):
                                if part.startswith('fragments='):
                                    try:
                                        current_fragments = int(part.split('=')[1])
                                        parts[i] = f"fragments={current_fragments + amount}"
                                        updated = True
                                    except (ValueError, IndexError):
                                        pass
                        
                        elif reward_type == 'WHITELIST_TICKET':
                            amount = int(reward_amount)
                            for i, part in enumerate(parts):
                                if part.startswith('whitelist_tickets='):
                                    try:
                                        current_tickets = int(part.split('=')[1])
                                        parts[i] = f"whitelist_tickets={current_tickets + amount}"
                                        updated = True
                                    except (ValueError, IndexError):
                                        pass
                        
                        line = ':'.join(parts) + '\n'
                    
                    lines.append(line)
            
            if updated:
                with open(result_file, 'w', encoding='utf-8') as f:
                    f.writelines(lines)
                    debug_log(f"Updated account stats after reward claim for {wallet_address}: {reward_type}({reward_amount})")
        
        except Exception as e:
            error_log(f"Error updating account stats after reward claim: {str(e)}")

    def fragment_roulette(self, token, wallet_address, account_number):
        try:
            privy_id_token = None
            for cookie in self.session.cookies:
                if cookie.name == 'privy-id-token':
                    privy_id_token = cookie.value
                    break
            
            auth_token = privy_id_token if privy_id_token else token
            
            player_data = None
            fragments = 0
            
            headers = {
                'Accept': 'application/json, text/plain, */*',
                'Authorization': f'Bearer {auth_token}',
                'Origin': 'https://monad.fantasy.top',
                'Referer': 'https://monad.fantasy.top/',
                'User-Agent': self.user_agent
            }
            
            response = self.session.get(
                f'https://secret-api.fantasy.top/player/basic-data/{wallet_address}',
                headers=headers,
                proxies=self.proxies,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                if 'players_by_pk' in data:
                    player_data = data['players_by_pk']
                    fragments = int(player_data.get('fragments', 0))
                    
                    if fragments < self.config['fragment_roulette']['min_fragments']:
                        info_log(f"Account {account_number} has {fragments} fragments, need {self.config['fragment_roulette']['min_fragments']} for roulette. Skipping.")
                        return False
            else:
                try:
                    with open(self.config['app']['result_file'], 'r', encoding='utf-8') as f:
                        for line in f:
                            if wallet_address in line:
                                parts = line.strip().split(':')
                                for part in parts:
                                    if part.startswith('fragments='):
                                        try:
                                            fragments = int(part.split('=')[1])
                                            if fragments < self.config['fragment_roulette']['min_fragments']:
                                                info_log(f"Account {account_number} has {fragments} fragments, need {self.config['fragment_roulette']['min_fragments']} for roulette. Skipping.")
                                                return False
                                        except ValueError:
                                            pass
                except Exception as e:
                    error_log(f"Error reading fragments from result file: {str(e)}")
                    return False
                    
            headers = {
                'Accept': 'application/json, text/plain, */*',
                'Authorization': f'Bearer {auth_token}',
                'Origin': 'https://monad.fantasy.top',
                'Referer': 'https://monad.fantasy.top/',
                'Content-Length': '0',
                'User-Agent': self.user_agent
            }

            response = self.session.post(
                'https://secret-api.fantasy.top/rewards/buy-fragment-roulette',
                headers=headers,
                data="",
                proxies=self.proxies,
                timeout=10
            )
            
            if response.status_code == 401 and auth_token == privy_id_token and token:
                auth_token = token
                headers['Authorization'] = f'Bearer {auth_token}'
                response = self.session.post(
                    'https://secret-api.fantasy.top/rewards/buy-fragment-roulette',
                    headers=headers,
                    data="",
                    proxies=self.proxies,
                    timeout=10
                )
            
            if response.status_code not in [200, 201]:
                if response.status_code == 400:
                    info_log(f"Account {account_number} doesn't have enough fragments for roulette")
                    return False
                
                error_log(f"Failed to spin fragment roulette: {response.status_code}")
                return False
            
            data = response.json()
            
            if data.get("success", False) and "selectedPrize" in data:
                prize = data["selectedPrize"]
                prize_type = prize.get("type", "Unknown")
                prize_text = prize.get("text", "Unknown")
                
                success_log(f"Account {account_number}: Fragment roulette prize: {prize_type}({prize_text})")
                
                if prize_type == "PACK":
                    self._update_pack_info(wallet_address, prize_type, prize_text)
                
                return data
            
            error_log(f"Unexpected response from fragment roulette: {data}")
            return False
            
        except Exception as e:
            error_log(f'Error with fragment roulette: {str(e)}')
            return False

    def _update_pack_info(self, wallet_address, pack_type, pack_count):
        try:
            result_file = self.config['app']['result_file']
            
            if not os.path.exists(result_file):
                return
                
            lines = []
            with open(result_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if wallet_address in line:
                        parts = line.strip().split(':')
                        pack_info = f"packs={pack_type}({pack_count})"
                        
                        has_pack_info = False
                        for i, part in enumerate(parts):
                            if part.startswith('packs='):
                                parts[i] = pack_info
                                has_pack_info = True
                                break
                        
                        if not has_pack_info:
                            parts.append(pack_info)
                        
                        line = ':'.join(parts) + '\n'
                    
                    lines.append(line)
            
            with open(result_file, 'w', encoding='utf-8') as f:
                f.writelines(lines)
                
        except Exception as e:
            error_log(f"Error updating pack info: {str(e)}")


    def daily_claim(self, token, wallet_address, account_number):
        max_retries = 2
        retry_delay = 1
        
        privy_id_token = None
        for cookie in self.session.cookies:
            if cookie.name == 'privy-id-token':
                privy_id_token = cookie.value
                break
        
        auth_token = privy_id_token if privy_id_token else token
        
        headers = {
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Authorization': f'Bearer {auth_token}',
            'Origin': 'https://monad.fantasy.top',
            'Referer': 'https://monad.fantasy.top/',
            'Content-Length': '0',
            'User-Agent': self.user_agent,
            'Priority': 'u=1, i',
            'Sec-Ch-Ua': '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site'
        }

        while True:
            try:
                response = self.session.post(
                    'https://secret-api.fantasy.top/quest/daily-claim',
                    headers=headers,
                    data="",
                    proxies=self.proxies,
                    timeout=10
                )
                
                if response.status_code == 500:
                    info_log(f'Daily claim returned 500 for account {account_number}, retrying...')
                    sleep(retry_delay)
                    continue
                    
                if response.status_code == 405:
                    response = self.session.get(
                        'https://secret-api.fantasy.top/quest/daily-claim',
                        headers=headers,
                        proxies=self.proxies,
                        timeout=10
                    )

                if response.status_code == 201:
                    data = response.json()
                    if data.get("success", False):
                        self.account_storage.update_account(
                            wallet_address,
                            self.account_storage.get_account_data(wallet_address)["private_key"],
                            last_daily_claim=datetime.now(pytz.UTC).isoformat()
                        )
                        daily_streak = data.get("dailyQuestStreak", "N/A")
                        current_day = data.get("dailyQuestProgress", "N/A")
                        prize = data.get("selectedPrize", {})
                        prize_type = prize.get("type", "Unknown")
                        prize_amount = prize.get("text", "Unknown")
                        
                        success_log(f'Account {account_number} ({wallet_address}): '
                                  f'{Fore.GREEN}STREAK:{daily_streak}{Fore.RESET}, '
                                  f'{Fore.GREEN}DAY:{current_day}{Fore.RESET}, '
                                  f'{Fore.GREEN}PRIZE:{prize_type}({prize_amount}){Fore.RESET}')
                        return True
                    else:
                        next_due_time = data.get("nextDueTime")
                        if next_due_time:
                            next_due_datetime = parser.parse(next_due_time)
                            moscow_tz = pytz.timezone('Europe/Moscow')
                            current_time = datetime.now(moscow_tz)
                            time_difference = next_due_datetime.replace(tzinfo=pytz.UTC) - current_time.replace(tzinfo=moscow_tz)
                            hours, remainder = divmod(time_difference.seconds, 3600)
                            minutes, _ = divmod(remainder, 60)
                            success_log(f"Account {account_number}: {wallet_address}: Next claim available in {hours}h {minutes}m")
                        return True

                if response.status_code == 401:
                    if auth_token == privy_id_token and token:
                        auth_token = token
                        headers['Authorization'] = f'Bearer {auth_token}'
                        response = self.session.post(
                            'https://secret-api.fantasy.top/quest/daily-claim',
                            headers=headers,
                            data="",
                            proxies=self.proxies,
                            timeout=10
                        )
                        
                        if response.status_code == 201:
                            return True
                            
                    account_data = self.account_storage.get_account_data(wallet_address)
                    if account_data:
                        auth_data = self.login(account_data["private_key"], wallet_address, account_number)
                        if auth_data:
                            new_token = self.get_token(auth_data, wallet_address, account_number)
                            if new_token:
                                return self.daily_claim(new_token, wallet_address, account_number)
                    return False

                error_log(f'Daily claim failed for account {account_number}: {response.status_code}')
                return False

            except Exception as e:
                error_log(f'Daily claim error for account {account_number}: {str(e)}')
                return False

    def onboarding_quest_claim(self, token, wallet_address, account_number, quest_id):
        try:
            privy_id_token = None
            for cookie in self.session.cookies:
                if cookie.name == 'privy-id-token':
                    privy_id_token = cookie.value
                    break
                    
            auth_token = privy_id_token if privy_id_token else token
            
            headers = {
                'Accept': 'application/json, text/plain, */*',
                'Authorization': f'Bearer {auth_token}',
                'Origin': 'https://monad.fantasy.top',
                'Referer': 'https://monad.fantasy.top/',
                'Content-Length': '0',
                'User-Agent': self.user_agent,
                'Priority': 'u=1, i',
                'Sec-Ch-Ua': '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
                'Sec-Ch-Ua-Mobile': '?0',
                'Sec-Ch-Ua-Platform': '"Windows"',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-site'
            }

            response = self.session.post(
                f'https://secret-api.fantasy.top/quest/onboarding/complete/{quest_id}',
                headers=headers,
                data="",
                proxies=self.proxies,
                timeout=10
            )

            if response.status_code == 401 and auth_token == privy_id_token and token:
                auth_token = token
                headers['Authorization'] = f'Bearer {auth_token}'
                response = self.session.post(
                    f'https://secret-api.fantasy.top/quest/onboarding/complete/{quest_id}',
                    headers=headers,
                    data="",
                    proxies=self.proxies,
                    timeout=10
                )
                
            if response.status_code == 401:
                account_data = self.account_storage.get_account_data(wallet_address)
                if account_data:
                    auth_data = self.login(account_data["private_key"], wallet_address, account_number)
                    if auth_data:
                        new_token = self.get_token(auth_data, wallet_address, account_number)
                        if new_token:
                            return self.onboarding_quest_claim(new_token, wallet_address, account_number, quest_id)

            if response.status_code == 201:
                return True

            error_log(f'Onboarding quest claim failed for account {account_number}: {response.status_code}')
            return False

        except Exception as e:
            error_log(f'Onboarding quest claim error for account {account_number}: {str(e)}')
            return False

    def _create_sign_message(self, wallet_address, nonce):
        lines = []
        lines.append(f"monad.fantasy.top wants you to sign in with your Ethereum account:")
        lines.append(f"{wallet_address}")
        lines.append("")
        lines.append(f"By signing, you are proving you own this wallet and logging in. This does not initiate a transaction or cost any fees.")
        lines.append("")
        lines.append(f"URI: https://monad.fantasy.top")
        lines.append(f"Version: 1")
        lines.append(f"Chain ID: 1")
        lines.append(f"Nonce: {nonce}")
        lines.append(f"Issued At: {datetime.utcnow().isoformat()}Z")
        lines.append(f"Resources:")
        lines.append(f"- https://privy.io")
        
        return "\n".join(lines)

    def _sign_message(self, message, private_key):
        return self.web3.eth.account.sign_message(
            encode_defunct(message.encode('utf-8')),
            private_key
        )

    def quest_claim(self, token, wallet_address, account_number, quest_id):
        try:
            headers = {
                'Accept': 'application/json, text/plain, */*',
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
                'Origin': 'https://monad.fantasy.top',
                'Referer': 'https://monad.fantasy.top/',
                'User-Agent': self.user_agent
            }

            payload = {
                "playerId": wallet_address,
                "questThresholdId": quest_id
            }

            response = self.session.post(
                f'{self.base_url}/quest/claim',
                json=payload,
                headers=headers,
                proxies=self.proxies
            )

            if response.status_code == 201 or response.status_code == 200:
                success_log(f'Successfully claimed quest {quest_id} for account {account_number}: {wallet_address}')
                return True

            elif response.status_code == 429:
                info_log(f'Rate limit on quest claim for account {account_number}, retrying...')
                return "429"

            elif response.status_code == 401:
                account_data = self.account_storage.get_account_data(wallet_address)
                if account_data:
                    auth_data = self.login(account_data["private_key"], wallet_address, account_number)
                    if auth_data:
                        new_token = self.get_token(auth_data, wallet_address, account_number)
                        if new_token:
                            return self.quest_claim(new_token, wallet_address, account_number, quest_id)

            error_log(f'Quest claim failed for account {account_number}: {response.status_code}')
            return False

        except Exception as e:
            error_log(f'Quest claim error for account {account_number}: {str(e)}')
            return False

    def fragments_claim(self, token, wallet_address, account_number, fragment_id):
        try:
            headers = {
                'Accept': 'application/json, text/plain, */*',
                'Authorization': f'Bearer {token}',
                'Origin': 'https://monad.fantasy.top',
                'Referer': 'https://monad.fantasy.top/',
                'Content-Length': '0'
            }

            response = self.session.post(
                f'{self.base_url}/quest/onboarding/complete/{fragment_id}',
                headers=headers,
                data="",
                proxies=self.proxies,
                timeout=10
            )

            if response.status_code == 401:
                account_data = self.account_storage.get_account_data(wallet_address)
                if account_data:
                    auth_data = self.login(account_data["private_key"], wallet_address, account_number)
                    if auth_data:
                        new_token = self.get_token(auth_data, wallet_address, account_number)
                        if new_token:
                            return self.fragments_claim(new_token, wallet_address, account_number, fragment_id)

            if response.status_code == 201:
                success_log(f'Successfully claimed fragment {fragment_id} for account {account_number}: {wallet_address}')
                return True

            error_log(f'Fragment claim failed for account {account_number}: {response.status_code}')
            return False

        except Exception as e:
            error_log(f'Fragment claim error for account {account_number}: {str(e)}')
            return False


    def info(self, token, wallet_address, account_number):
        try:
            privy_id_token = None
            for cookie in self.session.cookies:
                if cookie.name == 'privy-id-token':
                    privy_id_token = cookie.value
                    break
            
            auth_token = privy_id_token if privy_id_token else token
            
            headers = {
                'Accept': 'application/json, text/plain, */*',
                'Authorization': f'Bearer {auth_token}',
                'Origin': 'https://monad.fantasy.top',
                'Referer': 'https://monad.fantasy.top/',
                'User-Agent': self.user_agent,
                'sec-ch-ua': '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"'
            }

            url = f'https://secret-api.fantasy.top/player/basic-data/{wallet_address}'
            
            response = self.session.get(
                url,
                headers=headers,
                proxies=self.proxies,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                
                if 'players_by_pk' not in data:
                    error_log(f"Unexpected response structure for account {account_number}: missing 'players_by_pk'")
                    return False
                    
                player_data = data.get('players_by_pk', {})
                rewards_status = len(data.get('rewards', []))
                
                fantasy_points = player_data.get('fantasy_points', 0)
                fragments = player_data.get('fragments', 0)
                is_onboarding_done = bool(player_data.get('is_onboarding_done', False))
                portfolio_value = str(player_data.get('portfolio_value', '0'))
                whitelist_tickets = int(player_data.get('whitelist_tickets', 0))
                number_of_cards = int(player_data.get('number_of_cards', 0))
                
                try:
                    total_gliding_score = float(player_data.get('total_gliding_score', 0))
                except (ValueError, TypeError):
                    total_gliding_score = 0.0
                    
                gold_value = str(player_data.get('gold', '0'))
                
                has_tournament_rewards = False
                tournament_rewards_data = ""
                tournament_rewards = self.check_tournament_rewards(token, wallet_address, account_number)
                if tournament_rewards and 'tournamentRewards' in tournament_rewards:
                    rewards_list = tournament_rewards.get('tournamentRewards', [])
                    if rewards_list:
                        has_tournament_rewards = True
                        rewards_details = []
                        for reward in rewards_list:
                            tournament_num = reward.get('tournament_number', 'Unknown')
                            reward_items = reward.get('rewards', [])
                            reward_texts = []
                            for r in reward_items:
                                reward_texts.append(f"{r.get('type', 'Unknown')}({r.get('amount', 0)})")
                            rewards_details.append(f"Tournament{tournament_num}:{','.join(reward_texts)}")
                        tournament_rewards_data = "|".join(rewards_details)
                        
                        tournament_data = self.get_active_tournaments(token, wallet_address, account_number)
                        if tournament_data and not tournament_data.get('already_claimed', True):
                            tournament_ids = [t.get('id') for t in tournament_data.get('tournaments', [])]
                            if tournament_ids:
                                claim_result = self.claim_tournament_rewards(token, wallet_address, account_number, tournament_ids)
                                if claim_result and 'claimed' in claim_result:
                                    rewards = claim_result.get('claimed', {})
                                    rewards_str = ", ".join([f"{k}: {v}" for k, v in rewards.items()])
                                    success_log(f"Account {account_number}: Claimed tournament rewards: {rewards_str}")
                
                has_pending_packs = False
                pending_packs_data = ""
                pending_packs = self.check_pending_packs(token, wallet_address, account_number)
                if pending_packs and pending_packs.get('hasPending', False):
                    has_pending_packs = True
                    fragments_count = pending_packs.get('fragments', 0)
                    claims = pending_packs.get('claims', [])
                    
                    pending_claims = []
                    for claim in claims:
                        if 'type' in claim and 'amount' in claim:
                            pending_claims.append(f"{claim['type']}({claim['amount']})")
                    
                    if pending_claims:
                        pending_packs_data = "pending_packs=" + ",".join(pending_claims)
                    else:
                        pending_packs_data = f"pending_packs=UNKNOWN({fragments_count})"
                
                tournament_data = {}
                try:
                    active_tournaments = self.get_active_tournaments(token, wallet_address, account_number)
                    if active_tournaments and not active_tournaments.get('already_claimed', True):
                        tournament_player_info = active_tournaments.get('tournament_player_info', [])
                        for t_info in tournament_player_info:
                            t_id = t_info.get('tournament_id', '')
                            best_rank = t_info.get('best_rank', 0)
                            deck_count = t_info.get('nb_of_deck_played', 0)
                            t_name = next((t.get('name', 'Unknown') for t in active_tournaments.get('tournaments', []) 
                                          if t.get('id') == t_id), 'Unknown')
                            tournament_data[t_id] = {
                                'name': t_name,
                                'best_rank': best_rank,
                                'deck_count': deck_count
                            }
                except Exception as e:
                    debug_log(f"Error getting tournament data: {str(e)}")
                
                result_file = self.config['app']['result_file']
                existing_data = {}

                if os.path.exists(result_file):
                    with open(result_file, 'r', encoding='utf-8') as f:
                        for line in f:
                            parts = line.strip().split(':')
                            if len(parts) > 0:
                                addr = parts[0]
                                existing_data[addr] = line.strip()

                result_parts = [
                    f"{wallet_address}",
                    f"stars={player_data.get('stars', 0)}",
                    f'gold="{gold_value}"',
                    f"portfolio_value={portfolio_value}",
                    f"number_of_cards={number_of_cards}",
                    f"fantasy_points={fantasy_points}",
                    f"fragments={fragments}",
                    f"onboarding_done={is_onboarding_done}",
                    f"whitelist_tickets={whitelist_tickets}",
                    f"gliding_score={total_gliding_score:.2f}",
                    f"rewards={rewards_status}"
                ]
                
                if has_tournament_rewards:
                    result_parts.append(f"tournament_rewards={tournament_rewards_data}")
                
                if has_pending_packs:
                    result_parts.append(pending_packs_data)
                
                if tournament_data:
                    tournament_infos = []
                    for t_id, t_info in tournament_data.items():
                        tournament_infos.append(f"{t_info['name']}(Rank:{t_info['best_rank']},Decks:{t_info['deck_count']})")
                    if tournament_infos:
                        result_parts.append(f"active_tournaments={','.join(tournament_infos)}")
                
                if wallet_address in existing_data:
                    for part in existing_data[wallet_address].split(':'):
                        if part.startswith('packs='):
                            result_parts.append(part)
                            break
                
                result_line = ":".join(result_parts)

                os.makedirs("logs", exist_ok=True)
                
                if wallet_address not in existing_data:
                    with open(result_file, 'a+', encoding='utf-8') as f:
                        f.write(result_line + '\n')
                else:
                    all_lines = []
                    with open(result_file, 'r', encoding='utf-8') as read_f:
                        for line in read_f:
                            if line.strip().startswith(wallet_address + ":"):
                                all_lines.append(result_line + '\n')
                            else:
                                all_lines.append(line)
                    
                    with open(result_file, 'w', encoding='utf-8') as write_f:
                        write_f.writelines(all_lines)

                success_log(
                    f"Info collected for account {account_number}: {wallet_address} | "
                    f"fMON:{fantasy_points}, Cards:{number_of_cards}, "
                    f"Portfolio:{portfolio_value}, Onboarding:{is_onboarding_done}"
                )
                return True
                    
            elif response.status_code == 429:
                info_log(f'Rate limit on info check for account {account_number}, retrying...')
                return "429"
            elif response.status_code == 401:
                if auth_token == privy_id_token and token:
                    auth_token = token
                    headers['Authorization'] = f'Bearer {auth_token}'
                    retry_response = self.session.get(
                        url,
                        headers=headers,
                        proxies=self.proxies,
                        timeout=10
                    )
                    
                    if retry_response.status_code == 200:
                        return self.info(token, wallet_address, account_number)
                
                account_data = self.account_storage.get_account_data(wallet_address)
                if account_data:
                    auth_data = self.login(account_data["private_key"], wallet_address, account_number)
                    if isinstance(auth_data, str) and "429" in auth_data:
                        return "429"
                    if auth_data:
                        new_token = self.get_token(auth_data, wallet_address, account_number)
                        if new_token:
                            return self.info(new_token, wallet_address, account_number)

            error_log(f'Error getting info for account {account_number}: {response.status_code}')
            return False

        except Exception as e:
            error_log(f"Error in info function for account {account_number}: {str(e)}")
            return False
            
    def get_headers(self, token=None):
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'User-Agent': self.user_agent,
            'Origin': self.base_url,
            'Referer': f'{self.base_url}/'
        }
        if token:
            headers['Authorization'] = f'Bearer {token}'
        return headers

    def check_cookies(self):
        required_cookies = ['privy-token', 'privy-session', 'privy-access-token']
        return all(cookie in self.session.cookies for cookie in required_cookies)

    def check_eth_balance(self, address):
        try:
            balance_wei = self.web3.eth.get_balance(address)
            balance_eth = float(self.web3.from_wei(balance_wei, 'ether'))
            return balance_eth
        except Exception as e:
            error_log(f'Error checking balance for {address}: {str(e)}')
            return 0

    def toggle_free_tactics(self, token, wallet_address, account_number):
        headers = {
            'Accept': 'application/json, text/plain, */*',
            'Authorization': f'Bearer {token}',
            'Origin': self.base_url,
            'Referer': f'{self.base_url}/',
            'User-Agent': self.user_agent
        }

        max_attempts = 15
        delay_between_attempts = 5

        for attempt in range(max_attempts):
            try:
                info_log(f'Toggle attempt {attempt + 1}/{max_attempts} for account {account_number}')
                response = self.session.post(
                    f'{self.base_url}/tactics/toggle-can-play-free-tactics',
                    headers=headers, 
                    proxies=self.proxies
                )
                
                if response.status_code == 201:
                    data = response.json()
                    if data.get('can_play_free_tactics', False):
                        success_log(f'Got TRUE status for account {account_number}: {wallet_address}')
                        return True
                    else:
                        info_log(f'Attempt {attempt + 1}: Status still FALSE for account {account_number}')
                        sleep(delay_between_attempts)
                else:
                    error_log(f'Toggle request failed: {response.status_code}')
                    sleep(delay_between_attempts)

            except Exception as e:
                error_log(f'Toggle attempt {attempt + 1} error: {str(e)}')
                sleep(delay_between_attempts)

        return False

    def wait_for_balance(self, address, required_balance, max_attempts=30, check_delay=3):
        for attempt in range(max_attempts):
            current_balance = self.check_eth_balance(address)
            info_log(f'Balance check attempt {attempt + 1}/{max_attempts} for {address}: {current_balance} ETH')
            
            if current_balance >= required_balance:
                success_log(f'Required balance reached for {address}: {current_balance} ETH')
                return True
                
            info_log(f'Waiting for balance... Current: {current_balance} ETH, Required: {required_balance} ETH')
            sleep(check_delay)
        
        error_log(f'Balance never reached required amount for {address}')
        return False

    def transfer_eth(self, from_private_key, from_address, to_address):
        max_retries = 3
        base_gas_reserve = 0.000003
        
        for attempt in range(max_retries):
            try:
                balance_wei = self.web3.eth.get_balance(from_address)
                balance_eth = float(self.web3.from_wei(balance_wei, 'ether'))
                
                current_gas_reserve = base_gas_reserve * (attempt + 1)
                
                transfer_amount = balance_eth - current_gas_reserve
                
                if transfer_amount <= 0:
                    error_log(f'Insufficient balance for transfer from {from_address} (attempt {attempt + 1})')
                    continue

                if transfer_amount < self.config['app']['min_balance']:
                    error_log(f'Transfer amount too small: {transfer_amount} ETH (attempt {attempt + 1})')
                    continue

                transaction = {
                    'nonce': self.web3.eth.get_transaction_count(from_address),
                    'to': self.web3.to_checksum_address(to_address),
                    'value': self.web3.to_wei(transfer_amount, 'ether'),
                    'gas': 21000,
                    'maxFeePerGas': self.web3.eth.gas_price * (2 + attempt),
                    'maxPriorityFeePerGas': self.web3.to_wei(0.00000005 * (1 + attempt), 'gwei'),
                    'type': 2,
                    'chainId': 81457
                }

                signed_txn = self.web3.eth.account.sign_transaction(transaction, from_private_key)
                tx_hash = self.web3.eth.send_raw_transaction(signed_txn.rawTransaction)
                
                success_log(f'Sending {transfer_amount} ETH from {from_address} to {to_address} (attempt {attempt + 1})')
                success_log(f'TX Hash: {tx_hash.hex()}')
                
                receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
                if receipt['status'] == 1:
                    success_log(f'Transfer confirmed: {tx_hash.hex()}')
                    return True
                else:
                    error_log(f'Transfer failed: {tx_hash.hex()} (attempt {attempt + 1})')
                    continue

            except Exception as e:
                error_log(f'Transfer error (attempt {attempt + 1}): {str(e)}')
                if attempt < max_retries - 1:
                    sleep(2)
                continue
        
        return False

    def _make_transfer_to_next(self, account_number: int, total_accounts: int, wallet_address: str, private_key: str):
        max_transfer_attempts = 5
        transfer_delay = 3
        
        next_account = (account_number % total_accounts) + 1
        
        with open(self.config['app']['keys_file'], 'r') as f:
            lines = f.readlines()
            if next_account <= len(lines):
                _, target_address = lines[next_account - 1].strip().split(':')
                
                for attempt in range(max_transfer_attempts):
                    try:
                        transfer_success = self.transfer_eth(private_key, wallet_address, target_address)
                        if transfer_success:
                            success_log(f'Successfully transferred from account {account_number} to {next_account}')
                            return True
                        
                        error_log(f'Transfer attempt {attempt + 1} failed, retrying...')
                        sleep(transfer_delay)
                        
                    except Exception as e:
                        error_log(f'Transfer attempt {attempt + 1} error: {str(e)}')
                        if attempt < max_transfer_attempts - 1:
                            sleep(transfer_delay)
                        continue
                
                error_log(f'All transfer attempts failed for account {account_number} to {next_account}')
        return False

    def tactic_claim(self, token, wallet_address, account_number, total_accounts, old_account_flag):
        success = False
        try:
            if old_account_flag:
                private_key = self.account_storage.get_account_data(wallet_address)["private_key"]
                balance = self.check_eth_balance(wallet_address)
                
                if balance < self.config['app']['min_balance']:
                    info_log(f'Insufficient balance ({balance} ETH) for account {account_number}: {wallet_address}')
                    
                    prev_account = account_number - 1 if account_number > 1 else 1
                    with open(self.config['app']['keys_file'], 'r') as f:
                        lines = f.readlines()
                        if prev_account <= len(lines):
                            prev_private_key, prev_address = lines[prev_account - 1].strip().split(':')
                            prev_balance = self.check_eth_balance(prev_address)
                            
                            if prev_balance >= self.config['app']['min_balance']:
                                transfer_success = self.transfer_eth(prev_private_key, prev_address, wallet_address)
                                if not transfer_success or not self.wait_for_balance(wallet_address, self.config['app']['min_balance']):
                                    info_log(f'Failed to transfer or reach required balance for account {account_number}')
                            else:
                                info_log(f'Previous account {prev_account} has insufficient balance: {prev_balance} ETH')

                if not self.toggle_free_tactics(token, wallet_address, account_number):
                    info_log(f'Failed to get TRUE status for account {account_number}')

            headers = {
                'Accept': 'application/json, text/plain, */*',
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {token}',
                'Origin': 'https://monad.fantasy.top',
                'Referer': 'https://monad.fantasy.top/play/tactics'
            }

            register_payload = {"tactic_id": self.config['tactic']['id']}
            register_response = self.session.post(
                f'{self.base_url}/tactics/register',
                json=register_payload,
                headers=headers,
                proxies=self.proxies,
                timeout=15
            )

            if register_response.status_code == 400:
                success_log(f'Already registered in tactic {account_number}')
                success = True
            else:
                try:
                    response_data = register_response.json()
                    if "id" in response_data:
                        success_log(f'Successfully registered in tactic {account_number} with ID: {response_data["id"]}')
                        success = True

                        entry_id = response_data["id"]
                        deck_response = self.session.get(
                            f'{self.base_url}/tactics/entry/{entry_id}/choices',
                            headers=self.get_headers(token),
                            proxies=self.proxies
                        )
                                
                        if deck_response.status_code == 200:
                            deck = deck_response.json()
                            if isinstance(deck, dict) and 'hero_choices' in deck:
                                cards = deck['hero_choices']
                                stars_to_select = self._get_deck_for_account(account_number, total_accounts)

                                used_cards = []
                                hero_choices = []
                                total_stars = 0

                                for stars in stars_to_select:
                                    card = self._select_card_by_stars(stars, cards, used_cards)
                                    if card:
                                        hero_choices.append(card)
                                        total_stars += card['hero_score']['stars']
                                    else:
                                        max_allowed_stars = 24 - total_stars
                                        card = self._get_alternative_card(cards, used_cards, max_allowed_stars)
                                        if card:
                                            hero_choices.append(card)
                                            total_stars += card['hero_score']['stars']

                                if len(hero_choices) == len(stars_to_select) and total_stars <= 24:
                                    save_payload = {
                                        "tacticPlayerId": entry_id,
                                        "heroChoices": hero_choices
                                    }

                                    save_response = self.session.post(
                                        f'{self.base_url}/tactics/save-deck',
                                        json=save_payload,
                                        headers=headers,
                                        proxies=self.proxies
                                    )

                                    if save_response.status_code == 200:
                                        success_log(f'Deck saved for account {account_number}')
                                    else:
                                        info_log(f'Save error {account_number}. Status: {save_response.status_code}')
                except Exception as e:
                    error_log(f'Error processing deck for account {account_number}: {str(e)}')

        except Exception as e:
            error_log(f'Tactic claim error for account {account_number}: {str(e)}')
            success = False
        
        finally:
            if old_account_flag:
                try:
                    self._make_transfer_to_next(account_number, total_accounts, wallet_address, private_key)
                except Exception as e:
                    error_log(f'Transfer error after tactic for account {account_number}: {str(e)}')
            
            return success

    def _get_deck_for_account(self, account_number: int, total_accounts: int):
        accounts_per_deck = math.ceil(total_accounts / len(self.config['tactic']['decks']))
        deck_index = min((account_number - 1) // accounts_per_deck, len(self.config['tactic']['decks']) - 1)
        return self.config['tactic']['decks'][deck_index]

    def _select_card_by_stars(self, stars: int, deck: list, used_cards: list):
        for card in deck:
            if isinstance(card, dict) and 'hero' in card and 'stars' in card['hero']:
                if card['hero']['stars'] == stars and card not in used_cards:
                    used_cards.append(card)
                    return card
        return None

    def _get_alternative_card(self, deck, used_cards, max_stars):
        for card in deck:
            if card not in used_cards and card['hero']['stars'] <= max_stars:
                used_cards.append(card)
                return card
        return None

    def claim_starter_cards(self, token: str, wallet_address: str, account_number: int) -> bool:
        try:
            privy_id_token = None
            for cookie in self.session.cookies:
                if cookie.name == 'privy-id-token':
                    privy_id_token = cookie.value
                    break
            
            auth_token = privy_id_token if privy_id_token else token
            
            monad_web3 = Web3(Web3.HTTPProvider(self.config['monad_rpc']['url']))
            
            contract_address = "0x9077d31a794d81c21b0650974d5f581f4000cd1a"
            contract_method_data = "0x1ff7712f00000000000000000000000000000000000000000000000000000000000000140000000000000000000000000000000000000000000000000000000000000060000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000010000000000000000000000000000000000000000000000000000000000000000"
            
            nonce_response = monad_web3.eth.get_transaction_count(wallet_address, "pending")
            
            gas_price = monad_web3.eth.gas_price
            max_priority_fee = monad_web3.to_wei(1.5, 'gwei')
            max_fee_per_gas = gas_price * 2
            
            transaction = {
                'nonce': nonce_response,
                'to': monad_web3.to_checksum_address(contract_address),
                'value': 0,
                'gas': 550000,
                'maxFeePerGas': max_fee_per_gas,
                'maxPriorityFeePerGas': max_priority_fee,
                'data': contract_method_data,
                'type': 2,
                'chainId': 10143
            }
            
            private_key = self.account_storage.get_account_data(wallet_address)["private_key"]
            
            try:
                account = monad_web3.eth.account.from_key(private_key)
                signed_txn = account.sign_transaction(transaction)
                tx_hash = monad_web3.eth.send_raw_transaction(signed_txn.rawTransaction)
                tx_hash_hex = tx_hash.hex()
                debug_log(f"Transaction sent: {tx_hash_hex}")
                
                receipt = None
                retries = 10
                while retries > 0 and receipt is None:
                    try:
                        receipt = monad_web3.eth.get_transaction_receipt(tx_hash)
                    except Exception:
                        sleep(2)
                        retries -= 1
                
                if receipt and receipt['status'] == 1:
                    success_log(f"Transaction confirmed for account {account_number}: {tx_hash_hex}")
                else:
                    error_log(f"Transaction failed or timed out for account {account_number}")
                    return False
            except Exception as e:
                error_log(f"Error signing or sending transaction for account {account_number}: {str(e)}")
                return False
            
            pack_opening_quest_id = "66387328-ff2a-46a9-acb7-846b466934b6"
            
            headers = {
                'Accept': 'application/json, text/plain, */*',
                'Authorization': f'Bearer {auth_token}',
                'Origin': 'https://monad.fantasy.top',
                'Referer': 'https://monad.fantasy.top/',
                'Content-Length': '0',
                'User-Agent': self.user_agent,
                'Priority': 'u=1, i',
                'Sec-Ch-Ua': '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
                'Sec-Ch-Ua-Mobile': '?0',
                'Sec-Ch-Ua-Platform': '"Windows"',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-site'
            }

            onboarding_response = self.session.post(
                f'https://secret-api.fantasy.top/quest/onboarding/complete/{pack_opening_quest_id}',
                headers=headers,
                data="",
                proxies=self.proxies,
                timeout=15
            )
            
            if onboarding_response.status_code == 401 and auth_token == privy_id_token and token:
                auth_token = token
                headers['Authorization'] = f'Bearer {auth_token}'
                
                onboarding_response = self.session.post(
                    f'https://secret-api.fantasy.top/quest/onboarding/complete/{pack_opening_quest_id}',
                    headers=headers,
                    data="",
                    proxies=self.proxies,
                    timeout=15
                )
            
            if onboarding_response.status_code == 201:
                success_log(f"Successfully claimed starter cards for account {account_number}")
                return True
            
            error_log(f"Failed to complete the pack opening quest: {onboarding_response.status_code}")
            return False
            
        except Exception as e:
            error_log(f"Error claiming starter cards for account {account_number}: {str(e)}")
            return False
