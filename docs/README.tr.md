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

## 2.0–2.3'te neler yeni

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
  bir kez yüklenir, tüm kuyruk boyunca bellekte kalır. **Her kuyruk satırının
  kendi hedef dili vardır** — tek çalıştırmada bir video birden fazla dile
  çevrilebilir ve transkripsiyon yalnızca bir kez yapılır.
- **Transkript önbelleği**: Whisper çıktısı `cache/transcripts/` altına
  yazılır ve yeniden kullanılır. Aynı videoyu ikinci bir dile çevirmek
  transkripsiyonu tamamen atlar — test klibinde **2.32×** daha hızlı ölçüldü
  (24.6 sn → 10.6 sn). Anahtar dosya boyutu, mtime, model boyutu ve kelime
  damgası modunu içerir; video düzenlenirse veya model değişirse önbellek
  geçersiz olur. Ayarlar'dan kapatılabilir ve temizlenebilir.
- **Whisper batch modu** (Ayarlar): `BatchedInferencePipeline` ile CPU'da daha
  hızlı çıkarım — ölçülen: `tiny` 1.82×, `small` 1.17–1.34×. Varsayılan kapalı.
- **SRT Çevir sekmesi**: var olan `.srt` dosyasını çevirin — transkripsiyon
  atlanır, isteğe bağlı video ile burn-in/soft-sub yapılır. Bu sekmenin
  **kendi hedef dil ve çıktı seçimi** vardır; Video sekmesinden bağımsızdır.
- **Dosya adı çakışması yok**: çıktı adı hedef dili taşır (`film_tr.srt`,
  `film_de.srt`). Aynı video farklı dillere çevrildiğinde dosyalar birbirinin
  üzerine yazmaz.
- **Önbellek yönetimi**: Ayarlar'da modelleri boyutlarıyla görün, seçip silin.
  Transkript önbelleğinin boyutu, kayıt sayısı ve temizleme düğmesi hemen
  yanındadır.
- **Videoya işlemeden önce altyazı önizlemesi** (2.2.0+): `.srt` yazıldıktan
  sonra uygulama durur ve düzenlenebilir bir önizleme gösterir. Metni veya
  zamanlamayı video kodlanmadan önce düzeltebilir, isterseniz yalnızca `.srt`
  üretebilirsiniz. "Bir daha sorma" seçimi hatırlanır. Ayarlar'dan kapatılır.
- **Sessiz üzerine yazma yok**: *üzerine yaz* kapalıysa mevcut çıktılar
  korunur, yeni dosyalar `_2`, `_3`… ekiyle yazılır.

---

## 2.4'te neler yeni

**Terim sözlüğü**
- TSV terim listesi (`kaynak<TAB>hedef`, isteğe bağlı `en>tr` sütunu) marka ve
  teknik terimleri çevirmenin elinden alır. Terimler çeviriden önce NLLB'nin
  koruduğu `[[G0]]` yer tutucularına çevrilir, sonra hedef karşılıklar yazılır.
  Yer tutucu kaybolursa terim doğrudan değiştirilir; `.srt` dosyasına asla
  `[[G0]]` sızmaz. Şablon: `docs/glossary-ornek.tsv`.
- Büyük/küçük harf eşleşmesi Türkçe `İ/ı/I` sorununu konumları kaydırmadan
  çözer; `C++`, `(beta)` gibi regex karakterleri birebir eşleşir.

**Gömülü altyazı içe aktarma**
- Video sekmesindeki **Gömülü Altyazı Kullan…** videonun içindeki altyazı
  akışlarını listeler (`subrip`, `ass`, `mov_text`…), seçileni `.srt` olarak
  çıkarır ve kaynak dili seçili şekilde **SRT Çevir** sekmesine taşır.
- Görüntü tabanlı akışlar (PGS / VobSub / DVB) boş dosya üretmek yerine net
  bir hata mesajıyla reddedilir.

