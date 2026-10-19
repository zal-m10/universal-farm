# Universal Farm

Perkakas terminal interaktif untuk membuat API key dari beberapa penyedia layanan AI secara otomatis. Hasilnya dapat langsung dimasukkan ke database 9Router dan laporannya dikirim ke Telegram.

Dikembangkan dari [hirotomasato/harbor](https://github.com/hirotomasato/harbor).

## Tampilan

![Menu utama](assets/menu-utama.jpg)

![Menu TokenHarbor](assets/menu-tokenharbor.jpg)

![Menu Mistral](assets/menu-mistral.jpg)

![Menu Dahl](assets/menu-dahl.jpg)

![Menu GonkaRouter](assets/menu-gonkarouter.jpg)

## Penyedia yang didukung

| Penyedia | Metode | Imbalan per akun |
|---|---|---|
| TokenHarbor | Browser Chromium | Akses model gratis |
| Mistral AI | HTTP murni | Tier gratis Mistral |
| Dahl Inference | HTTP murni, tanpa email | 100 juta token |
| GonkaRouter | HTTP murni, SIWE wallet | USD 20 |

## Kemampuan utama

1. Antarmuka terminal interaktif dengan menu bernomor
2. Injeksi otomatis ke 9Router berbasis baseUrl, idempoten dan lewati duplikat
3. Notifikasi Telegram berisi ringkasan dan daftar key tiap run, termasuk progres tiap 30 key untuk batch besar
4. Rotasi proxy per akun dengan format `user:pass@host:port`
5. Pilihan surel sekali pakai: Tempik (instansi sendiri) atau Temp Mail (tempmail.lol, tanpa setup)
6. Capsolver opsional dengan saklar ON/OFF
7. Parallel farm: semua penyedia berjalan di background sekaligus dan tahan putus SSH

## Instalasi

Satu baris perintah:

```bash
curl -fsSL https://raw.githubusercontent.com/zal-m10/universal-farm/main/install.sh | bash
```

Atau dengan wget:

```bash
wget -qO- https://raw.githubusercontent.com/zal-m10/universal-farm/main/install.sh | bash
```

Pemasang akan mengurus paket sistem (python3, git, curl), mengklon repo ke `~/universal-farm`, membuat virtualenv beserta dependensi Python, memasang Chromium untuk Playwright, lalu mendaftarkan perintah `farm`.

Setelah selesai, ketik `farm` untuk membuka menu.

## Uninstall

Satu baris perintah:

```bash
curl -fsSL https://raw.githubusercontent.com/zal-m10/universal-farm/main/uninstall.sh | bash
```

Atau dari dalam aplikasi: menu `[9] Uninstall`.

Perintah ini menghapus `~/universal-farm`, perintah `farm`, seluruh hasil farm (key, progres, state), dan log sementara. Instalasi 9Router tidak ikut tersentuh.

## Instalasi manual

```bash
git clone https://github.com/zal-m10/universal-farm.git
cd universal-farm
python3 -m venv .venv
.venv/bin/pip install playwright requests rich eth-account
.venv/bin/python -m playwright install chromium
```

Pada Debian/Ubuntu, pasang juga dependensi OS untuk Chromium:

```bash
.venv/bin/python -m playwright install-deps chromium
```

Jalankan:

```bash
.venv/bin/python -m tools.tokenharbor.farm_tui
```

## Panduan menu

Menu utama:

| No | Menu | Fungsi |
|---|---|---|
| 1 | Farm TokenHarbor | Buat akun TokenHarbor via browser |
| 2 | Farm Mistral keys | Buat API key Mistral AI via HTTP |
| 3 | Farm Dahl keys | Buat API key Dahl Inference via HTTP |
| 4 | Farm GonkaRouter keys | Buat API key GonkaRouter via SIWE |
| 5 | Parallel farm | Jalankan beberapa farm di background |
| 6 | Delay setting | Jeda antar akun dalam detik |
| 7 | Setup Proxy | Kelola daftar proxy |
| 8 | Setup Bot Tele | Token bot dan chat ID Telegram |
| 9 | Uninstall | Hapus seluruh instalasi farm |
| 0 | Exit | Keluar |

Tiap submenu farm berisi: Run farm (foreground atau background), Results (lihat, salin, hapus), dan Auto inject 9Router (ON/OFF).

## Konfigurasi

### Proxy

Satu proxy per baris di `tools/proxies.txt` dengan format:

```
user:pass@host:port
```

Tanda `@` sebelum host bersifat wajib. Format `user:pass:host:port` (tanpa `@`) akan membuat koneksi proxy gagal. Berkas ini tidak ikut ke repo karena berisi kredensial.

### Surel sekali pakai

Tersedia di submenu TokenHarbor. Dua opsi:

1. Tempik: instansi Tempik milik sendiri. Masukkan base URL-nya, contoh `https://tempik.domainanda.com`.
2. Temp Mail: memakai tempmail.lol tanpa setup apa pun (bawaan). Perlu dicatat pengiriman surel verifikasi ke domain temp mail kadang tidak konsisten. Bila kode verifikasi tidak kunjung masuk, gunakan Tempik.

### Capsolver

Opsional, tersedia di submenu TokenHarbor. Farm tetap berjalan normal tanpanya karena signup memakai browser Chromium asli sehingga Turnstile terverifikasi secara native. Kunci API disimpan di `tools/.capsolver_key` dan tidak ikut ke repo.

### Bot Telegram

Isi Bot Token (dari BotFather) dan Chat ID pada menu `[8]`. Setiap farm selesai akan mengirim ringkasan beserta daftar API key ke Telegram. Untuk batch besar, progres dikirim setiap 30 key baru.

## Integrasi 9Router

Bila diaktifkan, key hasil farm otomatis masuk ke SQLite 9Router di `/var/lib/9router/db/data.sqlite`:

1. Node dicari berdasarkan baseUrl, bukan nama. Node yang sudah ada dipakai ulang sehingga tidak terjadi duplikat.
2. Prefix bawaan: `HrbrFarm` (TokenHarbor), `mstrlfarm` (Mistral), `DahlFarm` (Dahl), `gofarm` (GonkaRouter).
3. Key yang sudah tercatat dilewati. Menjalankan ulang bersifat idempoten dan aman.

## Lokasi berkas hasil

| Penyedia | Berkas |
|---|---|
| TokenHarbor | `account.json` di folder repo |
| Mistral | `/root/mistral_keys.txt` |
| Dahl | `/root/dahl_keys.txt` |
| GonkaRouter | `/root/gonka_keys.txt` |

Berkas kredensial dan proxy tidak di commit ke repo.

## Catatan Termux (Android)

```bash
pkg update -y && pkg install -y python git curl
git clone https://github.com/zal-m10/universal-farm
cd universal-farm
python -m venv .venv
.venv/bin/pip install requests rich
```

Chromium Playwright tidak berjalan di Android, sehingga Farm TokenHarbor (yang butuh browser) tidak dapat dipakai di Termux. Gunakan VPS untuk itu. Farm Mistral, Dahl, dan GonkaRouter yang murni HTTP berjalan normal di Termux.

## Pemecahan masalah

**Perintah `farm` tidak ditemukan.** Pemasang menaruhnya di `~/.local/bin`. Tambahkan ke PATH:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

**`ERR_PROXY_CONNECTION_FAILED`.** Periksa format proxy: harus `user:pass@host:port` dengan `@` sebelum host.

**Pesan "You're doing that a bit fast".** Ini batas laju signup TokenHarbor di sisi server, bukan dari IP atau surel. Hentikan total beberapa jam, lalu coba satu akun dengan jeda panjang.

**Surel verifikasi tidak masuk (Temp Mail).** Beralih ke Tempik (instansi sendiri) yang pengirimannya lebih konsisten.

**GonkaRouter sering 401 setelah timeout.** Nonce SIWE hanya sekali pakai. Versi terbaru mengambil nonce baru pada tiap percobaan ulang. Perbarui via `git pull`.

## Lisensi

MIT
