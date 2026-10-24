"""Select publisher-provided image metadata; never download an image."""
from html.parser import HTMLParser
import ipaddress
import re
from urllib.parse import urljoin, urlsplit


def safe_image_url(value, base_url=None):
    if not isinstance(value, str) or not value.strip():
        return None
    # HTMLParser/XML attributes already decode entities once. Preserve signed queries.
    value = value.strip()
    if len(value) > 4096 or any(ord(c) < 33 for c in value) or '\\' in value:
        return None
    try:
        value = urljoin(base_url, value) if base_url else value
        parts = urlsplit(value)
        host = (parts.hostname or '').lower().rstrip('.')
        if (parts.scheme not in {'http', 'https'} or not host or parts.username is not None
                or parts.password is not None or parts.port not in {None, 80 if parts.scheme == 'http' else 443}):
            return None
        if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal', '.lan', '.home')):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            if '.' not in host or host.replace('.', '').isdigit():
                return None
        if re.search(r'(?:^|[/_.-])(?:logo|default|placeholder)(?:[/_.-]|$)', parts.path, re.I):
            return None
    except (ValueError, UnicodeError):
        return None
    return value


def image_from_rss(media, article_url):
    for row in media if isinstance(media, list) else []:
        if not isinstance(row, dict):
            continue
        kind = str(row.get('kind', '')).lower().rsplit('}', 1)[-1].rsplit(':', 1)[-1]
        mime = str(row.get('type', '')).lower()
        medium = str(row.get('medium', '')).lower()
        if medium not in {'', 'image'} or (mime and not mime.startswith('image/')):
            continue
        if kind not in {'content', 'thumbnail', 'enclosure'}:
            continue
        if not (kind == 'thumbnail' or medium == 'image' or mime.startswith('image/')):
            continue
        url = safe_image_url(row.get('url'), article_url)
        if url:
            return {'url': url, 'origin': 'rss_media'}
    return None


class _ImageMetadata(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.values = {}

    def handle_starttag(self, tag, attrs):
        if tag == 'meta':
            row = dict(attrs)
            key = (row.get('property') or row.get('name') or '').lower()
            if key in {'og:image:secure_url', 'og:image', 'og:image:url', 'twitter:image', 'twitter:image:src'}:
                self.values.setdefault(key, []).append(row.get('content'))


def image_from_html(html, article_url):
    doc = _ImageMetadata()
    doc.feed(html)
    doc.close()
    for key in ('og:image:secure_url', 'og:image', 'og:image:url', 'twitter:image', 'twitter:image:src'):
        for value in doc.values.get(key, []):
            url = safe_image_url(value, article_url)
            if url:
                return {'url': url, 'origin': 'og_image' if key.startswith('og:') else 'twitter_image'}
    return None