**Paketleme ve CI**
- `pyproject.toml` (PEP 621, sürüm `version.py`'den) + `subtra` GUI girişi.
- GitHub Actions (`windows-latest`): ruff (yalnızca gerçek hatalar),
  `compileall` ve model indirme kapalıyken tüm test paketi.
- `assets/app.ico` (7 boyut, `tools/make_icon.py` ile üretilir) pencere ve exe
  simgesi.

**Düzeltmeler**
- `translator.ensure_nllb_model()` `SUBTRA_NO_DOWNLOAD=1` ve model yokken
  temiz mesaj yerine `NameError` veriyordu.
- Sürüm testi *en yakın* etiketi karşılaştırdığı için her sürüm yükseltmesinde
  etiket atılana kadar düşüyordu; artık yalnızca `HEAD` üzerindeki tam etikete
  bakar.

**2.4.1 — depo temizliği**
- İç planlama notları depodan çıkarıldı; ağaçta yalnızca kaynak kod, testler,
  kullanıcıya dönük dokümanlar (`README.md`, `docs/README.tr.md`,
  `docs/glossary-ornek.tsv`) ve simge kaldı. İşlevsel değişiklik yok.

---

## 2.5'te neler yeni

**Ses kanalı seçimi**
- Birden fazla ses kanalı olan videolarda (ör. Türkçe + İngilizce dublaj) artık
  **istenen kanal** yazıya dökülür; eskiden her zaman ilk kanal okunuyordu.
  Video sekmesi her kanalı dil, başlık, codec ve kanal sayısıyla listeler;
  seçim sonraki çalıştırmalar için hatırlanır.
- Uçtan uca doğrulandı: 1. kanalda 200 Hz ton, 2. kanalda konuşma olan dosyada
  1. kanal "konuşma bulunamadı", 2. kanal doğru metni veriyor. Olmayan bir kanal
  seçilirse ham FFmpeg çıktısı yerine net Türkçe mesaj çıkar.
- Burn-in ve yumuşak altyazı çıktısı eskisi gibi **tüm** ses kanallarını korur.

**Düzeltmeler**
- **"Kelime düzeyinde zaman damgası" kapatılınca her iş çöküyordu.** Bu ayarla
  faster-whisper `words` döndürmediği için altyazı hattı boş kalıyor ve her
  çalıştırma "konuşma bulunamadı" ile bitiyordu. Segment metni artık sözde
  kelimelere bölünüyor (süre karakter ağırlığına göre dağıtılır); seçenek
  vaat ettiği gibi çalışıyor — ~%15 daha hızlı, bölme biraz daha kaba.

---

## 2.6'da neler yeni

**Paketlenmiş exe artık gerçekten çalışıyor — üç sessiz bozukluk düzeltildi**

Hiçbiri kaynaktan çalıştırırken görünmüyordu; bu yüzden exe uçtan uca
doğrulanana kadar fark edilmedi:

1. **Exe hiç transkripsiyon yapamıyordu.** faster-whisper'ın VAD modeli
   (`silero_vad_v6.onnx`) pakete girmiyordu; her transkripsiyon
   `ONNXRuntimeError: NO_SUCHFILE` ile düşüyordu. `Subtra.spec` artık
   `faster_whisper` veri dosyalarını topluyor.
2. **Motor kontrolü exe'de 60 sn asılıp başarısız oluyordu.** CTranslate2 ön
   kontrolü ayrı süreçte çalışır; donmuş derlemede `sys.executable` =
   `Subtra.exe` olduğu için `-c` kabul edilmiyor, GUI açılıyor ve zaman aşımı
   bekleniyordu. Yani paketlenmiş uygulamada **hiçbir iş başlatılamıyordu**.
   Prob artık kendi `--ct2-probe` bayrağını kullanıyor (yine ayrı süreç, çökme
   izolasyonu korunuyor).
3. Pencere simgesi pakete kopyalanmıyordu.

**Yeni destek girişleri**

```
Subtra.exe --self-check           # modüller, DLL'ler, simge, veri klasörü, modeller
Subtra.exe --smoke-test VIDEO [DIL] [MODEL]
                                  # gerçek Whisper + NLLB + FFmpeg, SRT yazar
```

İkisi de raporu `%LOCALAPPDATA%\Subtra\` altına yazar (`selfcheck.txt`,
`smoke.txt`) çünkü pencereli exe'de konsol yoktur. "Uygulama çalışmıyor"
diyen kullanıcıya çalıştırtılacak komut budur — rapor sebebi doğrudan söyler.

**Derleme doğrulaması artık derlemenin parçası**

- `test/test_frozen_exe.py` exe'yi derler, `--self-check` ve gerçek
  `--smoke-test` (fixture videodan 5 satır Türkçe) çalıştırır.
- `build.ps1` paketlemeden sonra `--self-check` ve (varsayılan olarak) tam
  frozen testini çalıştırır; `-SkipTests` verilmedikçe bu sınıf hata sessizce
  yayınlanamaz.

---

## 2.7'de neler yeni

**Kuyrukta dosya başına terim sözlüğü**
- Kuyruk tablosuna **Sözlük** sütunu eklendi. Her satır kendi terim listesini
  kullanabilir — on videoluk kuyruk artık tek sözlüğe mahkûm değil.
- Boş hücre "Ayarlar'daki genel sözlüğü kullan" demektir; böylece genel sözlük
  değişince hiç atanmamış satırlar onu izler, kendi dosyası olan satırlar ise
  kendi seçimini korur.
- Satır(lar)ı seçip **Sözlük Seç…**, **Tümüne Uygula** veya **Kaldır**
  kullanılır. Bozuk/olmayan sözlük dosyası uyarıyla reddedilir, satır olduğu
  gibi kalır. Özet satırı kaç dosyanın kendi sözlüğü olduğunu yazar.

| Satır | Sözlük hücresi | Etkin sözlük |
|---|---|---|
| 1 | `—` | Ayarlar → genel |
| 2 | `hukuk.tsv` | `hukuk.tsv` |

Uçtan uca doğrulandı: aynı videonun iki kopyasına satır başına `ALTYAZI_A` ve
`ALTYAZI_B` atandı; iki çıktı sırasıyla `… ALTYAZI_A …` ve `… ALTYAZI_B …`
üretti, çapraz kullanım olmadı (ikinci iş transkripti önbellekten aldı).

**Düzeltme — RAM kontrolü sığan modelleri reddediyordu**

Boş RAM tahmini ~1.4 GB fazlaydı: 6 GB'lik makinede 1.7 GB boşken `tiny` bile
reddediliyordu (11 test koşulamıyordu). Bu makinede ölçüldü:

| Bileşen | Ölçüm |
|---|---|
| Qt GUI + tiny + NLLB, süreç RSS | **863 MB** |
| FFmpeg burn-in tepe (1080p, crf 18) | 164 MB (ayrı süreç) |
| 10 dk WAV dilimi | ~38 MB |
| **Gerçek toplam ihtiyaç** | **~1.0–1.1 GB** |
| Eski tahmin | 2430 MB (`110 + 820 + 1500` pay) |

Overhead sabiti **1500 → 400 MB** indirildi (ölçülen FFmpeg tepesinin ~2.4
katı, büyük videolar için emniyet payı). 2.1 GB boşken kararlar artık
`tiny`/`base`/`small` **kabul**, `medium` **red** — gerçekle uyuşuyor; `medium`
bu makineye gerçekten sığmıyor.

`hardware.check_memory()` ayrıca `available_mb` parametresi kazandı; mantık
makinenin o anki RAM'i yerine sabit değerlerle test ediliyor (eski test makine
yükliyken kırılıyordu).

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
- **Terim sözlüğü** — marka/terimleri çeviri boyunca birebir koru
- **Gömülü altyazı içe aktarma** — videonun içindeki altyazıyı yeniden kullan
- **Ses kanalı seçimi** — çok sesli dosyalarda hangi dublajın yazıya döküleceğini seç
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
| `transcript_cache.py` | Transkript önbelleği (JSON, atomik, dosya+model anahtarlı) |
| `subtitle_preview.py` | Render öncesi SRT önizleme/düzenleme diyaloğu |
| `glossary.py` | Terim sözlüğü: ayrıştırma, yer tutucuyla koruma/geri yazma |
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
3. **Ses kanalı** — dosyada birden fazla ses varsa hangi dublajın yazıya
   döküleceğini seçin (dil, başlık ve kanal sayısı gösterilir)
4. **Hedef dil**: 21 dilden biri
5. **Çıktı**: burn-in / yumuşak altyazı / sadece `.srt`
6. Burn-in için stil ayarlayın → **Başlat**

Videoda zaten altyazı varsa **Gömülü Altyazı Kullan…** seçilen akışı `.srt`
olarak çıkarır ve kaynak dili doldurulmuş şekilde **SRT Çevir** sekmesine
taşır — transkripsiyon gerekmez.

### Kuyruk sekmesi
Birden fazla video sürükleyin → **Kuyruğu Başlat**. Her dosya için durum ve
çıktı adı tabloda görünür; hatada kuyruk devam eder ve sonda özet verilir.

Satır başına **hedef dil** ve **terim sözlüğü** ayarlanır: satırları seçip
tablonun altındaki düğmeleri kullanın. Sözlük hücresi boşsa Ayarlar'daki genel
sözlük geçerlidir.

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
- **Terim sözlüğü** — bir `.tsv` seçin (şablon: `docs/glossary-ornek.tsv`);
  etkin terim sayısı gösterilir ve seçim hatırlanır
- **FFmpeg**, **çeviri motoru**, **model önbelleği** yönetimi

### Terim sözlüğü dosyası

```
# '#' ile başlayan satırlar yorumdur
OpenAI	OpenAI
machine translation	makine çevirisi
benchmark	karşılaştırma testi	en>tr
prompt -> komut
```

Satır başına bir terim: `kaynak<TAB>hedef` (veya `kaynak -> hedef`). Üçüncü
sütun isteğe bağlıdır ve terimi tek bir dil çiftine kısıtlar. Uzun terim kısa
terimden önce gelir, harf/rakamla başlayan terimlerde tam kelime eşleşmesi
aranır, markalar olduğu gibi geçer.

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
py -m py_compile main.py gui.py worker.py transcriber.py translator.py subtitles.py ffmpeg_utils.py languages.py app_paths.py hardware.py logging_setup.py error_report.py ffmpeg_bootstrap.py errors.py version.py transcript_cache.py
```

### C. Birim testleri (ağ/model gerekmez)

```powershell
py test/test_subtitles.py         # altyazı motoru
py test/test_transcriber_units.py # kelime damgası kapalıyken sözde kelimeler
py test/test_audio_select.py      # ses kanalı listeleme/çıkarma (FFmpeg gerekir)
py test/test_queue_glossary.py    # kuyrukta dosya başına sözlük (GUI + gerçek iş)
py test/test_frozen_exe.py        # run_all'da YOK: exe'yi derler, içinden transkripsiyon yapar
py test/test_glossary.py          # sözlük ayrıştırma, koruma/geri yazma, Türkçe harf
py test/test_glossary_pipeline.py # sözlük + çeviri akışı (sahte model)
py test/test_glossary_ui.py       # Ayarlar'daki sözlük seçimi
py test/test_subtitle_import.py   # gömülü akış listeleme/çıkarma (FFmpeg gerekir)
py test/test_packaging.py         # pyproject + CI tutarlılığı
py test/test_ci_workflow.py       # workflow YAML şeması + adımları yerelde
py test/test_model_guard.py       # SUBTRA_NO_DOWNLOAD temiz hata verir
py test/test_icon.py              # assets/app.ico geçerli + bağlı
py test/test_cache_and_batch.py   # transkript önbelleği + batch (~80 sn)
py test/test_version.py           # sürüm tek kaynak
py test/test_download_resume.py   # HTTP Range ile devam ettirme (yerel sunucu)
py test/test_logging.py           # log dosyası + panelde tekrar yok
```

`test_download_resume.py` yerel bir HTTP sunucusu açar, aktarımı yarıda keser
ve `.part` dosyasının korunduğunu, `Range` başlığının gönderildiğini ve son
SHA256'nın eşleştiğini doğrular. İnternet gerekmez.

### C2. CI

`.github/workflows/ci.yml` her push ve pull request'te `windows-latest`
üzerinde çalışır: `ruff check .` (yalnızca gerçek hatalar — sözdizimi, tanımsız
isim), `compileall`, sonra `SUBTRA_NO_DOWNLOAD=1` ve
`QT_QPA_PLATFORM=offscreen` ile `test/run_all.py`. Modele bağlı testler `SKIP`
verir; iş tek bir model indirmeden yeşil kalır.

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
proje içindeki FFmpeg'i `dist` klasörüne kopyalar, **paketi doğrular** ve
`Subtra-portable.zip` üretir.

Yalnızca paketleme:

```powershell
py -m PyInstaller Subtra.spec --noconfirm --clean
```

**Derledikten sonra mutlaka doğrulayın** — açılan exe, çalışan exe demek değil:

```powershell
dist\Subtra\Subtra.exe --self-check        # rapor: %LOCALAPPDATA%\Subtra\selfcheck.txt
py test/test_frozen_exe.py --no-build      # exe üzerinden gerçek transkripsiyon (~1 dk)
```

Sonuç:

```
dist\Subtra\
    Subtra.exe
    assets\app.ico             ← pencere simgesi
    ffmpeg\bin\ffmpeg.exe      ← PATH gerekmez
    ffmpeg\bin\ffprobe.exe
    _internal\
        faster_whisper\assets\silero_vad_v6.onnx   ← VAD için zorunlu
```

- **Klasör modu** kullanılır (`--onefile` değil): açılış hızlı, modeller kalıcı.
- FFmpeg'i pakete koymak istemiyorsanız klasörü silin; uygulama ilk açılışta
  indirir.
- Antivirüs yanlış pozitif verirse klasörü istisnaya ekleyin.
- FFmpeg dahil açılmış boyut **~347 MB**; zip kabaca yarısı.

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
| Bellek yetersiz | Daha küçük model, `num_workers=1` — uygulama model yüklemeden önce boş RAM'i kontrol eder ve takasa girecekse `medium`'ı reddeder |
| Sözlük terimi uygulanmadı | Terimin kaynak yazımını ve varsa `en>tr` sütununu kontrol edin; logda eşleşen/kaybolan terim sayısı yazar |
| "Bu altyazı akışı görüntü tabanlı" | PGS/VobSub metne çevrilemez — metin tabanlı bir akış veya harici `.srt` kullanın |
| Çok sesli dosyada yanlış dil bulundu | Video sekmesindeki **Ses kanalı** listesinden doğru kanalı seçin; varsayılan ilk kanaldır |
| **Paketlenmiş exe açılıyor ama hiçbir iş çalışmıyor** | `Subtra.exe --self-check` çalıştırın; `%LOCALAPPDATA%\Subtra\selfcheck.txt` sebebi yazar |
| CI eski etikette düşüyor | Yalnızca `HEAD` üzerindeki tam etiket karşılaştırılır; sürüm yükseltmesi etiket atılana kadar güvenlidir |

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
- **Bellek**: model yüklemeden önce boş RAM kontrol edilir. Paylar ölçümle
  kalibre edildi: model tahminleri + 400 MB (Qt/FFmpeg/tampon payı). Ölçülen
  gerçek toplam (GUI + tiny + NLLB) 863 MB; tahmin 1330 MB (emniyet paylı).
- **Ses kanalı**: `ffprobe` ses akışlarını `audio_index` (0 tabanlı) ile
  listeler; çıkarma `-map 0:a:<n>` kullanır. Görüntü/çıktı tarafında tüm ses
  kanalları korunur (`-map 0:a?`), yalnızca transkripsiyon kaynağı seçilir.
- **Kelime damgası kapalı**: faster-whisper `words` döndürmez; segment metni
  süresi karakter ağırlığına göre dağıtılarak sözde kelimelere bölünür.
- **Terim sözlüğü**: NLLB'nin koruduğu `[[G<n>]]` yer tutucuları (ölçüldü:
  `[[0]]` ve `__0__` aynen geçer, `⟦0⟧`/`«0»` bozulur). Eşleşmede `İ/ı/I`
  uzunluk korunarak `i`'ye katlanır, böylece konumlar kaymaz; çözülemeyen
  terimler ikinci geçişte birebir değiştirilir ve logda raporlanır.
- **Gömülü altyazı**: `ffprobe` akışları listeler, `ffmpeg -map 0:<i> -c:s srt`
  çıkarır. Metin codec'leri beyaz listededir; PGS/VobSub/DVB reddedilir.
- **İptal**: `threading.Event`; FFmpeg süreci sonlandırılır, dilim döngüsü
  her adımda kontrol eder, geçici dosyalar silinir.

### Kapsam dışı

- **Konuşmacı ayrımı (diarization).** PyTorch ve hesap gerektiren, yüzlerce MB
  indirilen pyannote ağırlıkları (Hugging Face token'ı) gerekir; bu proje
  bilinçli olarak küçük, CPU-only ve hesapsız bir bağımlılık kümesiyle çalışır.
  Altyazı yalnızca metin + zamanlamadır.

---

## Lisans

Subtra **MIT Lisansı** ile yayımlanır — bkz. [LICENSE](../LICENSE).

İndirilen modeller kendi lisanslarına tabidir:

- faster-whisper / Whisper: MIT
- NLLB-200: CC-BY-NC-4.0 (ticari kullanım için lisansınızı kontrol edin)
- FFmpeg: LGPL/GPL
