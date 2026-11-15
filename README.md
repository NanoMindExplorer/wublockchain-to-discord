# wublockchain-to-discord (+ Telegram Bahasa Indonesia)

Mirror berita Wu Blockchain dari channel Telegram publik
[`wublockchainenglish`](https://t.me/s/wublockchainenglish) ke:

| Tujuan | Isi | Cara |
|---|---|---|
| **Discord** (webhook) | Teks asli (Inggris) | `DC_WEBHOOK` |
| **Telegram** (channel) | **Auto-translate ke Bahasa Indonesia** | `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` |

Kedua tujuan independen: kalau salah satu belum diisi, yang lain tetap
jalan. Satu postingan baru hanya ditandai "terkirim" setelah **semua**
tujuan yang aktif menerimanya — kalau satu gagal, postingan itu dicoba
lagi di siklus berikutnya tanpa duplikat (status per-tujuan dicatat di
`state.json`).

Berjalan di GitHub Actions (`mirror.yml`): polling tiap 30 detik, job
di-restart tiap 5 jam. State (`state.json`, `last_post`) di-commit kembali
ke repo supaya cursor tidak hilang saat job restart.

## Terjemahan (kenapa akurat)

Sumbernya berbahasa Inggris. Terjemahan ke Bahasa Indonesia dilakukan
per paragraf, lalu melewati **glossary kripto** yang mengembalikan istilah
yang biasa dirusak mesin penerjemah (ticker, nama proyek, jargon kripto
tetap utuh; angka, tanggal, dan URL tidak disentuh). Kalau terjemahan
gagal, teks asli tetap dikirim supaya beritanya tidak hilang.

- **Default (tanpa kunci):** Google Translate (endpoint gratis, tanpa
  API key). Sudah diuji pada berita asli — hasilnya natural, misal
  *"Bitcoin ETF inflows hit $1.2 billion…"* → *"Arus masuk Bitcoin ETF
  mencapai $1.2 miliar…"*, angka `$1.2 billion` → `$1.2 miliar`,
  `4.2%` → `4,2%`, `50,000 ETH` → `50.000 ETH`.
- **Opsional (lebih akurat):** DeepL free API (`DEEPL_API_KEY`). Kalau
  diisi, DeepL dipakai dulu; kalau DeepL gagal, otomatis jatuh ke Google.

## Setup Telegram (5 menit)

1. **Buat bot:** buka [@BotFather](https://t.me/BotFather) di Telegram →
   `/newbot` → ikuti petunjuk → salin **token** bot-nya.
2. **Buat / pilih channel Telegram** yang mau menerima berita (misal
   channel baru khusus berita).
3. **Jadikan bot admin channel itu:** buka channel → edit → Administrators
   → tambahkan bot → beri izin **Post Messages**. (Tanpa ini bot tidak
   bisa mengirim.)
4. **Dapatkan Chat ID channel:**
   - Kalau channel publik (`t.me/namachannel`): Chat ID-nya `@namachannel`.
   - Kalau channel privat: kirim satu pesan ke channel, lalu buka
     `https://api.telegram.org/bot<TOKEN>/getUpdates` dan cari
     `"chat":{"id": -100xxxxxxxxxx}` — angka itu Chat ID-nya.
5. **Tambahkan Secrets di GitHub:** repo → Settings → Secrets and
   variables → Actions → New repository secret:
   - `TELEGRAM_BOT_TOKEN` = token dari BotFather
   - `TELEGRAM_CHAT_ID` = `@namachannel` atau `-100xxxxxxxxxx`
   - `DEEPL_API_KEY` = (opsional) kunci DeepL free API
   - `DC_WEBHOOK` = (sudah ada) webhook Discord, kalau mau tetap kirim ke Discord
6. **Jalankan:** Actions → `wublockchain-to-discord` → Run workflow →
   mode `once` untuk tes sekali, atau biarkan jadwal otomatis (tiap 5 jam).

## Menjalankan lokal

```bash
export DC_WEBHOOK="https://discord.com/api/webhooks/..."   # opsional
export TELEGRAM_BOT_TOKEN="123456:ABC..."                   # opsional
export TELEGRAM_CHAT_ID="@namachannel"                      # opsional
export CHANNEL="wublockchainenglish"                        # default
python3 mirror.py --loop 330   # mirror realtime 330 menit
python3 mirror.py              # sekali jalan (snapshot + keluar)
```

Butuh minimal satu tujuan (Discord dan/atau Telegram). Tanpa keduanya,
script berhenti dengan pesan error.

## File

- `mirror.py` — polling + parsing + terjemahan + pengiriman (tanpa dependensi,
  hanya stdlib Python).
- `state.json` — cursor (`last_post`) + catatan pengiriman per postingan.
- `.github/workflows/mirror.yml` — jadwal GitHub Actions.
- `.github/workflows/diagnose.yml` — cek manual apakah halaman `t.me/s/…`
  masih bisa dibaca.
