import json
import os
from datetime import datetime, timedelta
from typing import Dict, Optional
import pytz

class AccountStorage:
    def __init__(self, storage_file: str = "data/accounts_data.json"):
        self.storage_file = storage_file
        self.data = self._load_data()

    def _load_data(self) -> Dict:
        if os.path.exists(self.storage_file):
            try:
                with open(self.storage_file, 'r') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                return {}
        return {}

    def _save_data(self):
        os.makedirs(os.path.dirname(self.storage_file), exist_ok=True)
        with open(self.storage_file, 'w') as f:
            json.dump(self.data, f, indent=4)

    def update_account(self, address: str, private_key: str, token: Optional[str] = None,
                      cookies: Optional[Dict] = None, last_daily_claim: Optional[str] = None):
        if address not in self.data:
            self.data[address] = {
                "private_key": private_key,
                "created_at": datetime.now(pytz.UTC).isoformat()
            }
        
        account_data = self.data[address]
        
        if token is not None:
            account_data["token"] = token
            account_data["token_updated_at"] = datetime.now(pytz.UTC).isoformat()
        
        if cookies is not None:
            account_data["cookies"] = cookies
            account_data["cookies_updated_at"] = datetime.now(pytz.UTC).isoformat()
        
        if last_daily_claim is not None:
            account_data["last_daily_claim"] = last_daily_claim
        
        self._save_data()

    def get_account_data(self, address: str) -> Optional[Dict]:
        return self.data.get(address)

    def get_next_daily_claim_time(self, address: str) -> Optional[datetime]:
        account_data = self.get_account_data(address)
        if not account_data or "last_daily_claim" not in account_data:
            return None

        last_claim = datetime.fromisoformat(account_data["last_daily_claim"])
        next_claim = last_claim.replace(tzinfo=pytz.UTC) + timedelta(hours=24)
        return next_claim if next_claim > datetime.now(pytz.UTC) else None
