"""Sequential text-only HTTP with policy checks, bounded retries and evidence."""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import random
import time
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

from mts.storage import HtmlCache


BASE = 'https://www.10thplanetjj.com'
ARCHIVE = BASE + '/techniques-archive/'
USER_AGENT = 'PersonalMTSChapterIndexer/2.0 (personal research; public text metadata only)'
TRANSIENT = {429, 500, 502, 503, 504}


class FetchFailure(Exception):
    def __init__(self, message, status='fetch_error'):
        super().__init__(message)
        self.status = status


class OfflineMiss(FetchFailure):
    pass


def validate_url(url):
    parsed = urlparse(url)
    if (parsed.scheme != 'https' or parsed.netloc not in {'www.10thplanetjj.com', '10thplanetjj.com'}
            or parsed.username or parsed.password):
        raise FetchFailure(f'Refusing URL outside the public text source: {url}')
    if parsed.path not in {'/robots.txt', '/techniques-archive/'} and not (
            parsed.path.startswith('/techniques/') and parsed.path.endswith('/')):
        raise FetchFailure(f'Redirect/resource outside public episode pages: {url}', 'access_restricted')


def retry_after(value):
    if not value:
        return 0
    try:
        return max(0, float(value))
    except ValueError:
        try:
            return max(0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return 0


class TextClient:
    def __init__(self, cache, delay=5.0, offline=False, refresh=False, retries=4, session=None):
        self.cache = cache if isinstance(cache, HtmlCache) else HtmlCache(cache)
        self.delay, self.offline, self.refresh, self.retries = delay, offline, refresh, retries
        self.session = session or requests.Session()
        self.session.headers.update({'User-Agent': USER_AGENT, 'Accept': 'text/html,text/plain'})
        self.robots = None
        self.network_requests = 0

    def close(self):
        self.session.close()

    def _request(self, original_url):
        url = original_url
        for redirect in range(6):
            validate_url(url)
            if self.robots and not self.robots.can_fetch(USER_AGENT, url):
                raise FetchFailure(f'robots.txt disallows {url}', 'robots_disallowed')
            for attempt in range(self.retries):
                time.sleep(self.delay + random.uniform(0, min(1, self.delay / 3)))
                self.network_requests += 1
                try:
                    response = self.session.get(url, timeout=(10, 30), allow_redirects=False)
                except (requests.ConnectionError, requests.Timeout) as exc:
                    if attempt == self.retries - 1:
                        raise FetchFailure(str(exc)) from exc
                    time.sleep(min(120, 8 * 2 ** attempt))
                    continue
                except requests.RequestException as exc:
                    raise FetchFailure(str(exc)) from exc
                if response.status_code in TRANSIENT and attempt < self.retries - 1:
                    wait = max(8 * 2 ** attempt, retry_after(response.headers.get('Retry-After')))
                    if wait > 120:
                        break  # Record limitation instead of retrying earlier than requested.
                    print(f'HTTP {response.status_code}: backoff {wait:g}s: {url}', flush=True)
                    time.sleep(wait)
                    continue
                break
            if response.is_redirect:
                target = urljoin(url, response.headers['Location'])
                validate_url(target)
                url = target
                continue
            content_type = response.headers.get('Content-Type', '').split(';')[0].lower()
            if content_type and content_type not in {'text/html', 'text/plain', 'application/xhtml+xml'}:
                raise FetchFailure(f'Non-text response ({content_type}) for {url}')
            return self.cache.write(original_url, response.text, response.status_code, url)
        raise FetchFailure(f'Too many redirects for {original_url}')

    def _check_robots(self):
        if self.robots is not None:
            return
        # A live run rechecks policy once; cached-only execution makes no requests.
        page = self._request(BASE + '/robots.txt')
        if page['status_code'] != 200:
            raise FetchFailure(f'robots.txt unavailable (HTTP {page["status_code"]}); stopped before crawling')
        self.robots = RobotFileParser()
        self.robots.parse(page['html'].splitlines())

    def get(self, url, refresh=False):
        validate_url(url)
        try:
            cached = self.cache.read(url)
        except (ValueError, KeyError) as exc:
            if self.offline:
                raise OfflineMiss(f'Corrupt cache for {url}: {exc}') from exc
            cached = None
        if cached and not (refresh or self.refresh):
            return cached
        if self.offline:
            raise OfflineMiss(f'No cached HTML for {url}; run a targeted live crawl first')
        self._check_robots()
        return self._request(url)
