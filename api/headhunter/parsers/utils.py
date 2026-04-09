"""
Утилиты для парсинга HeadHunter.

Содержит вспомогательные классы:
- ProxyRotator: ротатор прокси-серверов
- UserAgentRotator: ротатор User-Agent
- RequestJitter: генератор jitter для запросов
- ParsingMetrics: метрики парсинга
- IPBlockingTracker: трекер блокировок IP
"""

import re
import time
import logging
import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import SSLError as RequestsSSLError
import ssl
import random
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from django.utils import timezone

logger = logging.getLogger('modules.vacancies_parser.headhunter')


class ProxyRotator:
    """Ротатор прокси-серверов для обхода блокировок"""

    # Базовый набор бесплатных прокси (резервный)
    DEFAULT_PROXIES = [
        {'http': 'http://185.82.99.181:9091', 'https': 'https://185.82.99.181:9091'},
        {'http': 'http://109.167.134.253:5678', 'https': 'https://109.167.134.253:5678'},
        {'http': 'http://195.201.108.163:1080', 'https': 'https://195.201.108.163:1080'},
    ]

    def __init__(self, custom_proxies: Optional[List[Dict[str, str]]] = None):
        self.proxies = custom_proxies or self.DEFAULT_PROXIES.copy()
        self.current_index = 0
        self.last_rotation = time.time()
        self.failed_proxies = set()  # Прокси с ошибками

    @classmethod
    def from_json_file(cls, json_file_path: str) -> 'ProxyRotator':
        """Создать ProxyRotator из JSON файла с прокси"""
        import json
        try:
            with open(json_file_path, 'r', encoding='utf-8') as f:
                proxy_data = json.load(f)

            proxies = []
            for item in proxy_data:
                proxy_url = item.get('proxy', '')
                protocol = item.get('protocol', 'http')
                https = item.get('https', False)

                if not proxy_url:
                    continue

                proxy_dict: Dict[str, str] = {}
                if protocol in ['http', 'https']:
                    if protocol == 'http' or https:
                        proxy_dict['http'] = proxy_url
                    if https or protocol == 'https':
                        # Преобразуем http в https если нужно
                        if proxy_url.startswith('http://'):
                            proxy_dict['https'] = proxy_url.replace('http://', 'https://', 1)
                        else:
                            proxy_dict['https'] = proxy_url
                elif protocol in ['socks4', 'socks5']:
                    # Для SOCKS прокси используем тот же URL для http и https
                    proxy_dict = {
                        'http': proxy_url,
                        'https': proxy_url
                    }

                if proxy_dict:
                    proxies.append(proxy_dict)

            logger.info(f'Загружено {len(proxies)} прокси из файла {json_file_path}')
            return cls(custom_proxies=proxies)

        except Exception as e:
            logger.error(f'Ошибка загрузки прокси из файла {json_file_path}: {e}')
            return cls()  # Возвращаем с дефолтными прокси

    def get_random_proxy(self) -> Optional[Dict[str, str]]:
        """Получить случайный рабочий прокси"""
        available_proxies = [p for i, p in enumerate(self.proxies) if i not in self.failed_proxies]
        if not available_proxies:
            return None
        return random.choice(available_proxies)

    def get_next_proxy(self) -> Optional[Dict[str, str]]:
        """Получить следующий прокси по кругу"""
        if not self.proxies:
            return None

        # Пропускаем нерабочие прокси
        attempts = 0
        while attempts < len(self.proxies):
            proxy = self.proxies[self.current_index]
            if self.current_index not in self.failed_proxies:
                self.current_index = (self.current_index + 1) % len(self.proxies)
                return proxy

            self.current_index = (self.current_index + 1) % len(self.proxies)
            attempts += 1

        return None

    def mark_proxy_failed(self, proxy: Dict[str, str]):
        """Отметить прокси как нерабочий"""
        try:
            proxy_url = proxy.get('http', proxy.get('https', ''))
            for i, p in enumerate(self.proxies):
                if p.get('http') == proxy_url or p.get('https') == proxy_url:
                    self.failed_proxies.add(i)
                    logger.warning(f"Прокси {proxy_url} отмечен как нерабочий")
                    break
        except Exception as e:
            logger.debug(f"Ошибка при отметке прокси как нерабочего: {e}")

    def should_rotate(self, requests_since_rotation: int, time_since_rotation: float) -> bool:
        """Определить, нужно ли ротировать прокси"""
        # Редкая, но более безопасная ротация
        return (requests_since_rotation >= random.randint(120, 260) or
                time_since_rotation >= random.randint(600, 1200))

    def test_proxy(self, proxy: Dict[str, str], timeout: float = 5.0) -> bool:
        """Протестировать работоспособность прокси"""
        try:
            test_url = "http://httpbin.org/ip"
            response = requests.get(test_url, proxies=proxy, timeout=timeout)
            return response.status_code == 200
        except Exception:
            return False

    def get_working_proxies(self) -> List[Dict[str, str]]:
        """Получить список рабочих прокси"""
        working_proxies = []
        for proxy in self.proxies:
            if self.test_proxy(proxy, timeout=2.0):
                working_proxies.append(proxy)
        return working_proxies

    def add_proxy(self, proxy: Dict[str, str]):
        """Добавить новый прокси"""
        self.proxies.append(proxy)

    def clear_failed_proxies(self):
        """Очистить список нерабочих прокси"""
        self.failed_proxies.clear()


