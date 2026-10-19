# Universal Farm

![Menu utama](assets/menu-utama.jpg)

Tool TUI buat farming API key dari beberapa provider AI sekaligus. Key yang didapat bisa langsung diinject ke 9Router, dan tiap farm selesai ada notifikasi ke Telegram.

Fork dari [hirotomasato/harbor](https://github.com/hirotomasato/harbor), tapi sudah jauh beda dari upstream.

## Provider

| Provider | Cara kerja | Dapat apa per akun |
|---|---|---|
| TokenHarbor | Browser Chromium asli | Akses model gratis |
| Mistral AI | HTTP murni | Jatah gratis Mistral |
| Dahl Inference | HTTP murni, tanpa email | 100 juta token |
| GonkaRouter | HTTP murni, login pakai wallet (SIWE) | USD 20 |

## Screenshot submenu

![Menu TokenHarbor](assets/menu-tokenharbor.jpg)
![Menu Mistral](assets/menu-mistral.jpg)
![Menu Dahl](assets/menu-dahl.jpg)
![Menu GonkaRouter](assets/menu-gonkarouter.jpg)

## Fitur

1. Menu interaktif di terminal, tinggal pilih nomor
2. Key otomatis masuk ke database 9Router (cari node pakai baseUrl, tidak bikin duplikat, key yang sudah ada dilewati)
3. Notifikasi Telegram tiap farm selesai: ringkasan + daftar key. Buat batch gede, progres dikirim tiap 30 key baru
4. Proxy ganti tiap akun, format `user:pass@host:port`
5. Buat TokenHarbor bisa pilih email sekali pakai: Tempik (punya sendiri) atau Temp Mail (tempmail.lol, langsung jalan)
6. Capsolver opsional, ada saklar ON/OFF. Tanpa capsolver pun farm TokenHarbor tetap jalan karena pakai browser beneran
7. Parallel farm: semua provider jalan bareng di background, aman kalau SSH putus

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/zal-m10/universal-farm/main/install.sh | bash
```

Atau pakai wget:

```bash
wget -qO- https://raw.githubusercontent.com/zal-m10/universal-farm/main/install.sh | bash
```

Installer bakal urus paket sistem (python3, git, curl), clone repo ke `~/universal-farm`, bikin virtualenv + install dependency Python, install Chromium buat Playwright, terus daftarin perintah `farm`.

Abis itu ketik `farm` buat buka menunya.

## Uninstall

```bash
curl -fsSL https://raw.githubusercontent.com/zal-m10/universal-farm/main/uninstall.sh | bash
```

Atau dari dalam aplikasi: menu `[9] Uninstall`.

Ini bakal hapus `~/universal-farm`, perintah `farm`, semua hasil farm (key, progres, state), dan log sementara. 9Router tidak ikut kehapus.

## Install manual

```bash
git clone https://github.com/zal-m10/universal-farm.git
cd universal-farm
python3 -m venv .venv
.venv/bin/pip install playwright requests rich eth-account
.venv/bin/python -m playwright install chromium
```

Di Debian/Ubuntu, install juga dependency OS buat Chromium:

```bash
.venv/bin/python -m playwright install-deps chromium
```

Jalankan:

```bash
.venv/bin/python -m tools.tokenharbor.farm_tui
```

## Menu

| No | Menu | Buat apa |
|---|---|---|
| 1 | Farm TokenHarbor | Bikin akun TokenHarbor pakai browser |
| 2 | Farm Mistral keys | Bikin API key Mistral pakai HTTP |
| 3 | Farm Dahl keys | Bikin API key Dahl pakai HTTP |
| 4 | Farm GonkaRouter keys | Bikin API key GonkaRouter pakai wallet |
| 5 | Parallel farm | Jalanin beberapa farm di background |
| 6 | Delay setting | Jeda antar akun, dalam detik |
| 7 | Setup Proxy | Atur daftar proxy |
| 8 | Setup Bot Tele | Isi token bot dan chat ID Telegram |
| 9 | Uninstall | Hapus semua sampai bersih |
| 0 | Exit | Keluar |

Tiap submenu farm isinya: Run farm (foreground atau background), Results (lihat/salin/hapus key), sama Auto inject 9Router (ON/OFF).

## Setting

### Proxy

Satu proxy per baris di `tools/proxies.txt`:

```
user:pass@host:port
```

Tanda `@` sebelum host itu wajib. Kalau nulisnya `user:pass:host:port` (pakai titik dua), koneksi proxy bakal gagal. File ini tidak ikut ke repo karena isinya kredensial.

### Email sekali pakai (TokenHarbor)

Ada di submenu TokenHarbor. Dua pilihan:

1. Tempik: pakai instansi Tempik sendiri. Tinggal masukin base URL-nya, misal `https://tempik.domainlo.com`.
2. Temp Mail: pakai tempmail.lol, langsung jalan tanpa setting. Tapi kadang email verifikasinya tidak masuk. Kalau begitu, pakai Tempik saja.

### Capsolver (TokenHarbor)

Opsional. Ada saklar ON/OFF. Tanpa capsolver pun tidak masalah karena signup pakai browser Chromium beneran, jadi Turnstile keverifikasi otomatis. Key-nya disimpan di `tools/.capsolver_key`, tidak ikut ke repo.

### Bot Telegram

Isi Bot Token (bikin di BotFather) dan Chat ID di menu `[8]`. Tiap farm selesai bakal kirim ringkasan + daftar API key ke Telegram. Kalau batch gede, progres dikirim tiap ada 30 key baru.

## Cara kerja inject 9Router

Kalau dinyalain, key hasil farm otomatis masuk ke SQLite 9Router di `/var/lib/9router/db/data.sqlite`:

1. Node dicari pakai baseUrl, bukan nama. Jadi kalau node sudah ada, dipakai ulang, tidak bikin baru.
2. Prefix bawaan: `HrbrFarm` (TokenHarbor), `mstrlfarm` (Mistral), `DahlFarm` (Dahl), `gofarm` (GonkaRouter).
3. Key yang sudah ada dilewati. Dijalanin berkali-kali pun aman.

## File hasil

| Provider | Lokasi |
|---|---|
| TokenHarbor | `account.json` di folder repo |
| Mistral | `/root/mistral_keys.txt` |
| Dahl | `/root/dahl_keys.txt` |
| GonkaRouter | `/root/gonka_keys.txt` |

File kredensial dan proxy tidak diikutkan ke repo.

## Di Termux (Android)

```bash
pkg update -y && pkg install -y python git curl
git clone https://github.com/zal-m10/universal-farm
cd universal-farm
python -m venv .venv
.venv/bin/pip install requests rich
```

Chromium tidak jalan di Android, jadi Farm TokenHarbor yang butuh browser tidak bisa dipakai di Termux. Pakai VPS buat itu. Farm Mistral, Dahl, dan GonkaRouter yang murni HTTP jalan normal di Termux.

## Kalau ada masalah

**`farm: command not found`.** Installer naruhnya di `~/.local/bin`. Tambahin ke PATH:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

**`ERR_PROXY_CONNECTION_FAILED`.** Cek format proxy, harus `user:pass@host:port` pakai `@`.

**Muncul "You're doing that a bit fast".** Ini limit dari server TokenHarbor, bukan dari IP atau email. Berhenti dulu beberapa jam, terus coba 1 akun aja dengan jeda panjang.

**Email verifikasi tidak masuk (Temp Mail).** Ganti ke Tempik.

**GonkaRouter sering 401 habis timeout.** Nonce SIWE cuma sekali pakai. Versi terbaru sudah ambil nonce baru tiap retry. Update pakai `git pull`.

## Lisensi

MIT
