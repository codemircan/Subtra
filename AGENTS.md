# Subtra — çalışma kuralları

## İş bölümü (zorunlu)

| Rol | Ajan | Model |
|---|---|---|
| Planlama, organizasyon, işi adımlara bölme | `hermes` (alt ajan) | oturum modeli |
| Kod yazma, test, commit | birincil ajan (build) | DeepSeek V4.1 Flash |

**Kural:** Yeni bir özellik, hata düzeltmesi veya çok adımlı her işte önce
`hermes` alt ajanı çağrılır (`subagent`, `agent: "hermes"`). Hermes kodu okur,
planı metin olarak döner. Uygulamayı birincil ajan yapar.

İstisnalar (Hermes'e gerek yok):

- tek satırlık düzeltme veya tek dosyalık açık değişiklik,
- kullanıcının "direkt yap" dediği iş,
- Hermes'in planı bu oturumda zaten alınmışsa (tekrar çağırmayın).

## Değişmez kurallar

- Testler asla model indirmez: `SUBTRA_NO_DOWNLOAD=1`, model yoksa SKIP (exit 77).
- `main` yalnızca etiketli sürüm alır; çalışma `development` dalında.
- Sürüm tek kaynak: `version.py`. Etiket `vX.Y.Z` biçiminde.
- Kaynak dosyalar LF, `.bat`/`.ps1`/`.spec` CRLF (`.gitattributes`).
- Repoya medya, `.srt`, model, anahtar girmez.
- Arayüz metni Türkçe; README İngilizce (`docs/README.tr.md` ikincil).
- Paketleme sonrası doğrulama: `Subtra.exe --self-check` + `test/test_frozen_exe.py`.