class UserAgentRotator:
    """Ротатор User-Agent для обхода блокировок"""

    # Различные браузеры и устройства для имитации реальных пользователей
    USER_AGENTS = [
        # Chrome Desktop (разные версии)
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',

        # Firefox Desktop
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:119.0) Gecko/20100101 Firefox/119.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:120.0) Gecko/20100101 Firefox/120.0',

        # Safari Desktop
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',

        # Edge
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',

        # Chrome Mobile
        'Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/120.0.0.0 Mobile/15E148 Safari/604.1',

        # Opera
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 OPR/106.0.0.0',

        # Yandex Browser
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 YaBrowser/24.1.0.0 Safari/537.36',
    ]

    def __init__(self):
        self.current_index = 0
        self.last_rotation = time.time()

    def get_random_user_agent(self) -> str:
        """Получить случайный User-Agent"""
        return random.choice(self.USER_AGENTS)

    def get_next_user_agent(self) -> str:
        """Получить следующий User-Agent по кругу"""
        ua = self.USER_AGENTS[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.USER_AGENTS)
        return ua

    def should_rotate(self, requests_since_rotation: int, time_since_rotation: float) -> bool:
        """Определить, нужно ли ротировать User-Agent"""
        # Редкая, но более безопасная ротация
        return (requests_since_rotation >= random.randint(150, 320) or
                time_since_rotation >= random.randint(900, 1800))


class RequestJitter:
    """Генератор jitter для имитации человеческого поведения"""

    def __init__(self, base_delay: float = 1.0, jitter_factor: float = 0.3):
        self.base_delay = base_delay
        self.jitter_factor = jitter_factor

    def get_delay(self) -> float:
        """Получить задержку с jitter"""
        # Добавляем случайное отклонение ±30% от базовой задержки
        jitter = random.uniform(-self.jitter_factor, self.jitter_factor)
        delay = self.base_delay * (1 + jitter)
        # Минимум 0.075 секунды, максимум не больше base_delay * 2
        return max(0.075, min(delay, self.base_delay * 2))

    def get_human_like_delay(self, min_delay: float = 0.5, max_delay: float = 3.0) -> float:
        """Получить задержку, имитирующую человеческое поведение"""
        # Используем нормальное распределение для более реалистичных задержек
        mean = (min_delay + max_delay) / 2
        std_dev = (max_delay - min_delay) / 6  # 99.7% значений в пределах min-max

        delay = random.gauss(mean, std_dev)
        return max(min_delay, min(delay, max_delay))

    def get_page_turn_delay(self) -> float:
        """Задержка при перелистывании страниц (дольше, как будто читают)"""
        return random.uniform(1.5, 3.75)

    def get_detail_request_delay(self) -> float:
        """Задержка при запросе деталей вакансии"""
        return random.uniform(0.375, 1.5)


