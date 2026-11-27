"""Dil kodlari, gorunen adlar ve Whisper -> NLLB eslemesi.

Whisper dil kodlari ISO 639-1 (iki harf), NLLB-200 ise ISO 639-3 + yazi
sistemi kullanir (or. "eng_Latn"). Ceviri icin bu esleme zorunludur.
"""

from __future__ import annotations

WHISPER_TO_NLLB = {
    "af": "afr_Latn",
    "am": "amh_Ethi",
    "ar": "arb_Arab",
    "az": "azj_Latn",
    "be": "bel_Cyrl",
    "bg": "bul_Cyrl",
    "bn": "ben_Beng",
    "bs": "bos_Latn",
    "ca": "cat_Latn",
    "cs": "ces_Latn",
    "cy": "cym_Latn",
    "da": "dan_Latn",
    "de": "deu_Latn",
    "el": "ell_Grek",
    "en": "eng_Latn",
    "es": "spa_Latn",
    "et": "est_Latn",
    "eu": "eus_Latn",
    "fa": "pes_Arab",
    "fi": "fin_Latn",
    "fr": "fra_Latn",
    "gl": "glg_Latn",
    "gu": "guj_Gujr",
    "he": "heb_Hebr",
    "hi": "hin_Deva",
    "hr": "hrv_Latn",
    "hu": "hun_Latn",
    "hy": "hye_Armn",
    "id": "ind_Latn",
    "is": "isl_Latn",
    "it": "ita_Latn",
    "ja": "jpn_Jpan",
    "jv": "jav_Latn",
    "ka": "kat_Geor",
    "kk": "kaz_Cyrl",
    "km": "khm_Khmr",
    "kn": "kan_Knda",
    "ko": "kor_Hang",
    "ku": "kmr_Latn",
    "lo": "lao_Laoo",
    "lt": "lit_Latn",
    "lv": "lvs_Latn",
    "mg": "plt_Latn",
    "mi": "mri_Latn",
    "mk": "mkd_Cyrl",
    "ml": "mal_Mlym",
    "mn": "khk_Cyrl",
    "mr": "mar_Deva",
    "ms": "zsm_Latn",
    "mt": "mlt_Latn",
    "my": "mya_Mymr",
    "nb": "nob_Latn",
    "ne": "npi_Deva",
    "nl": "nld_Latn",
    "nn": "nno_Latn",
    "no": "nob_Latn",
    "oc": "oci_Latn",
    "pa": "pan_Guru",
    "pl": "pol_Latn",
    "ps": "pbt_Arab",
    "pt": "por_Latn",
    "ro": "ron_Latn",
    "ru": "rus_Cyrl",
    "sa": "san_Deva",
    "sd": "snd_Arab",
    "si": "sin_Sinh",
    "sk": "slk_Latn",
    "sl": "slv_Latn",
    "sn": "sna_Latn",
    "so": "som_Latn",
    "sq": "als_Latn",
    "sr": "srp_Cyrl",
    "su": "sun_Latn",
    "sv": "swe_Latn",
    "sw": "swh_Latn",
    "ta": "tam_Taml",
    "te": "tel_Telu",
    "tg": "tgk_Cyrl",
    "th": "tha_Thai",
    "tk": "tuk_Latn",
    "tl": "tgl_Latn",
    "tr": "tur_Latn",
    "tt": "tat_Cyrl",
    "uk": "ukr_Cyrl",
    "ur": "urd_Arab",
    "uz": "uzn_Latn",
    "vi": "vie_Latn",
    "yi": "ydd_Hebr",
    "yo": "yor_Latn",
    "yue": "yue_Hant",
    "zh": "zho_Hans",
    "zu": "zul_Latn",
}

