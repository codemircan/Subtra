# Hermes — planlama ajanı

Bu proje iki role ayrılmıştır:

| Rol | Ajan | Ne yapar |
|---|---|---|
| Planlama | **Hermes** (`hermes`) | Kodu okur, işi adımlara böler, planı metin olarak verir |
| Uygulama | birincil ajan | Kodu yazar, test eder, commit eder |

## Kurulum

**1. Ajan tanımı:** `~/.config/opencode/agents/hermes.md`

- `mode: all` — hem doğrudan (Tab ile seçilip) hem alt ajan olarak çağrılabilir.
- `model` belirtilmedi — oturumun modelini kullanır (tek model var:
  `evren/deepseek-v4.1-flash`).
- Yetkiler: `edit` ❌, `shell` ❌, `subagent` ❌, `read`/`glob`/`grep`/`skill` ✅
  → **okuyabilir, değiştiremez.**

**2. Kural dosyası:** `AGENTS.md` (proje kökü) — her oturumda modele enjekte
edilir; "önce Hermes planlasın" kuralını taşır.

## Kullanım

Otomatik (kural gereği yeni işte):

> "Kuyruğa klasör sürükle-bırak ekle"
> → birincil ajan önce `hermes`'i çağırır → plan gelir → kod yazılır.

Elle:

- **Tab** tuşuyla ajan listesinden `hermes` seç, planı doğrudan al.
- Alt ajan olarak: birincil ajana "Hermes'e planlat" de.

## Doğrulama (bu kurulumda ölçüldü)

Hermes'e `test/run_all.py`'yi okutup "kaç test model gerektiriyor" soruldu:

- Hermes: **30 giriş, 20 her zaman / 10 model** → dosya değiştirmedi, yalnız okudu ✅
- Gerçek (`ast` ile sayım): **31 giriş, 20 her zaman / 11 model**

Yani rol ve sınırlar doğru çalışıyor, ancak **sayısal iddiaları doğrulanmalı**.
Planı uygulamadan önce kritik sayıları bir komutla teyit et.

## Not

`hermes` alt ajanı bu oturum açıldığında zaten tanımlıydı. Yukarıdaki dosya o
tanımın yerine geçti ve rol/sınırları korudu.
