import uuid
from typing import List, Dict, Optional, Tuple
from colorama import Fore
from .utils import error_log, success_log, info_log, debug_log

class TournamentManager:
    def __init__(self, api, config):
        self.api = api
        self.config = config
        self.tournament_types = {
            "bronze": {"max_stars": 18, "name": "Bronze Tournament"},
            "silver": {"max_stars": 23, "name": "Silver Tournament"},
            "gold": {"max_stars": 25, "name": "Gold Tournament"},
            "elite": {"max_stars": float('inf'), "name": "Elite Tournament"}
        }
        
    def fetch_player_cards(self, wallet_address: str, token: str, account_number: int) -> List[Dict]:
        try:
            privy_id_token = None
            for cookie in self.api.session.cookies:
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
                'User-Agent': self.api.user_agent,
                'Priority': 'u=1, i',
                'Sec-Ch-Ua': '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
                'Sec-Ch-Ua-Mobile': '?0',
                'Sec-Ch-Ua-Platform': '"Windows"',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-site'
            }
            
            page = 0
            limit = 100
            cards = []
            
            while True:
                params = {
                    'pagination.page': page,
                    'pagination.limit': limit,
                    'where.heroes.name.contains': '',
                    'where.heroes.handle.contains': '',
                    'where.rarity.in': [1, 2, 3, 4],
                    'orderBy': 'cards_score_desc',
                    'groupCard': 'true',
                    'isProfile': 'true',
                    'isGalleryView': 'false'
                }
                
                response = self.api.session.get(
                    f'https://secret-api.fantasy.top/card/player/{wallet_address}',
                    headers=headers,
                    params=params,
                    proxies=self.api.proxies,
                    timeout=15
                )
                
                if response.status_code == 429:
                    info_log(f"Rate limit hit while fetching cards for account {account_number}, retrying...")
                    continue
                
                if response.status_code == 401:
                    if auth_token == privy_id_token and token:
                        auth_token = token
                        headers['Authorization'] = f'Bearer {auth_token}'
                        continue
                    
                    error_log(f"Authorization failed while fetching cards for account {account_number}")
                    return []
                
                if response.status_code != 200:
                    error_log(f"Failed to fetch cards for account {account_number}: {response.status_code}")
                    return []
                
                data = response.json()
                if not data.get('data'):
                    break
                    
                for card in data['data']:
                    if not card.get('is_in_deck', False):
                        cards.append(card)
                
                meta = data.get('meta', {})
                current_page = meta.get('currentPage', 0)
                last_page = meta.get('lastPage', 0)
                
                if current_page >= last_page:
                    break
                    
                page += 1
            
            success_log(f"Fetched {len(cards)} available cards for account {account_number}")
            return cards
            
        except Exception as e:
            error_log(f"Error fetching cards for account {account_number}: {str(e)}")
            return []
    
    def select_best_cards_for_tournament(self, cards: List[Dict], max_stars: int, used_card_ids: List[str]) -> Tuple[List[Dict], int]:
        available_cards = [card for card in cards if card['id'] not in used_card_ids]
        
        if len(available_cards) < 5:
            return [], 0
            
        sorted_cards = sorted(available_cards, key=lambda x: (x.get('heroes', {}).get('stars', 0)), reverse=True)
        
        best_selection = self._find_optimal_card_selection(sorted_cards, max_stars)
        
        if not best_selection:
            sorted_by_stars_asc = sorted(available_cards, key=lambda x: (x.get('heroes', {}).get('stars', 0)))
            best_selection = sorted_by_stars_asc[:5]
            
        total_stars = sum(card.get('heroes', {}).get('stars', 0) for card in best_selection)
        
        return best_selection, total_stars
    
    def _find_optimal_card_selection(self, sorted_cards: List[Dict], max_stars: int) -> List[Dict]:
        if len(sorted_cards) < 5:
            return []
            
        def get_card_stars(card):
            stars = card.get('heroes', {}).get('stars', 0)
            if isinstance(stars, str):
                try:
                    return int(stars)
                except ValueError:
                    return 0
            return stars
        
        selected = []
        total_stars = 0
        
        for card in sorted_cards:
            card_stars = get_card_stars(card)
            if card_stars + total_stars <= max_stars:
                selected.append(card)
                total_stars += card_stars
                if len(selected) == 5:
                    break
        
        if len(selected) == 5:
            return selected

        selected = []
        total_stars = 0
        
        value_cards = []
        for card in sorted_cards:
            card_stars = get_card_stars(card)
            if card_stars == 0:
                card_stars = 1
                
            score = card.get('card_weighted_score', 0)
            if isinstance(score, str):
                try:
                    score = float(score)
                except ValueError:
                    score = 0
                    
            value_cards.append((card, score / card_stars))
        
        value_cards.sort(key=lambda x: x[1], reverse=True)
        
        for card, _ in value_cards:
            card_stars = get_card_stars(card)
            if card_stars + total_stars <= max_stars:
                selected.append(card)
                total_stars += card_stars
                if len(selected) == 5:
                    break
        
        if len(selected) == 5:
            return selected
        
        sorted_by_stars = sorted(sorted_cards, key=get_card_stars)
        return sorted_by_stars[:5]
    
    def register_for_tournament(self, token: str, wallet_address: str, account_number: int, 
                               tournament_id: str, card_ids: List[str]) -> bool:
        try:
            privy_id_token = None
            for cookie in self.api.session.cookies:
                if cookie.name == 'privy-id-token':
                    privy_id_token = cookie.value
                    break
            
            auth_token = privy_id_token if privy_id_token else token
            
            headers = {
                'Accept': 'application/json, text/plain, */*',
                'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
                'Authorization': f'Bearer {auth_token}',
                'Content-Type': 'application/json',
                'Origin': 'https://monad.fantasy.top',
                'Referer': 'https://monad.fantasy.top/',
                'User-Agent': self.api.user_agent,
                'Priority': 'u=1, i',
                'Sec-Ch-Ua': '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
                'Sec-Ch-Ua-Mobile': '?0',
                'Sec-Ch-Ua-Platform': '"Windows"',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-site'
            }
            
            deck_id = str(uuid.uuid4())
            
            payload = {
                "deckId": deck_id,
                "cardIds": card_ids,
                "tournamentId": tournament_id
            }
            
            response = self.api.session.post(
                'https://secret-api.fantasy.top/tournaments/create-deck',
                headers=headers,
                json=payload,
                proxies=self.api.proxies,
                timeout=15
            )
            
            if response.status_code == 429:
                info_log(f"Rate limit hit during tournament registration for account {account_number}, retrying...")
                return False
            
            if response.status_code == 401 and auth_token == privy_id_token and token:
                auth_token = token
                headers['Authorization'] = f'Bearer {auth_token}'
                
                response = self.api.session.post(
                    'https://secret-api.fantasy.top/tournaments/create-deck',
                    headers=headers,
                    json=payload,
                    proxies=self.api.proxies,
                    timeout=15
                )
            
            if response.status_code in [200, 201]:
                success_log(f"Successfully registered account {account_number} in tournament {tournament_id}")
                return True
                
            error_log(f"Failed to register for tournament: {response.status_code}")
            debug_log(f"Registration response: {response.text}")
            return False
            
        except Exception as e:
            error_log(f"Error registering for tournament: {str(e)}")
            return False
    
    def register_in_tournaments(self, token: str, wallet_address: str, account_number: int, 
                               tournament_ids: Dict[str, str]) -> Dict[str, bool]:
        results = {}
        cards = self.fetch_player_cards(wallet_address, token, account_number)
        
        if not cards:
            info_log(f"No cards available for account {account_number}")
            return {t_type: False for t_type in tournament_ids.keys()}
        
        used_card_ids = []
        
        tournament_order = ["elite", "gold", "silver", "bronze"]
        
        for t_type in tournament_order:
            if t_type not in tournament_ids or not tournament_ids[t_type]:
                continue
                
            tournament_id = tournament_ids[t_type]
            max_stars = self.tournament_types[t_type]["max_stars"]
            
            info_log(f"Attempting to register account {account_number} in {t_type.capitalize()} tournament")
            
            selected_cards, total_stars = self.select_best_cards_for_tournament(cards, max_stars, used_card_ids)
            
            if len(selected_cards) < 5:
                error_log(f"Not enough available cards for {t_type} tournament for account {account_number}")
                results[t_type] = False
                continue
                
            if total_stars > max_stars:
                error_log(f"Selected cards exceed star limit for {t_type} tournament: {total_stars} > {max_stars}")
                results[t_type] = False
                continue
                
            card_ids = [card['id'] for card in selected_cards]
            
            try:
                clean_card_info = []
                for card in selected_cards:
                    name = card.get('heroes', {}).get('name', 'Unknown')
                    clean_name = ''.join(c for c in name if ord(c) < 128)
                    stars = card.get('heroes', {}).get('stars', 0)
                    clean_card_info.append(f"{clean_name} ({stars}*)")
                
                info_log(f"Selected cards for {t_type} tournament (total {total_stars}*): {', '.join(clean_card_info)}")
                
                success = self.register_for_tournament(token, wallet_address, account_number, tournament_id, card_ids)
                
                if success:
                    used_card_ids.extend(card_ids)
                    results[t_type] = True
                else:
                    results[t_type] = False
            except Exception as e:
                error_log(f"Error registering for {t_type} tournament: {str(e)}")
                results[t_type] = False
        
        return results