# Arayuzde gosterilecek Turkce dil adlari.
WHISPER_LANGUAGE_NAMES_TR = {
    "af": "Afrikaanca",
    "am": "Amharca",
    "ar": "Arapça",
    "az": "Azerice",
    "be": "Belarusça",
    "bg": "Bulgarca",
    "bn": "Bengalce",
    "bs": "Boşnakça",
    "ca": "Katalanca",
    "cs": "Çekçe",
    "cy": "Galce",
    "da": "Danca",
    "de": "Almanca",
    "el": "Yunanca",
    "en": "İngilizce",
    "es": "İspanyolca",
    "et": "Estonca",
    "eu": "Baskça",
    "fa": "Farsça",
    "fi": "Fince",
    "fr": "Fransızca",
    "gl": "Galiçyaca",
    "gu": "Gucaratça",
    "he": "İbranice",
    "hi": "Hintçe",
    "hr": "Hırvatça",
    "hu": "Macarca",
    "hy": "Ermenice",
    "id": "Endonezce",
    "is": "İzlandaca",
    "it": "İtalyanca",
    "ja": "Japonca",
    "jv": "Javaca",
    "ka": "Gürcüce",
    "kk": "Kazakça",
    "km": "Kmerce",
    "kn": "Kannada",
    "ko": "Korece",
    "ku": "Kürtçe",
    "lo": "Laoca",
    "lt": "Litvanca",
    "lv": "Letonca",
    "mg": "Malgaşça",
    "mi": "Maorice",
    "mk": "Makedonca",
    "ml": "Malayalamca",
    "mn": "Moğolca",
    "mr": "Marathi",
    "ms": "Malayca",
    "mt": "Maltaca",
    "my": "Birmanca",
    "nb": "Norveççe (Bokmål)",
    "ne": "Nepalce",
    "nl": "Felemenkçe",
    "nn": "Norveççe (Nynorsk)",
    "no": "Norveççe",
    "oc": "Oksitanca",
    "pa": "Pencapça",
    "pl": "Lehçe",
    "ps": "Peştuca",
    "pt": "Portekizce",
    "ro": "Romence",
    "ru": "Rusça",
    "sa": "Sanskritçe",
    "sd": "Sindhî",
    "si": "Sinhala",
    "sk": "Slovakça",
    "sl": "Slovence",
    "sn": "Şona",
    "so": "Somalice",
    "sq": "Arnavutça",
    "sr": "Sırpça",
    "su": "Sundaca",
    "sv": "İsveççe",
    "sw": "Svahili",
    "ta": "Tamilce",
    "te": "Telugu",
    "tg": "Tacikçe",
    "th": "Tayca",
    "tk": "Türkmence",
    "tl": "Tagalogca",
    "tr": "Türkçe",
    "tt": "Tatarca",
    "uk": "Ukraynaca",
    "ur": "Urduca",
    "uz": "Özbekçe",
    "vi": "Vietnamca",
    "yi": "Yidce",
    "yo": "Yorubaca",
    "yue": "Kantonca",
    "zh": "Çince",
    "zu": "Zuluca",
    "ht": "Haiti Kreolü",
    "fo": "Faroece",
    "ba": "Başkurtça",
    "ln": "Lingala",
    "as": "Assamca",
    "ha": "Hausaca",
    "br": "Bretonca",
    "la": "Latince",
}

# Hedef dil icin ISO 639-2/B altyazi etiketi (mkv/mp4 ustverisi).
# Listede olmayan diller icin whisper kodu kullanilir.
SUBTITLE_TAGS = {
    "af": "afr", "am": "amh", "ar": "ara", "az": "aze", "be": "bel",
    "bg": "bul", "bn": "ben", "bs": "bos", "ca": "cat", "cs": "cze",
    "cy": "wel", "da": "dan", "de": "ger", "el": "gre", "en": "eng",
    "es": "spa", "et": "est", "eu": "baq", "fa": "per", "fi": "fin",
    "fr": "fre", "gl": "glg", "gu": "guj", "he": "heb", "hi": "hin",
    "hr": "hrv", "hu": "hun", "hy": "arm", "id": "ind", "is": "ice",
    "it": "ita", "ja": "jpn", "jv": "jav", "ka": "geo", "kk": "kaz",
    "km": "khm", "kn": "kan", "ko": "kor", "ku": "kur", "lo": "lao",
    "lt": "lit", "lv": "lav", "mg": "mlg", "mi": "mao", "mk": "mac",
    "ml": "mal", "mn": "mon", "mr": "mar", "ms": "may", "mt": "mlt",
    "my": "bur", "nb": "nob", "ne": "nep", "nl": "dut", "nn": "nno",
    "no": "nor", "oc": "oci", "pa": "pan", "pl": "pol", "ps": "pus",
    "pt": "por", "ro": "rum", "ru": "rus", "sa": "san", "sd": "snd",
    "si": "sin", "sk": "slo", "sl": "slv", "sn": "sna", "so": "som",
    "sq": "alb", "sr": "srp", "su": "sun", "sv": "swe", "sw": "swa",
    "ta": "tam", "te": "tel", "tg": "tgk", "th": "tha", "tk": "tuk",
    "tl": "tgl", "tr": "tur", "tt": "tat", "uk": "ukr", "ur": "urd",
    "uz": "uzb", "vi": "vie", "yi": "yid", "yo": "yor", "yue": "chi",
    "zh": "chi", "zu": "zul", "ht": "hat", "fo": "fao", "ba": "bak",
    "ln": "lin", "as": "asm", "ha": "hau", "br": "bre", "la": "lat",
}


