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
            'sec-ch-ua': '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site',
            'Priority': 'u=1, i'
        }
        
        page = 1
        limit = 19
        cards = []
        
        while True:
            params = {
                'pagination.page': page,
                'pagination.limit': limit,
                'where.rarity.in': [1, 2, 3, 4],
                'orderBy': 'cards_score_desc',
                'groupCard': 'true',
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
                debug_log(f"Response: {response.text[:200]}")
                return []
            
            data = response.json()
            if not data.get('data'):
                break
                
            for card in data.get('data', []):
                if not card.get('is_in_deck', False):
                    processed_card = {
                        'id': card.get('id'),
                        'heroes': {
                            'name': card.get('name', card.get('heroes', {}).get('name', 'Unknown')),
                            'handle': card.get('handle', card.get('heroes', {}).get('handle', 'Unknown')),
                            'stars': card.get('stars', card.get('heroes', {}).get('stars', 0))
                        },
                        'card_weighted_score': card.get('card_weighted_score', card.get('weighted_score', 0))
                    }
                    cards.append(processed_card)
            
            meta = data.get('meta', {})
            current_page = meta.get('currentPage', 0)
            last_page = meta.get('lastPage', 0)
            
            if current_page >= last_page or not meta:
                break
                
            page += 1
        
        success_log(f"Fetched {len(cards)} available cards for account {account_number}")
        return cards
        
    except Exception as e:
        error_log(f"Error fetching cards for account {account_number}: {str(e)}")
        return []
