import time
import random
import threading
from typing import Dict, List, Tuple

class SimpleProxyManager:
    def __init__(self, all_proxies: List[str], cooldown_period: int = 60):
        self.all_proxies = all_proxies
        self.rate_limited_proxies = {}
        self.lock = threading.Lock()
        self.cooldown_period = cooldown_period
        
    def get_proxy(self) -> Tuple[str, Dict[str, str]]:
        with self.lock:
            current_time = time.time()
            
            available_proxies = [
                proxy for proxy in self.all_proxies 
                if proxy not in self.rate_limited_proxies or self.rate_limited_proxies[proxy] < current_time
            ]
            
            if not available_proxies:
                next_proxy = min(self.rate_limited_proxies.items(), key=lambda x: x[1])[0]
            else:
                next_proxy = random.choice(available_proxies)
                
            return next_proxy, {"http": next_proxy, "https": next_proxy}
    
    def mark_rate_limited(self, proxy: str):
        with self.lock:
            jitter = random.uniform(0, 15)
            self.rate_limited_proxies[proxy] = time.time() + self.cooldown_period + jitter
            
    def remove_rate_limit(self, proxy: str):
        with self.lock:
            if proxy in self.rate_limited_proxies:
                del self.rate_limited_proxies[proxy]
