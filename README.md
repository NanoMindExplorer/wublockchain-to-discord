# wublockchain-to-discord (Bahasa Indonesia)

Mirror berita Wu Blockchain dari channel Telegram publik
[`wublockchainenglish`](https://t.me/s/wublockchainenglish) ke channel
Discord — **dalam Bahasa Indonesia**.

Postingan aslinya berbahasa Inggris; setiap berita di-auto-translate ke
Bahasa Indonesia dulu, baru dikirim ke Discord (webhook `DC_WEBHOOK`,
bot "Kabar Burung"). Jadi channel Discord menerima berita Wu Blockchain
yang sudah berbahasa Indonesia.

Berjalan di GitHub Actions (`mirror.yml`): polling tiap 30 detik, job
di-restart tiap 5 jam. State (`state.json`, `last_post`) di-commit kembali
ke repo supaya cursor tidak hilang saat job restart. Satu postingan baru
hanya ditandai "terkirim" setelah Discord menerimanya (HTTP 200/204) —
kalau gagal, dicoba lagi di siklus berikutnya tanpa duplikat.

## Terjemahan (kenapa akurat)

Terjemahan ke Bahasa Indonesia dilakukan per paragraf, lalu melewati
**glossary kripto** yang mengembalikan istilah yang biasa dirusak mesin
penerjemah (ticker, nama proyek, jargon kripto tetap utuh; angka, tanggal,
dan URL tidak disentuh). Kalau terjemahan gagal, teks asli tetap dikirim
supaya beritanya tidak hilang.

- **Default (tanpa kunci):** Google Translate (endpoint gratis, tanpa
  API key). Sudah diuji pada berita asli — hasilnya natural, misal
  *"Bitcoin ETF inflows hit $1.2 billion…"* → *"Arus masuk Bitcoin ETF
  mencapai $1.2 miliar…"*, angka `$1.2 billion` → `$1.2 miliar`,
  `4.2%` → `4,2%`, `50,000 ETH` → `50.000 ETH`.
- **Opsional (lebih akurat):** DeepL free API (`DEEPL_API_KEY`). Kalau
  diisi, DeepL dipakai dulu; kalau DeepL gagal, otomatis jatuh ke Google.
  Daftar gratis di [deepl.com](https://www.deepl.com/pro-api) (500rb
  karakter/bulan, tanpa kartu kredit), lalu tambahkan sebagai Secret
  `DEEPL_API_KEY` di repo → Settings → Secrets and variables → Actions.

## Menjalankan lokal

```bash
export DC_WEBHOOK="https://discord.com/api/webhooks/..."   # wajib
export CHANNEL="wublockchainenglish"                        # default
export TARGET_LANG="id"                                     # default
export DEEPL_API_KEY="..."                                  # opsional
python3 mirror.py --loop 330   # mirror realtime 330 menit
python3 mirror.py              # sekali jalan (snapshot + keluar)
```

## File

- `mirror.py` — polling + parsing + terjemahan + pengiriman ke Discord
  (tanpa dependensi, hanya stdlib Python).
- `state.json` — cursor (`last_post`).
- `.github/workflows/mirror.yml` — jadwal GitHub Actions.
- `.github/workflows/diagnose.yml` — cek manual apakah halaman `t.me/s/…`
  masih bisa dibaca.