@dataclass
class ParsingMetrics:
    """Метрики парсинга для мониторинга"""
    start_time: datetime = field(default_factory=timezone.now)
    requests_count: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    rate_limits_hit: int = 0
    new_vacancies: int = 0
    updated_vacancies: int = 0
    skipped_vacancies: int = 0
    errors: List[str] = field(default_factory=list)
    
    def record_request(self, success: bool = True):
        """Записать результат запроса"""
        self.requests_count += 1
        if success:
            self.successful_requests += 1
        else:
            self.failed_requests += 1
    
    def record_rate_limit(self):
        """Записать срабатывание rate limit"""
        self.rate_limits_hit += 1
    
    def record_error(self, error_msg: str):
        """Записать ошибку"""
        self.errors.append(f"{timezone.now().isoformat()}: {error_msg}")
        if len(self.errors) > 100:  # Ограничиваем количество ошибок
            self.errors = self.errors[-100:]
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразовать в словарь для логирования"""
        duration = (timezone.now() - self.start_time).total_seconds()
        return {
            'duration_seconds': round(duration, 2),
            'requests_total': self.requests_count,
            'requests_successful': self.successful_requests,
            'requests_failed': self.failed_requests,
            'rate_limits_hit': self.rate_limits_hit,
            'new_vacancies': self.new_vacancies,
            'updated_vacancies': self.updated_vacancies,
            'skipped_vacancies': self.skipped_vacancies,
            'avg_request_time': round(duration / self.requests_count, 3) if self.requests_count else 0,
            'success_rate': round(self.successful_requests / self.requests_count * 100, 1) if self.requests_count else 0,
            'errors_count': len(self.errors)
        }
    
    def log_summary(self):
        """Вывести сводку в лог"""
        stats = self.to_dict()
        logger.info(
            "Метрики парсинга: %d запросов за %.1f сек, "
            "новых: %d, обновлено: %d, пропущено: %d, "
            "rate limits: %d, ошибок: %d",
            stats['requests_total'],
            stats['duration_seconds'],
            stats['new_vacancies'],
            stats['updated_vacancies'],
            stats['skipped_vacancies'],
            stats['rate_limits_hit'],
            stats['errors_count']
        )


class IPBlockingTracker:
    """Трекер блокировок IP для отслеживания 403 ошибок и адаптивных задержек"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._403_count = 0
            cls._instance._last_403_time = 0
            cls._instance._adaptive_delay_multiplier = 1.0
        return cls._instance
    
    def record_403(self) -> None:
        """Записать факт 403 ошибки"""
        current_time = time.time()
        self._403_count += 1
        self._last_403_time = current_time
        
        # Если много 403 за короткое время - увеличиваем множитель задержки
        if self._403_count >= 12:
            self._adaptive_delay_multiplier = min(self._adaptive_delay_multiplier * 1.3, 3.0)
            logger.warning(f'[BLOCKING] Обнаружено {self._403_count} ошибок 403. Увеличиваем задержки в {self._adaptive_delay_multiplier:.1f}x')
    
    def reset_on_success(self) -> None:
        """Сбросить счетчик при успешном запросе"""
        if self._403_count > 0:
            # Постепенно уменьшаем множитель при успешных запросах
            self._adaptive_delay_multiplier = max(self._adaptive_delay_multiplier * 0.94, 1.0)
            # Сбрасываем счетчик если прошло достаточно времени
            if time.time() - self._last_403_time > 240:  # 4 минуты без 403
                self._403_count = 0
                self._adaptive_delay_multiplier = 1.0
    
    def get_adaptive_delay_multiplier(self) -> float:
        """Получить текущий множитель задержки"""
        return self._adaptive_delay_multiplier


