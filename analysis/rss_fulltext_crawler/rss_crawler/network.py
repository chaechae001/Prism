"""Small, bounded HTTP client with explicit redirects and cached robots rules."""

from dataclasses import dataclass
from email.message import Message
from http.client import HTTPException
import ipaddress
import math
import re
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .parsing import article_identity, checked_url, source_for_url


PRODUCT = "AINewsFulltextBot"
USER_AGENT = "AINewsFulltextBot/0.1 (RSS article text collector)"
POLICY_AGENTS = (PRODUCT, "GPTBot")
REDIRECTS = {301, 302, 303, 307, 308}


class FetchError(Exception):
    def __init__(self, code: str, http_status: int | None = None):
        self.code = code
        self.http_status = http_status
        super().__init__(code)


@dataclass(frozen=True)
class Response:
    url: str
    status: int
    headers: dict[str, str]
    body: bytes


def validate_network_url(url: str, resolver=socket.getaddrinfo) -> None:
    try:
        checked_url(url)
    except ValueError as exc:
        raise FetchError("invalid_url") from exc
    if source_for_url(url) is None:
        raise FetchError("unsupported_host")
    parts = urlsplit(url)
    try:
        addresses = resolver(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except OSError as exc:
        raise FetchError("dns_error") from exc
    if not addresses or any(not ipaddress.ip_address(address[4][0].split("%")[0]).is_global for address in addresses):
        raise FetchError("non_public_address")


def read_limited(stream, max_bytes: int) -> bytes:
    body = stream.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise FetchError("response_too_large")
    return body


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HttpTransport:
    def __init__(self, timeout: float = 15):
        if not math.isfinite(timeout) or not 1 <= timeout <= 30:
            raise ValueError("timeout must be between 1 and 30 seconds")
        self.timeout = timeout
        self.opener = build_opener(ProxyHandler({}), _NoRedirect())

    def request(self, url: str, max_bytes: int) -> Response:
        validate_network_url(url)
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity", "Accept": "text/html,application/rss+xml,application/xml,text/plain;q=0.9,*/*;q=0.1"})
        try:
            try:
                response = self.opener.open(request, timeout=self.timeout)
            except HTTPError as response_error:
                response = response_error
            with response:
                headers = {key.lower(): value for key, value in response.headers.items()}
                if headers.get("content-encoding", "identity").lower() not in {"", "identity"}:
                    raise FetchError("unsupported_content_encoding", response.code)
                if response.code in REDIRECTS:
                    body = b""
                else:
                    body = read_limited(response, max_bytes)
                return Response(url, response.code, headers, body)
        except FetchError:
            raise
        except HTTPException as exc:
            raise FetchError("http_protocol_error") from exc
        except (URLError, OSError, TimeoutError, ValueError) as exc:
            raise FetchError("network_error") from exc


def _robots_octets(value: str) -> str:
    value = "".join(quote(char, safe="") if ord(char) > 127 else char for char in value)

    def normalize(match):
        char = chr(int(match.group(1), 16))
        unreserved = ord(char) < 128 and (char.isalnum() or char in "-._~")
        return char if unreserved else "%" + match.group(1).upper()

    return re.sub(r"%([0-9a-fA-F]{2})", normalize, value)


class RobotsPolicy:
    """Robots groups, longest matching rule, wildcard and end-anchor support.

    Crawl-delay and Request-rate are also honored conservatively. This parser
    covers the rules needed by the supported publishers; it is not a general
    crawler framework or a statement about permission to reuse article text.
    """

    def __init__(self, text: str):
        self.groups = []
        group = None
        directives_seen = False
        for line in text.lstrip("\ufeff").splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = (part.strip() for part in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if group is None or directives_seen:
                    group = {"agents": [], "rules": [], "delay": 0.0}
                    self.groups.append(group)
                    directives_seen = False
                group["agents"].append(value.lower())
            elif group is not None and key in {"allow", "disallow", "crawl-delay", "request-rate"}:
                directives_seen = True
                if key in {"allow", "disallow"} and value.startswith("/"):
                    group["rules"].append((key == "allow", value))
                elif key in {"crawl-delay", "request-rate"}:
                    try:
                        if key == "crawl-delay":
                            delay = float(value)
                        else:
                            requests, seconds = value.split("/", 1)
                            delay = float(seconds) / float(requests)
                        if math.isfinite(delay) and delay >= 0:
                            group["delay"] = max(group["delay"], delay)
                    except (ValueError, ZeroDivisionError):
                        pass

    def _matching_groups(self, agent: str):
        matches = []
        product = agent.lower().split("/", 1)[0]
        for group in self.groups:
            specificity = max((0 if token == "*" else len(token) for token in group["agents"] if token == "*" or (token and token in product)), default=-1)
            if specificity >= 0:
                matches.append((specificity, group))
        best = max((specificity for specificity, _ in matches), default=-1)
        return [group for specificity, group in matches if specificity == best]

    def can_fetch(self, agent: str, url: str) -> bool:
        parts = urlsplit(url)
        path = _robots_octets((parts.path or "/") + (("?" + parts.query) if parts.query else ""))
        matches = []
        for group in self._matching_groups(agent):
            for allow, pattern in group["rules"]:
                anchored = pattern.endswith("$")
                raw_pattern = _robots_octets(pattern[:-1] if anchored else pattern)
                regex = re.escape(raw_pattern).replace(r"\*", ".*") + ("$" if anchored else "")
                if re.match(regex, path):
                    matches.append((len(raw_pattern.replace("*", "")), allow))
        return max(matches, default=(-1, True))[1]

    def delay(self, agent: str) -> float:
        return max((group["delay"] for group in self._matching_groups(agent)), default=0.0)


class CrawlClient:
    def __init__(self, transport=None, min_delay: float = 1.5, clock=time.monotonic, sleep=time.sleep):
        if not math.isfinite(min_delay) or not 0 <= min_delay <= 30:
            raise ValueError("min_delay must be between 0 and 30 seconds")
        self.transport = transport if transport is not None else HttpTransport()
        self.min_delay = min_delay
        self.clock = clock
        self.sleep = sleep
        self.last_request = {}
        self.policies = {}
        self.policy_errors = {}
        self.requests_made = 0

    def _one(self, url, max_bytes, delay):
        if delay > 30:
            raise FetchError("crawl_delay_exceeds_budget")
        host = urlsplit(url).hostname
        previous = self.last_request.get(host)
        if previous is not None:
            wait = delay - (self.clock() - previous)
            if wait > 0:
                self.sleep(wait)
        self.last_request[host] = self.clock()
        self.requests_made += 1
        return self.transport.request(url, max_bytes)

    @staticmethod
    def _trusted(url, source):
        actual = source_for_url(url)
        if actual is None or actual.key != source.key:
            raise FetchError("unsupported_redirect_or_host")

    def _policy(self, url):
        parts = urlsplit(url)
        origin = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
        if origin in self.policy_errors:
            raise self.policy_errors[origin]
        if origin in self.policies:
            return self.policies[origin]
        current = origin + "/robots.txt"
        source = source_for_url(url)
        try:
            for _ in range(4):
                self._trusted(current, source)
                response = self._one(current, 200_000, self.min_delay)
                if response.status in REDIRECTS:
                    destination = urljoin(current, response.headers.get("location", ""))
                    if urlsplit(current).scheme == "https" and urlsplit(destination).scheme != "https":
                        raise FetchError("unsafe_redirect")
                    self._trusted(destination, source)
                    current = destination
                    continue
                if response.status in {404, 410}:
                    policy = RobotsPolicy("")
                elif response.status in {401, 403}:
                    raise FetchError("robots_disallowed", response.status)
                elif response.status != 200:
                    raise FetchError("robots_unavailable", response.status)
                else:
                    try:
                        text = response.body.decode("utf-8-sig")
                    except UnicodeError as exc:
                        raise FetchError("robots_unavailable") from exc
                    if text.lstrip().lower().startswith(("<!doctype html", "<html")):
                        raise FetchError("robots_unavailable")
                    policy = RobotsPolicy(text)
                self.policies[origin] = policy
                return policy
            raise FetchError("robots_redirect_limit")
        except FetchError as exc:
            error = exc if exc.code in {"robots_disallowed", "robots_unavailable"} else FetchError("robots_unavailable", exc.http_status)
            self.policy_errors[origin] = error
            raise error

    def get(self, url: str, max_bytes: int, expected_identity=None) -> Response:
        source = source_for_url(url)
        if source is None:
            raise FetchError("unsupported_host")
        current = url
        for _ in range(4):
            self._trusted(current, source)
            if expected_identity is not None and article_identity(current) != expected_identity:
                raise FetchError("redirect_id_mismatch")
            policy = self._policy(current)
            if not all(policy.can_fetch(agent, current) for agent in POLICY_AGENTS):
                raise FetchError("robots_disallowed")
            delay = max([self.min_delay] + [policy.delay(agent) for agent in POLICY_AGENTS])
            response = self._one(current, max_bytes, delay)
            if response.status in REDIRECTS:
                location = response.headers.get("location")
                if not location:
                    raise FetchError("redirect_without_location", response.status)
                destination = urljoin(current, location)
                self._trusted(destination, source)
                if urlsplit(current).scheme == "https" and urlsplit(destination).scheme != "https":
                    raise FetchError("unsafe_redirect")
                current = destination
                continue
            if response.status != 200:
                raise FetchError("http_error", response.status)
            return response
        raise FetchError("redirect_limit")


def decode_html(response: Response) -> str:
    message = Message()
    message["content-type"] = response.headers.get("content-type", "")
    charset = message.get_content_charset()
    if not charset:
        match = re.search(rb'<meta\b[^>]*charset\s*=\s*["\']?([\w-]+)', response.body[:8192], re.I)
        charset = match.group(1).decode("ascii") if match else "utf-8-sig"
    if charset.lower() in {"euc-kr", "ks_c_5601-1987"}:
        charset = "cp949"
    try:
        return response.body.decode(charset)
    except (LookupError, UnicodeError) as exc:
        raise FetchError("html_encoding_error") from exc
