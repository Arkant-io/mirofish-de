"""
Echtzeit-Konkurrenzanalyse (Opt-in "Konkurrenzanalyse einbeziehen").

Pro angegebenem Wettbewerber (Name oder Website-URL) wird live recherchiert:
  - Name  -> aktuelle deutsche News über den Google-News-RSS-Suchfeed
             (gleiche Quelle wie GermanSourcesService, kein API-Key nötig)
  - URL   -> die Website selbst wird abgerufen und als Text extrahiert
             (mit SSRF-Schutz: nur http/https, keine privaten/lokalen Hosts)

Das Ergebnis wird als eigener Seed-Block in den Wissens-Graphen eingespeist,
sodass Simulations-Agenten UND der Bericht darauf zugreifen können. Fehler
brechen die Pipeline nie — Konkurrenzdaten sind Zusatzmaterial.
"""

import re
import html
import http.client
import ipaddress
import socket
import ssl
import urllib.parse
import xml.etree.ElementTree as ET

from ..utils.logger import get_logger

logger = get_logger('mirofish.competitor_sources')

_GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=de&gl=DE&ceid=DE:de"

# ASCII-only User-Agent (Umlaute/Em-Dash wuerden urllib crashen)
_USER_AGENT = "Mozilla/5.0 (compatible; MiroFishResearch/1.0)"

_MAX_COMPETITORS = 5
_MAX_NEWS_PER_COMPETITOR = 5
_MAX_SITE_CHARS = 6000
_TIMEOUT = 12
_MAX_REDIRECTS = 5
_MAX_BYTES = 2 * 1024 * 1024