# Arayuzde sunulan hedef diller: dunyada en cok konusulan ~20 dil + Turkce.
# (NLLB-200 200 dili destekler; arayuzu sade tutmak icin bu liste secildi.)
TARGET_CODES = (
    "en",  # Ingilizce
    "zh",  # Cince
    "hi",  # Hintce
    "es",  # Ispanyolca
    "fr",  # Fransizca
    "ar",  # Arapca
    "bn",  # Bengalce
    "pt",  # Portekizce
    "ru",  # Rusca
    "ur",  # Urduca
    "id",  # Endonezce
    "de",  # Almanca
    "ja",  # Japonca
    "mr",  # Marathi
    "te",  # Telugu
    "tr",  # Turkce
    "ta",  # Tamilce
    "vi",  # Vietnamca
    "ko",  # Korece
    "it",  # Italyanca
    "fa",  # Farsca
)


def _target_entry(code: str) -> dict:
    return {
        "nllb": WHISPER_TO_NLLB[code],
        "label": WHISPER_LANGUAGE_NAMES_TR.get(code, code.upper()),
        "subtitle_tag": SUBTITLE_TAGS.get(code, code),
        "suffix": f"_{code}",
    }


# Arayuzden secilebilen hedef diller.
TARGET_LANGUAGES = {code: _target_entry(code) for code in TARGET_CODES}

# Varsayilan hedef dil.
DEFAULT_TARGET = "tr"


def target_options() -> list[tuple[str, str]]:
    """(kod, ad) listesi; ada gore alfabetik."""
    return sorted(
        ((code, info["label"]) for code, info in TARGET_LANGUAGES.items()),
        key=lambda item: item[1],
    )


def target_label(code: str | None) -> str:
    if not code:
        return "Bilinmiyor"
    return TARGET_LANGUAGES.get(code, {}).get("label", code.upper())


def target_suffix(code: str | None) -> str:
    """Dosya adi eki; or. 'en' -> '_en'."""
    if code and code in TARGET_LANGUAGES:
        return TARGET_LANGUAGES[code]["suffix"]
    return f"_{code}" if code else ""


def target_subtitle_tag(code: str | None) -> str:
    if code and code in TARGET_LANGUAGES:
        return TARGET_LANGUAGES[code]["subtitle_tag"]
    return code or "und"


def known_suffixes() -> tuple[str, ...]:
    """Tanimli tum dil ekleri (en uzundan kisa) — dosya adi temizligi icin."""
    return tuple(
        sorted((info["suffix"] for info in TARGET_LANGUAGES.values()), key=len, reverse=True)
    )


def whisper_to_nllb(code: str | None) -> str | None:
    """Whisper dil kodunu NLLB-200 koduna cevirir."""
    if not code:
        return None
    return WHISPER_TO_NLLB.get(code.strip().lower())


def language_label(code: str | None) -> str:
    """Dil kodunun Turkce adini dondurur."""
    if not code:
        return "Bilinmiyor"
    code = code.strip().lower()
    return WHISPER_LANGUAGE_NAMES_TR.get(code, code.upper())


def target_nllb(code: str) -> str:
    """Hedef dilin NLLB kodunu dondurur."""
    return TARGET_LANGUAGES[code]["nllb"]


# ISO 639-2 terminolojik (T) -> bibliyografik (B) eslemeleri. ffprobe
# genelde B kullanir (ger, fre, cze) ama Matroska/ISO 639-2/T de gorulur
# (deu, fra, ces). Ikisini de Whisper koduna cevirebilmek icin gerekli.
_ISO3_T_TO_B = {
    "deu": "ger",
    "fra": "fre",
    "ces": "cze",
    "nld": "dut",
    "ell": "gre",
    "ron": "rum",
    "srp": "srp",
    "hrv": "hrv",
    "slk": "slo",
    "slv": "slv",
    "kat": "geo",
    "eus": "baq",
    "mya": "bur",
    "mkd": "mac",
    "sqi": "alb",
    "hye": "arm",
    "zho": "chi",
    "fas": "per",
    "msa": "may",
    "isl": "ice",
    "bod": "tib",
}


def from_subtitle_tag(code: str | None) -> str:
    """Altyazi etiketini (tur/eng/deu) Whisper dil koduna cevirir.

    Taninmayan/bos etiket icin bos dizge doner; cagiran taraf otomatik
    tahmine duser.
    """
    value = (code or "").strip().lower()
    if not value:
        return ""
    if len(value) == 2:
        return value if value in WHISPER_TO_NLLB else ""
    if len(value) != 3:
        return ""
    value = _ISO3_T_TO_B.get(value, value)
    for whisper_code, tag in SUBTITLE_TAGS.items():
        if tag == value:
            return whisper_code
    return ""
