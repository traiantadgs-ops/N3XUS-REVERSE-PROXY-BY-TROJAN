# NRP.py (N3XUS REVERSE PROXY)

### Главная суть
NRP.py — это легкий консольный инструмент на Python (Flask) для Termux, который позволяет создавать локальные зеркала сайтов, генерировать публичную ссылку через Cloudflare Tunnel, а также перехватывать введенные пользователями данные с определением их IP, геолокации и статуса VPN/Proxy.

---

### Дисклеймер
⚠️ Данный инструмент создан исключительно в образовательных целях и для тестирования собственных систем безопасности. Любое несанкционированное использование против чужих ресурсов запрещено. Автор не несет ответственности за действия пользователей.

---

### Установка и запуск в Termux
   ```bash
   pkg update && pkg upgrade -y
   pkg install python git cloudflared -y
   pip install flask requests beautifulsoup4
   git clone https://github.com/traiantadgs-
   ops/N3XUS-REVERSE-PROXY-BY-TROJAN.git
   cd NRP.py
   python NRP.py
