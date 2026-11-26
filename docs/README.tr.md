# Subtra

Windows 10/11 üzerinde **GPU gerektirmeden (yalnızca CPU)** çalışan masaüstü
altyazı uygulaması. Video seçersiniz; uygulama konuşmanın dilini kendisi bulur,
metne çevirir, seçtiğiniz dile (21 dil) çevirir, `.srt` üretir ve
isterseniz altyazıyı videoya gömer.

Her şey **yerel ve ücretsiz**: ücretli servis, API anahtarı, kayıt yok.
İnternet yalnızca model/FFmpeg **ilk** indirmesinde kullanılır.

**Diller:** [English](../README.md) · Türkçe (bu dosya)

> **Depo hakkında:** Bu repoda yalnızca kaynak kod bulunur. Model dosyaları
> (`models/`), FFmpeg (`ffmpeg/`), video ve altyazı dosyaları repoya
> **dahil edilmez** — hepsi ilk çalıştırmada otomatik indirilir veya sizin
> tarafınızdan indirilir. Ayrıntı: [Modeller](#5-modeller-otomatik-tek-seferlik).

---

## Sürüm politikası

| Dal | İçerik |
|---|---|
| `main` | Yalnızca **kararlı sürümler**. Her sürüm etiketlenir (`v2.0.1`). |
| `development` | Aktif geliştirme. Kararsız olabilir. |

`main` dalına doğrudan commit atılmaz; değişiklikler `development` dalında
geliştirilip kararlı hâle geldiğinde `main`'e alınır ve etiketlenir.

```bash
git checkout development     # geliştirme
git checkout main            # kararlı sürüm
```

---

## 2.0'da neler yeni

**Dağıtım ve kararlılık**
- FFmpeg artık elle kurulmuyor: exe'ye gömülü varsa kullanılır, yoksa
  **ilk kullanımda otomatik indirilir** (`%LOCALAPPDATA%\Subtra\tools\ffmpeg`).
  İki ayrı kaynak (gyan.dev + BtbN) ve ilerleme/iptal desteği var.
- Tüm yazılabilir veriler `%LOCALAPPDATA%\Subtra` altında — Program Files'a
  kurulumda bile izin sorunu yok. Eski `models\` klasörü otomatik tanınır;
  eski `VideoCeviri` veri klasörü de taşınır, modeller yeniden indirilmez.
- Dönen log dosyası (`logs\subtra.log`, 2 MB × 3) ve **"Hata Raporunu
  Kopyala"** / **"Raporu Kaydet…"** düğmeleri.
- CPU thread sayısı **fiziksel çekirdeğe** göre seçilir (hyper-threading sayılmaz).

**Altyazı kalitesi**
- **Kelime düzeyinde zaman damgası** (`word_timestamps=True`): altyazı artık
  kelimenin ortasından kesilmiyor.
- Bölme kararı noktalama + sessizlik + süre sınırına göre verilir; karakter
  sayısı yalnızca satır içi sarma için kullanılır.
- Cümle birleştirme + çeviri sonrası oransal zaman dağıtımı.
- **CPS (saniyedeki karakter) kuralı**: varsayılan 18. Aşan altyazının süresi
  uzatılır; bölme kullanılmaz çünkü bölmek CPS'i düşürmez (aynı karakter /
  aynı süre).
- **Altyazı ölçeği**: `font_size` değeri "640 piksel yükseklik" referansına
  göre tanımlıdır ve gerçek video boyutuna ölçeklenir. libass'ın varsayılan
  `PlayResY=288` kutusu 1918 piksel yüksek videoda yazıyı **6.7 kat** büyütüp
  ekranı kaplıyordu; artık `PlayResX/PlayResY` video boyutuna eşitlenir.
- **Burn-in kodlayıcı**: `crf 18` + `preset slow` + `ref=5` +
  `aq-mode=3` + `deblock=1,1` + doğru H.264 level. Eski `crf 20 / medium /
  ref=3 / level 4.0` kombinasyonu karanlık sahnelerde ölçülebilir bloklanma
  üretiyordu (bkz. aşağıdaki teşhis notu).

**Performans**
- Uzun videolar **10 dakikalık dilimler** hâlinde işlenir: bellek sabit kalır,
  iptal çok daha hızlı sonuçlanır. Dilim sınırında kelime tekrarı temizlenir.
- Transkripsiyon + çeviri **paralel (pipeline)** çalışabilir. 6+ fiziksel
  çekirdekte otomatik açılır; altında kapalı kalır (thread'ler birbirini çalar).

**Üretkenlik**
- **Kuyruk sekmesi**: birden fazla video ekleyin, sırayla işlensin. Modeller
  bir kez yüklenir, tüm kuyruk boyunca bellekte kalır.
- **SRT Çevir sekmesi**: var olan `.srt` dosyasını çevirin — transkripsiyon
  atlanır, isteğe bağlı video ile burn-in/soft-sub yapılır. Bu sekmenin
  **kendi hedef dil ve çıktı seçimi** vardır; Video sekmesinden bağımsızdır.
- **Dosya adı çakışması yok**: çıktı adı hedef dili taşır (`film_tr.srt`,
  `film_de.srt`). Aynı video farklı dillere çevrildiğinde dosyalar birbirinin
  üzerine yazmaz.
- **Önbellek yönetimi**: Ayarlar'da modelleri boyutlarıyla görün, seçip silin.

---

## Özellikler

- Otomatik dil tespiti (Whisper) + güven oranı göstergesi
- Zaman damgalı transkripsiyon (faster-whisper, CPU, `int8`, VAD)
- Cümle bazlı, bağlamı koruyan çeviri (NLLB-200 distilled 600M, CTranslate2)
- Hedef dil: **21 dil** (Türkçe, İngilizce, Almanca, Fransızca, İspanyolca,
  Rusça, Arapça, Çince, Japonca, Korece, Hintçe, Portekizce, İtalyanca,
  Farsça, Endonezce, Urduca, Bengalce, Vietnamca, Tamilce, Telugu, Marathi)
- Kaynak dil = hedef dil ise çeviri otomatik atlanır
- Üç çıktı modu: burn-in (`libx264`, ses kopyalanır), yumuşak altyazı
  (yeniden kodlama yok), sadece `.srt`
- Altyazı stili: boyut, renk, konum (Arial — Türkçe karakterler sorunsuz)
- Satır başına ≈42 karakter, en fazla 2 satır; kısa altyazılar birleştirilir
- Aşamalı ilerleme, canlı log paneli, **İptal** düğmesi
- Tüm ağır işler `QThread` içinde — arayüz donmaz
- Boşluklu / Türkçe karakterli yollar sorunsuz (UTF-8, `shell=True` yok)
- Geçici dosyalar iş sonunda veya iptalde silinir
- Türkçe hata mesajları

---

## Proje yapısı

| Dosya | Görev |
|---|---|
| `main.py` | Giriş noktası; DPI, bağımlılık kontrolü, log başlatma |
| `gui.py` | PySide6 arayüzü: 4 sekme (Video / Kuyruk / SRT / Ayarlar) |
| `worker.py` | `ModelCache`, `JobRunner`, `VideoWorker`, `BatchWorker` |
| `transcriber.py` | Whisper indirme/yükleme, **parçalı** transkripsiyon, kelime damgası |
| `translator.py` | NLLB indirme/yükleme, batch çeviri, `TranslationPipeline` |
| `subtitles.py` | Kelime tabanlı cue üretimi, satır sarma, CPS, SRT yaz/oku |
| `ffmpeg_utils.py` | Ses çıkarma, burn-in, soft-sub, yol escape, disk kontrolü |
| `ffmpeg_bootstrap.py` | FFmpeg bulma + **otomatik indirme** |
| `app_paths.py` | `%LOCALAPPDATA%` yolları, eski klasör taşıma |
| `hardware.py` | Fiziksel çekirdek/RAM, thread bütçesi, model önerisi |
| `logging_setup.py` | Dönen dosya logu + arayüz kuyruğu |
| `error_report.py` | Kopyalanabilir hata raporu |
| `errors.py` | Ortak istisna tipleri |
| `languages.py` | Whisper → NLLB eşlemesi, 21 hedef dil, dosya adı ekleri |
| `Subtra.spec` / `build.ps1` | PyInstaller paketleme |
| `requirements.txt` | Python bağımlılıkları |
| `test/` | Doğrulama betikleri |

---

## 1. Python kurulumu

Python 3.10 – 3.14 desteklenir (3.13 ve 3.14 ile test edildi).

```powershell
py --version
```

Sanal ortam (önerilir):

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

PowerShell engelliyorsa:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

## 2. Bağımlılıklar

```powershell
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
```

## 3. Visual C++ Redistributable (çok önemli)

Çeviri motoru **CTranslate2** yerel bir C++ kütüphanesidir. Windows'ta eski bir
`MSVCP140.dll` (ör. 14.29) varsa model yüklenirken uygulama **aniden kapanır**
(hata mesajı çıkmaz). Bu makinede tam olarak bu sorun yaşandı.

```powershell
winget install --id Microsoft.VCRedist.2015+.x64 -e
```

veya elle: <https://aka.ms/vs/17/release/vc_redist.x64.exe> → **yeniden başlatın**.

Kontrol:

```powershell
(Get-Item C:\Windows\System32\MSVCP140.dll).VersionInfo.FileVersion
```

**14.30 veya üzeri** olmalı. Uygulama bunu Ayarlar → *Çeviri motoru* →
**Kontrol Et** ile ayrı bir süreçte test eder ve gerekirse Türkçe açıklama
gösterir.

## 4. FFmpeg

**Elle bir şey yapmanız gerekmiyor.** Uygulama sırayla şuraya bakar:

1. Ayarlar'da seçtiğiniz yol
2. Exe yanındaki `ffmpeg\bin\`
3. `%LOCALAPPDATA%\Subtra\tools\ffmpeg\bin` (daha önce indirilmiş)
4. `PATH`

Hiçbiri yoksa Ayarlar → **FFmpeg'i İndir** (~90 MB) veya elle **ffmpeg.exe
Yolu Seç…**. İndirme arka planda çalışır, arayüz donmaz.

> `ffmpeg.exe` ve `ffprobe.exe` **aynı klasörde** olmalıdır.

## 5. Modeller (otomatik, tek seferlik)

İlk kullanımda indirilir, `%LOCALAPPDATA%\Subtra\models` altına yazılır
(eski bir `models\` klasörünüz varsa o kullanılır):

| Model | Boyut | Ne zaman |
|---|---|---|
| `faster-whisper-tiny` | ~75 MB | tiny seçilirse |
| `faster-whisper-base` | ~145 MB | base seçilirse |
| `faster-whisper-small` | ~484 MB | small |
| `faster-whisper-medium` | ~1.5 GB | medium |
| `nllb-200-distilled-600M-ct2-int8` | ~615 MB | ilk çeviride |

İndirme tamamlandıktan sonra program **tamamen çevrimdışı** çalışır.
Ayarlar sekmesinden modelleri görüp silebilirsiniz.

---

## Kullanım

```powershell
py main.py
```

veya `calistir.bat` dosyasına çift tıklayın.

### Video sekmesi
1. Videoyu sürükleyip bırakın veya **Dosya Seç…**
2. **Whisper modeli** (öneri donanıma göre otomatik seçilir)
3. **Hedef dil**: 21 dilden biri
4. **Çıktı**: burn-in / yumuşak altyazı / sadece `.srt`
5. Burn-in için stil ayarlayın → **Başlat**

### Kuyruk sekmesi
Birden fazla video sürükleyin → **Kuyruğu Başlat**. Her dosya için durum ve
çıktı adı tabloda görünür; hatada kuyruk devam eder ve sonda özet verilir.

### SRT Çevir sekmesi
Var olan `.srt` dosyasını bırakın. İsterseniz bir video da seçin (burn-in veya
yumuşak altyazı için). **Kaynak dil** seçilmezse metinden tahmin edilir.

**Hedef dil** bu sekmede ayrıca seçilir — Video sekmesindeki seçimden
etkilenmez. **Çıktı** türü de burada belirlenir (sadece .srt / burn-in /
yumuşak altyazı).

### Ayarlar sekmesi
- **CPU thread** / **num_workers** — boş bırakılırsa fiziksel çekirdek sayısı
- **Transkripsiyon + çeviri paralel** — Otomatik / Açık / Kapalı
- **CPS sınırı** — 0 = kapalı, önerilen 17–20
- **Kelime düzeyi damga** — daha doğru bölme, ~%15 daha yavaş
- **FFmpeg**, **çeviri motoru**, **model önbelleği** yönetimi

### Çıktılar

Kaynak dosyanın yanına yazılır:

```
video.mp4
video_tr.srt      ← hedef dil Türkçe ise
video_de.srt      ← hedef dil Almanca ise
video_de.mp4      ← burn-in veya yumuşak altyazı seçildiyse
```

Dosya adındaki ek hedef dili gösterir; böylece aynı videoyu birden fazla
dile çevirdiğinizde hiçbir dosya birbirinin üzerine yazılmaz.

---

## Test (adım adım)

### A. Ortam

```powershell
py --version
py -c "import PySide6, faster_whisper, ctranslate2, tokenizers, requests, psutil; print('bagimliliklar tamam')"
```

### B. Sözdizimi

```powershell
py -m py_compile main.py gui.py worker.py transcriber.py translator.py subtitles.py ffmpeg_utils.py languages.py app_paths.py hardware.py logging_setup.py error_report.py ffmpeg_bootstrap.py errors.py
```

### C. Birim testleri (ağ/model gerekmez)

```powershell
py test/test_subtitles.py        # altyazı motoru
py test/test_version.py          # sürüm tek kaynak
py test/test_download_resume.py  # HTTP Range ile devam ettirme (yerel sunucu)
py test/test_logging.py          # log dosyası + panelde tekrar yok
```

`test_download_resume.py` yerel bir HTTP sunucusu açar, aktarımı yarıda keser
ve `.part` dosyasının korunduğunu, `Range` başlığının gönderildiğini ve son
SHA256'nın eşleştiğini doğrular. İnternet gerekmez.

### D. Motor ve FFmpeg

```powershell
py -c "from translator import check_ctranslate2_runtime; print(check_ctranslate2_runtime())"
py -c "import ffmpeg_bootstrap as b; print(b.describe_ffmpeg())"
```

Beklenen: `None` ve FFmpeg sürüm satırı.

### E. Uçtan uca (gerçek video)

Test videosu **repoda yok** (medya dosyaları git'te yok sayılır). İlk
kullanımda otomatik üretilir:

```powershell
py test/make_fixture.py          # test/konusma ingilizce.mp4 üret
py test/make_fixture.py --check  # sadece durumu göster
```

Üretim Windows SAPI (İngilizce konuşma) + FFmpeg ile yapılır. İngilizce SAPI
sesi yoksa video üretilemez ve modele bağlı testler `SKIP` verir (hata değil).

```powershell
py test/test_transcribe.py     # dilimleme + kelime damgası
py test/test_runner.py         # srt / burn / pipeline / SRT içe aktarma
py test/test_queue.py          # kuyruk + model yeniden kullanımı
py test/run_cancel_test.py 2500   # iptal + temp temizliği
```

### F. Arayüz

```powershell
py test/gui_screenshot.py "test\konusma ingilizce.mp4"
```

`test/gui_tab_*.png` dosyalarını üretir.

### G. Tüm paket

```powershell
py test/run_all.py            # SKIP hata sayılmaz
py test/run_all.py --strict   # SKIP de hata (CI için)
```

Çıkış kodları: `0` hepsi geçti/atlandı, `1` başarısız var, `77` hiçbiri koşmadı.

Testler **asla model indirmez**: `test/fixtures.py` `SUBTRA_NO_DOWNLOAD=1`
ayarlar; model yoksa test `SKIP` verir, sessizce yüzlerce MB indirmez.

### G. Hata senaryoları

| Senaryo | Beklenen |
|---|---|
| Sessiz video | "Bu videoda ses kanalı bulunamadı." |
| Bozuk dosya | "Video dosyası çözümlenemedi veya bozuk." |
| FFmpeg yok | Otomatik indirme teklifi |
| İnternet yok (ilk indirme) | "FFmpeg otomatik olarak indirilemedi…" |
| Konuşma yok | "Videoda konuşma bulunamadı." |
| Disk dolu | "Disk dolu… boş alan açıp tekrar deneyin." |
| VC++ eski | Ayarlar'da "ÇALIŞMIYOR" + Türkçe açıklama |

### I. Video kalite teşhisi

Bir videoda piksellenme, yırtılma veya dev altyazı görürseniz:

```powershell
py test/diagnose_quality_report.py "C:\yol\video.mp4"
```

Rapor: altyazı alanı oranı, karanlık bölge bloklanma farkı, SSIM, H.264
level ve bitrate karşılaştırması. `ORTALAMA` satırı `İYİ / KABUL EDİLEBİLİR /
KÖTÜ` verir.

H.264 level uygunluğunu (MaxFS / MaxMBPS / MaxDPB) denetlemek için:

```powershell
py test/check_h264_level.py
```

---

## Exe üretme

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

Bu betik: bağımlılıkları kurar, testleri çalıştırır, PyInstaller ile paketler,
proje içindeki FFmpeg'i `dist` klasörüne kopyalar ve
`Subtra-portable.zip` üretir.

Yalnızca paketleme:

```powershell
py -m PyInstaller Subtra.spec --noconfirm --clean
```

Sonuç:

```
dist\Subtra\
    Subtra.exe
    ffmpeg\bin\ffmpeg.exe      ← PATH gerekmez
    ffmpeg\bin\ffprobe.exe
    _internal\...
```

- **Klasör modu** kullanılır (`--onefile` değil): açılış hızlı, modeller kalıcı.
- FFmpeg'i pakete koymak istemiyorsanız klasörü silin; uygulama ilk açılışta
  indirir.
- Antivirüs yanlış pozitif verirse klasörü istisnaya ekleyin.

---

## Sorun giderme

| Belirti | Çözüm |
|---|---|
| `ModuleNotFoundError` | `py -m pip install -r requirements.txt` |
| Uygulama çeviride sessizce kapanıyor | VC++ Redistributable güncelle (bölüm 3) |
| "Çeviri motoru çalışmıyor" | `winget install --id Microsoft.VCRedist.2015+.x64 -e` |
| FFmpeg bulunamadı | Ayarlar → FFmpeg'i İndir |
| Model indirme başarısız | İnternet/proxy; disk alanı |
| Çeviri yavaş | `tiny`/`base` deneyin, diğer programları kapatın |
| Altyazı çok hızlı akıyor | CPS sınırını düşürün (ör. 15) |
| **Altyazı ekranı kaplıyor / dev yazı** | Güncel sürümü kullanın (ölçek düzeltmesi); Ayarlar → burn-in kalitesi |
| **Karanlık sahnelerde bloklanma/piksellesme** | Burn-in CRF'i 16–18 yapın; eski sürüm 20 kullanıyordu |
| Arayüz bulanık | Windows ölçekleme %100–150 |
| **Siyah cmd penceresi açık kalıyor, Qt DPI uyarısı** | `calistir.bat` ile başlatın (`pyw` kullanır, konsol açılmaz) — 2.1.2'de düzeltildi |
| Bellek yetersiz | Daha küçük model, `num_workers=1` |

Sorun bildirirken **Hata Raporunu Kopyala** düğmesini kullanın; sürüm, sistem,
donanım, FFmpeg, model envanteri, ayarlar ve son 200 log satırı eklenir.

### Geliştirici notları (karşılaşılan gerçek hatalar)

1. **CTranslate2 erişim ihlali (0xC0000005)** — Eski `MSVCP140.dll` (14.29)
   yüzünden `ctranslate2.Translator(...)` tüm süreci çökertiyordu; Python
   `try/except` bunu yakalayamaz. Çözüm: VC++ güncellemesi + ayrı süreçte
   ön kontrol (`translator.check_ctranslate2_runtime`).

2. **NLLB'de eksik EOS token'ı** — Kaynak dizisi `[src_lang] + tokenlar`
   şeklindeydi ve model "Kat Kat Kat…" diye tekrarlıyordu. NLLB kaynak
   dizisinin sonunda `</s>` bekler. Ayrıca `sentencepiece` ID'leri NLLB
   sırasıyla uyuşmaz; `tokenizer.json` + `shared_vocabulary.txt` eşlemesi
   gerekir.

3. **PyAV / faster-whisper uyumsuzluğu** — `av` 19 ile dosya yolu verildiğinde
   `metadata_errors` hatası. Çözüm: WAV'ı `wave` + numpy ile float32 diziye
   okuyup Whisper'a **dizi** vermek.

4. **Dilim sınırında kelime tekrarı** — 10 dakikalık dilimlerde son kelimeler
   tekrar ediyordu. Çözüm: `_duplicate_prefix_len` ile normalize edilmiş
   kelime öneki karşılaştırması.

5. **CPS bölmesi anlamı bozuyordu** — Karakter sayısına göre bölmek cümleyi
   ortadan kesiyordu ve CPS'i zaten düşüremiyordu. Çözüm: kelime damgası +
   noktalama sınırı; CPS yalnızca süre uzatılarak düzeltilir.

6. **Altyazı ekranı kaplıyordu (dev yazı)** — Kullanıcı 1080x1918 dikey videoda
   altyazının devasa çıktığını bildirdi. Neden: libass `force_style` içindeki
   `FontSize` değerini varsayılan `PlayResY=288` kutusuna göre ölçekler.
   `FontSize=18` × (1918/288) = **120 piksel** yazı → 2 satır metin 4 satıra
   taşıp ekranın yarısını kaplıyordu. Çözüm: `PlayResX/PlayResY` video
   boyutuna eşitlenir, punto piksele çevrilir. Ölçüm: altyazı alanı videonun
   %2.58'inden %0.57'sine indi (**%78 küçülme**).

7. **Karanlık sahnelerde bloklanma / piksellesme** — Aynı videoda bildirilen
   ikinci sorun. Teşhis yöntemi: kare kare SSIM + özel **bloklanma ölçütü**
   (8x8 blok sınırlarındaki piksel farkının blok içi farka oranı).

   | Ölçüm | Eski ayarlar | Yeni ayarlar |
   |---|---|---|
   | Altyazısız bölge SSIM | 0.9972 | 0.9978 |
   | Karanlık bölge bloklanma farkı | **+0.209** | **+0.038** |
   | H.264 level | 4.0 | 5.0 |
   | Bitrate | 3066 kbps | 4186 kbps |

   Suçlu bitrate değil, **kodlayıcı ayarlarıydı**: `ref=3`, `aq-mode=1`,
   `deblock=1,0` ve level 4.0. `aq-mode=3` karanlık sahnelere daha fazla bit
   ayırır, `deblock=1,1` blok sınırlarını yumuşatır, `ref=5` tahmini
   iyileştirir. Bloklanma **%82 azaldı**. Ayrıca 1080x1918@30 için level 4.0
   DPB sınırında kalıyordu (ref=5 ile 6 kare saklanamaz); doğru level artık
   `width/height/fps` üzerinden hesaplanıyor.

   Aynı videoda `crf 14` denemek bloklanmayı **düzeltmedi** (+0.189) — yani
   "daha yüksek bitrate" tek başına çözüm değil; doğru `x264-params` gerekli.

---

## Teknik notlar

- **Ses**: FFmpeg ile 16 kHz mono `pcm_s16le` WAV.
- **Parçalama**: WAV `wave` ile 10 dk dilimlere bölünür (ek ffmpeg geçişi yok,
  bellek ~38 MB/dilim). 1 sn örtüşme, dilim başında tekrar temizliği.
  Dil ilk dilimde tespit edilir, sonra sabitlenir; bağlam `initial_prompt` ile taşınır.
- **Thread bütçesi**: tek modelde tüm fiziksel çekirdekler; pipeline'da
  %60 Whisper / %40 NLLB.
- **Pipeline**: `queue.Queue(maxsize=8)` üretici-tüketici; kuyruk dolunca
  üretici bekler → bellek sınırlı kalır.
- **Sıralama garantisi**: pipeline sonuçları indeksle saklanır, `finish()`
  sıralı döndürür.
- **Burn-in**: `subtitles` filtresi + `force_style`
  (`FontName=Arial`, renk BGR sırasında `&HAABBGGRR`).
  `PlayResX/PlayResY` video boyutuna eşitlenir ve punto piksele ölçeklenir;
  aksi hâlde yüksek çözünürlüklü videolarda yazı devasa çıkar.
  Kodlayıcı: `crf 18`, `preset slow`, `ref=5:aq-mode=3:deblock=1,1:
  psy-rd=1.0,0.15`, level `h264_level_for(w, h, fps)` ile hesaplanır.
  Yol escape'i iki katmanlı: `C\:/...` ve hata durumunda göreli ad + `cwd`.
- **Yumuşak altyazı**: `.mp4` → `mov_text`, `.mkv` → `srt`, `-c copy`.
- **SRT**: UTF-8 (BOM'suz), LF, `HH:MM:SS,mmm`.
- **İptal**: `threading.Event`; FFmpeg süreci sonlandırılır, dilim döngüsü
  her adımda kontrol eder, geçici dosyalar silinir.

---

## Lisans

Subtra **MIT Lisansı** ile yayımlanır — bkz. [LICENSE](../LICENSE).

İndirilen modeller kendi lisanslarına tabidir:

- faster-whisper / Whisper: MIT
- NLLB-200: CC-BY-NC-4.0 (ticari kullanım için lisansınızı kontrol edin)
- FFmpeg: LGPL/GPL