def _strip_html(text: str) -> str:
    text = re.sub(r'<script[\s\S]*?</script>', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'<style[\s\S]*?</style>', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()


def _is_public_ip(ip) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def _resolve_public_ip(host: str):
    """Host auflösen; nur wenn ALLE Adressen öffentlich sind, eine davon liefern."""
    if not host or '.' not in host or host.endswith('.local'):
        return None
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
        ips = [ipaddress.ip_address(info[4][0].split('%')[0]) for info in infos]
    except (OSError, ValueError):
        return None
    if not ips or not all(_is_public_ip(ip) for ip in ips):
        return None
    return str(ips[0])


def _is_safe_public_url(url: str) -> bool:
    """SSRF-Schutz: nur http(s) auf öffentliche Hosts zulassen."""
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return False
        return _resolve_public_ip(parsed.hostname or '') is not None
    except Exception:
        return False


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """Verbindet zur vorab geprüften IP statt neu aufzulösen (kein DNS-Rebinding)."""

    def __init__(self, host, ip, **kwargs):
        super().__init__(host, **kwargs)
        self._pinned_ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Wie oben, TLS-Prüfung (SNI + Zertifikat) aber gegen den echten Hostnamen."""

    def __init__(self, host, ip, **kwargs):
        super().__init__(host, context=ssl.create_default_context(), **kwargs)
        self._pinned_ip = ip

    def connect(self):
        sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _http_get(url: str) -> bytes:
    """GET mit SSRF-Schutz bei jedem Schritt.

    Weiterleitungen werden selbst verfolgt: Jedes Ziel wird erneut geprüft, und
    verbunden wird immer mit genau der geprüften IP.
    """
    for _ in range(_MAX_REDIRECTS + 1):
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            raise ValueError(f"Schema nicht erlaubt: {parsed.scheme}")
        host = parsed.hostname or ''
        ip = _resolve_public_ip(host)
        if ip is None:
            raise ValueError(f"Ziel nicht öffentlich: {host}")
        conn_cls = _PinnedHTTPSConnection if parsed.scheme == 'https' else _PinnedHTTPConnection
        conn = conn_cls(host, ip, port=parsed.port, timeout=_TIMEOUT)
        try:
            path = parsed.path or '/'
            if parsed.query:
                path += '?' + parsed.query
            conn.request('GET', path, headers={"User-Agent": _USER_AGENT, "Accept-Encoding": "identity"})
            resp = conn.getresponse()
            if resp.status in (301, 302, 303, 307, 308):
                location = resp.getheader('Location')
                if not location:
                    raise ValueError("Weiterleitung ohne Ziel")
                url = urllib.parse.urljoin(url, location)
                continue
            if resp.status >= 400:
                raise ValueError(f"HTTP {resp.status}")
            return resp.read(_MAX_BYTES)
        finally:
            conn.close()
    raise ValueError("Zu viele Weiterleitungen")


def _looks_like_url(entry: str) -> bool:
    return entry.startswith(('http://', 'https://')) or (
        '.' in entry and ' ' not in entry and '/' not in entry.rstrip('/')
        and re.match(r'^[a-z0-9.\-]+\.[a-z]{2,}$', entry.lower()) is not None
    )


def _fetch_news(name: str) -> list:
    """Aktuelle News zu einem Wettbewerber-Namen."""
    url = _GOOGLE_NEWS_RSS.format(query=urllib.parse.quote(f'"{name}"'))
    try:
        raw = _http_get(url)
        root = ET.fromstring(raw)
    except Exception as e:
        logger.warning(f"Konkurrenz-News fehlgeschlagen ({name}): {e}")
        return []
    items = []
    for item in root.iterfind(".//item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        source_el = item.find("source")
        items.append({
            "title": title,
            "source": (source_el.text.strip() if source_el is not None and source_el.text else ""),
            "published": (item.findtext("pubDate") or "").strip(),
            "summary": _strip_html(item.findtext("description") or ""),
        })
        if len(items) >= _MAX_NEWS_PER_COMPETITOR:
            break
    return items


def _fetch_site(url: str) -> str:
    """Website eines Wettbewerbers als Text (gekuerzt)."""
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    if not _is_safe_public_url(url):
        logger.warning(f"Konkurrenz-Website uebersprungen (nicht oeffentlich/unsicher): {url}")
        return ""
    try:
        raw = _http_get(url)
        text = _strip_html(raw.decode('utf-8', errors='replace'))
        return text[:_MAX_SITE_CHARS]
    except Exception as e:
        logger.warning(f"Konkurrenz-Website fehlgeschlagen ({url}): {e}")
        return ""


class CompetitorResearchService:
    """Live-Recherche zu benannten Wettbewerbern."""

    @staticmethod
    def parse_competitors(raw: str) -> list:
        """Komma-/zeilengetrennte Eingabe in eine bereinigte Liste wandeln."""
        if not raw or not isinstance(raw, str):
            return []
        parts = re.split(r'[,\n;]+', raw)
        seen, result = set(), []
        for p in parts:
            p = p.strip()
            if p and p.lower() not in seen:
                seen.add(p.lower())
                result.append(p[:120])
            if len(result) >= _MAX_COMPETITORS:
                break
        return result

    @staticmethod
    def fetch(competitors: list) -> tuple:
        """
        Args:
            competitors: Liste von Namen und/oder URLs (max. 5)
        Returns:
            (text, count): formatierter Seed-Block + Anzahl Wettbewerber mit Daten
        """
        competitors = list(competitors or [])[:_MAX_COMPETITORS]
        if not competitors:
            return "", 0

        blocks = []
        hit_count = 0
        for entry in competitors:
            lines = [f"--- Wettbewerber: {entry} ---"]
            got_data = False

            if _looks_like_url(entry):
                site_text = _fetch_site(entry)
                if site_text:
                    lines.append(f"Website-Inhalt ({entry}):")
                    lines.append(site_text)
                    got_data = True
                # Domain ohne TLD-Endung auch als News-Suchbegriff nutzen
                name_guess = urllib.parse.urlparse(
                    entry if entry.startswith('http') else 'https://' + entry
                ).hostname or entry
                name_guess = re.sub(r'^www\.', '', name_guess).split('.')[0]
            else:
                name_guess = entry

            news = _fetch_news(name_guess)
            if news:
                lines.append(f"Aktuelle Nachrichten zu '{name_guess}':")
                for i, it in enumerate(news, 1):
                    meta = " — ".join(filter(None, [it.get("source"), it.get("published")]))
                    lines.append(f"{i}. {it['title']}" + (f" ({meta})" if meta else ""))
                    if it.get("summary"):
                        lines.append(f"   {it['summary'][:300]}")
                got_data = True

            if got_data:
                hit_count += 1
                blocks.append("\n".join(lines))

        if not blocks:
            return "", 0

        text = (
            "=== Echtzeit-Konkurrenzanalyse (automatisch recherchiert) ===\n"
            "Die folgenden Daten zu Wettbewerbern wurden live erhoben "
            "(Websites + aktuelle Nachrichten). Nutze sie fuer Vergleiche, "
            "Positionierung und die Wettbewerbs-Sektion des Berichts.\n\n"
            + "\n\n".join(blocks)
        )
        logger.info(f"Konkurrenzanalyse: Daten zu {hit_count}/{len(competitors)} Wettbewerbern eingebunden")
        return text, hit_count
