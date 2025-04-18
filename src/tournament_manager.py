import uuid
import time
import random
from typing import List, Dict, Optional, Tuple
from colorama import Fore
from .utils import (
    error_log,
    success_log,
    info_log,
    debug_log,
    get_sec_ch_ua,
    get_platform,
)
from time import sleep
from itertools import combinations


class TournamentManager:
    def __init__(self, api, config):
        self.api = api
        self.config = config
        self.tournament_types = {
            "bronze": {"max_stars": 18, "name": "Bronze Tournament"},
            "silver": {"max_stars": 23, "name": "Silver Tournament"},
            "gold": {"max_stars": 25, "name": "Gold Tournament"},
            "elite": {"max_stars": float("inf"), "name": "Elite Tournament"},
            "reverse": {
                "max_stars": float("inf"),
                "min_stars": 18,
                "name": "Reverse Tournament",
            },
        }

    def fetch_player_cards(
        self, wallet_address: str, token: str, account_number: int
    ) -> List[Dict]:
        try:
            privy_id_token = self.api._get_privy_token_id()

            auth_token = privy_id_token if privy_id_token else token

            headers = {
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                "Authorization": f"Bearer {auth_token}",
                "Origin": "https://monad.fantasy.top",
                "Referer": "https://monad.fantasy.top/",
                "User-Agent": self.api.user_agent,
                "sec-ch-ua": get_sec_ch_ua(self.api.user_agent),
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": get_platform(self.api.user_agent),
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-site",
                "Priority": "u=1, i",
            }

            page = 1
            limit = 100
            cards = []

            while True:
                params = {
                    "pagination.page": page,
                    "pagination.limit": limit,
                    "where.rarity.in": [1, 2, 3, 4],
                    "orderBy": "cards_score_desc",
                    "groupCard": "true",
                    "isGalleryView": "false",
                }

                response = self.api.session.get(
                    f"https://secret-api.fantasy.top/card/player/{wallet_address}",
                    headers=headers,
                    params=params,
                    proxies=self.api.proxies,
                    timeout=15,
                )
                sleep(1)

                if response.status_code == 429:
                    info_log(
                        f"Rate limit hit while fetching cards for account {account_number}, retrying..."
                    )
                    continue

                if response.status_code == 401:
                    if auth_token == privy_id_token and token:
                        auth_token = token
                        headers["Authorization"] = f"Bearer {auth_token}"
                        continue

                    error_log(
                        f"Authorization failed while fetching cards for account {account_number}"
                    )
                    return []

                if response.status_code != 200:
                    error_log(
                        f"Failed to fetch cards for account {account_number}: {response.status_code}"
                    )
                    debug_log(f"Response: {response.text[:200]}")
                    return []

                data = response.json()
                if not data.get("data"):
                    break

                for card in data.get("data", []):
                    # print(card)
                    if not card.get("is_in_deck", False):
                        processed_card = {
                            "id": card.get("id"),
                            "heroes": {
                                "name": card.get(
                                    "name",
                                    card.get("heroes", {}).get("name", "Unknown"),
                                ),
                                "rarity": card.get(
                                    "rarity",
                                    card.get("heroes", {}).get("rarity", 0),
                                ),
                                "handle": card.get(
                                    "handle",
                                    card.get("heroes", {}).get("handle", "Unknown"),
                                ),
                                "stars": card.get(
                                    "stars", card.get("heroes", {}).get("stars", 0)
                                ),
                            },
                            "card_weighted_score": card.get(
                                "card_weighted_score", card.get("weighted_score", 0)
                            ),
                        }
                        cards.append(processed_card)
                print(cards)
                meta = data.get("meta", {})
                current_page = meta.get("currentPage", 0)
                last_page = meta.get("lastPage", 0)

                if current_page >= last_page or not meta:
                    break

                page += 1

            success_log(
                f"Fetched {len(cards)} available cards for account {account_number}"
            )
            return cards

        except Exception as e:
            error_log(f"Error fetching cards for account {account_number}: {str(e)}")
            return []

    def select_best_cards_for_tournament(
        self,
        cards: List[Dict],
        max_stars: int,
        min_stars: int,
        used_card_ids: List[str],
    ) -> Tuple[List[Dict], int]:
        # for card in cards:
        #    print(card)
        try:
            available_cards = [
                card for card in cards if card["id"] not in used_card_ids
            ]

            if len(available_cards) < 5:
                return [], 0

            def get_stars_safe(card):
                try:
                    return int(card.get("heroes", {}).get("stars", 0))
                except (ValueError, TypeError):
                    return 0

            sorted_cards = sorted(available_cards, key=get_stars_safe, reverse=True)

            best_selection = self._find_optimal_card_selection(
                sorted_cards, max_stars, min_stars
            )
            if not best_selection:
                return [], 0

            if not best_selection or len(best_selection) < 5:
                sorted_by_stars_asc = sorted(available_cards, key=get_stars_safe)
                best_selection = sorted_by_stars_asc[:5]

            total_stars = 0
            for card in best_selection:
                try:
                    total_stars += int(card.get("heroes", {}).get("stars", 0))
                except (ValueError, TypeError):
                    pass

            return best_selection, total_stars

        except Exception as e:
            error_log(f"Error in select_best_cards_for_tournament: {str(e)}")
            return [], 0

    def _find_optimal_card_selection(
        self, sorted_cards: List[Dict], max_stars: int, min_stars: int = 0
    ) -> Optional[List[Dict]]:
        if len(sorted_cards) < 5:
            return []

        selected = []
        total_stars = 0

        filtered_cards = []
        rares_amount = 0
        epics_amount = 0
        legends_amount = 0
        for card in sorted_cards:
            rarity = int(card.get("heroes", {}).get("rarity", 0))
            if rarity == 3:
                rares_amount += 1
            elif rarity == 2:
                epics_amount += 1
            elif rarity == 1:
                legends_amount += 1

            if min_stars == 18 and rarity < 4:
                # only commons
                pass
            if max_stars == 18 and rarity < 4:
                # no rares in bronze
                pass
            elif max_stars == 23 and (rarity < 3 or (rares_amount > 3 and rarity == 3)):
                # max 3 rares
                pass
            elif max_stars == 25 and (
                rarity < 2
                or (rares_amount > 4 and rarity == 3)
                or (epics_amount > 2 and rarity == 2)
            ):
                pass
            else:
                filtered_cards.append(card)

        if min_stars == 18:
            pass

        elif max_stars == 23 and rares_amount == 0:
            info_log(f"No rares to register in silver")
            return None

        elif max_stars == 25 and epics_amount == 0:
            info_log(f"No epics to register in gold")
            return None

        elif max_stars > 26 and legends_amount == 0:
            info_log(f"No legends to register in elite")
            return None

        sorted_cards = filtered_cards
        if len(sorted_cards) < 5:
            return None

        if min_stars == 18:
            return self._find_optimal_cards_for_reverse(sorted_cards)

        sorted_cards = sorted(
            sorted_cards,
            key=lambda x: (
                -int(x.get("heroes", {}).get("rarity", 0)),
                int(x.get("heroes", {}).get("stars", 0)),
            ),
            reverse=True,
        )

        best = None  # (score_sum, combo)

        for combo in combinations(sorted_cards, 5):
            stars_sum = sum(
                int(item.get("heroes", {}).get("stars", 0)) for item in combo
            )
            if stars_sum <= max_stars:
                score_sum = sum(
                    int(item.get("card_weighted_score", 0)) for item in combo
                )
                if best is None or score_sum > best[0]:
                    best = (score_sum, combo)

        return best[1] if best else None

    def _find_optimal_cards_for_reverse(
        self, cards: List[Dict]
    ) -> Optional[List[Dict]]:
        sorted_cards = sorted(
            cards,
            key=lambda x: (
                int(x.get("heroes", {}).get("stars", 0)),
                int(x.get("card_weighted_score", 0)),
            ),
            reverse=False,
        )

        best = None  # Хранит кортеж (score_sum, stars_sum, combination)

        for combo in combinations(sorted_cards, 5):
            stars_sum = sum(
                int(item.get("heroes", {}).get("stars", 0)) for item in combo
            )
            if stars_sum >= 18:
                score_sum = sum(
                    int(item.get("card_weighted_score", 0)) for item in combo
                )
                current = (score_sum, stars_sum, combo)

                if (
                    best is None
                    or (current[0] < best[0])
                    or (current[0] == best[0] and current[1] < best[1])
                ):
                    best = current

        return best[2] if best else None

    def register_for_tournament(
        self,
        token: str,
        tournament_type: str,
        wallet_address: str,
        account_number: int,
        tournament_id: str,
        card_ids: List[str],
        deck_number: int = 1,
    ) -> bool:
        try:
            privy_id_token = self.api._get_privy_token_id()

            auth_token = privy_id_token if privy_id_token else token

            headers = {
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                "Authorization": f"Bearer {auth_token}",
                "Content-Type": "application/json",
                "Origin": "https://monad.fantasy.top",
                "Referer": "https://monad.fantasy.top/",
                "User-Agent": self.api.user_agent,
                "sec-ch-ua": get_sec_ch_ua(self.api.user_agent),
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": get_platform(self.api.user_agent),
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-site",
                "Priority": "u=1, i",
            }

            max_registration_retries = 3
            retry_delay = 2

            for retry_attempt in range(max_registration_retries):
                try:
                    deck_id = str(uuid.uuid4())

                    payload = {
                        "deckId": deck_id,
                        "cardIds": card_ids,
                        "tournamentId": tournament_id,
                    }

                    debug_log(f"Sending tournament registration payload: {payload}")

                    response = self.api.session.post(
                        "https://secret-api.fantasy.top/tournaments/create-deck",
                        headers=headers,
                        json=payload,
                        proxies=self.api.proxies,
                        timeout=15,
                    )

                    try:
                        response_data = response.json()
                        debug_log(f"Tournament registration response: {response_data}")
                    except Exception:
                        debug_log(f"Non-JSON response: {response.text}")

                    if response.status_code == 429:
                        info_log(
                            f"Rate limit hit during tournament registration for account {account_number}, retrying ({retry_attempt+1}/{max_registration_retries})..."
                        )
                        time.sleep(retry_delay)
                        continue

                    if response.status_code == 500:
                        info_log(
                            f"Server error (500) during tournament registration for account {account_number}, retrying ({retry_attempt+1}/{max_registration_retries})..."
                        )
                        time.sleep(retry_delay)
                        time.sleep(random.uniform(1.0, 3.0))
                        continue

                    if (
                        response.status_code == 401
                        and auth_token == privy_id_token
                        and token
                    ):
                        auth_token = token
                        headers["Authorization"] = f"Bearer {auth_token}"
                        continue

                    if response.status_code in [200, 201]:
                        success_log(
                            f"Successfully registered account {account_number} in tournament {tournament_type} = {tournament_id} (Deck #{deck_number})"
                        )
                        return True

                    info_log(
                        f"Unknown response {response.status_code} during tournament registration for account {account_number}, retrying ({retry_attempt+1}/{max_registration_retries})..."
                    )
                    info_log(response.text)
                    debug_log(f"Registration response: {response.text}")
                    time.sleep(retry_delay)

                except Exception as e:
                    if retry_attempt < max_registration_retries - 1:
                        error_log(
                            f"Error during tournament registration attempt {retry_attempt+1}: {str(e)}, retrying..."
                        )
                        time.sleep(retry_delay)
                    else:
                        error_log(f"Final error registering for tournament: {str(e)}")
                        return False

            error_log(
                f"Failed to register for tournament after {max_registration_retries} attempts"
            )
            return False

        except Exception as e:
            error_log(f"Error registering for tournament: {str(e)}")
            return False

    def register_in_tournaments(
        self,
        token: str,
        wallet_address: str,
        account_number: int,
        tournament_ids: Dict[str, str],
    ) -> Dict[str, bool]:
        results = {}
        cards = self.fetch_player_cards(wallet_address, token, account_number)

        if not cards:
            info_log(f"No cards available for account {account_number}")
            return {t_type: False for t_type in tournament_ids.keys()}

        print(tournament_ids)
        used_card_ids = []

        tournaments_types_ordered = ["elite", "gold", "silver", "reverse", "bronze"]
        for active_tournament_type in tournaments_types_ordered:
            t_id = tournament_ids.get(active_tournament_type, None)
            if not t_id:
                continue

            # active_tournament_type = None
            # for t_type, t_id in tournament_ids.items():
            #    if t_id:
            #        active_tournament_type = t_type
            #        break

            # print(active_tournament_type)
            # if not active_tournament_type:
            #    info_log(f"No active tournament selected for account {account_number}")
            #    return {}

            tournament_id = tournament_ids[active_tournament_type]
            max_stars = self.tournament_types[active_tournament_type]["max_stars"]
            min_stars = self.tournament_types[active_tournament_type].get(
                "min_stars", 0
            )

            info_log(
                f"Attempting to register account {account_number} in {active_tournament_type.capitalize()} tournament"
            )

            deck_number = 1
            registration_successful = False

            while True:
                selected_cards, total_stars = self.select_best_cards_for_tournament(
                    cards, max_stars, min_stars, used_card_ids
                )
                # print(selected_cards)

                if len(selected_cards) < 5:
                    if deck_number == 1:
                        info_log(
                            f"Not enough available cards for {active_tournament_type} tournament for account {account_number}"
                        )
                        results[active_tournament_type] = False
                    else:
                        info_log(
                            f"No more complete decks available for {active_tournament_type} tournament (registered {deck_number-1} decks) for account {account_number}"
                        )
                    break

                if total_stars > max_stars:
                    if deck_number == 1:
                        info_log(
                            f"Selected cards exceed star limit for {active_tournament_type} tournament: {total_stars} > {max_stars} for account {account_number}"
                        )
                        results[active_tournament_type] = False
                    else:
                        info_log(
                            f"No more valid decks within star limit for {active_tournament_type} tournament for account {account_number}"
                        )
                    break

                card_ids = [card["id"] for card in selected_cards]

                try:
                    clean_card_info = []
                    for card in selected_cards:
                        name = card.get("heroes", {}).get("name", "Unknown")
                        clean_name = "".join(c for c in name if ord(c) < 128)
                        stars = card.get("heroes", {}).get("stars", 0)
                        info = f"{clean_name} ({stars}*)"
                        rarity = int(card.get("heroes", {}).get("rarity", 0))
                        if rarity == 4:
                            info = f"{info} (COMMON)"
                        elif rarity == 3:
                            info = f"{info} (RARE)"
                        elif rarity == 2:
                            info = f"{info} (EPIC)"
                        elif rarity == 1:
                            info = f"{info} (LEGEND)"
                        clean_card_info.append(info)

                    info_log(
                        f"Selected cards for {active_tournament_type} tournament deck #{deck_number} (total {total_stars}*): {', '.join(clean_card_info)}"
                    )

                    success = self.register_for_tournament(
                        token,
                        active_tournament_type,
                        wallet_address,
                        account_number,
                        tournament_id,
                        card_ids,
                        deck_number,
                    )

                    if success:
                        used_card_ids.extend(card_ids)
                        registration_successful = True
                        deck_number += 1
                    else:
                        if deck_number == 1:
                            results[active_tournament_type] = False
                        break
                except Exception as e:
                    error_log(
                        f"Error registering for {active_tournament_type} tournament: {str(e)}"
                    )
                    if deck_number == 1:
                        results[active_tournament_type] = False
                    break
                if min_stars == 18:
                    # attemp to reg only one deck for reverse
                    break

            results[active_tournament_type] = registration_successful
        return results
