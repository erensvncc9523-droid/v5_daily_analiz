"""
BIST ESv2 Strateji Tarama & Excel Takip — Günlük Periyot
────────────────────────────────────────────────────────
Mantık: Akşam seans kapandıktan sonra çalıştırılır.
        1. Günlük AL sinyali veren yeni hisseleri bulur.
        2. Yüzde.xlsx dosyasını otomatik günceller:
           - Açık pozisyonların fiyat, en yüksek/en düşük, MFE/MAE değerlerini günceller.
           - Yeni revize dinamik stopları (Break-even %5, Taban Kâr %10, Trailing %15) işletir.
           - Kapanan pozisyonları işaretler ve kâr/zararı hesaplar.
           - Yeni AL sinyallerini yeni işlem satırı olarak ekler.
           - ÖZET ve BIST (XU100) sayfalarını senkronize eder.
"""

import pandas as pd
import numpy as np
from datetime import datetime, date
import warnings
import logging
import os
from pathlib import Path

warnings.filterwarnings("ignore")
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

try:
    import yfinance as yf
except ImportError:
    yf = None

try:
    from tvDatafeed import TvDatafeed, Interval
except ImportError:
    TvDatafeed = None
    Interval = None

SCRIPT_VERSION = "tarama.py 2026-08-21 ESv2-revised-tracker"

# ─────────────────────────────────────────────
# PARAMETRELER
# ─────────────────────────────────────────────
INTERVAL    = "1d"
PERIOD_1D   = "2y"
PERIOD_HTF  = "2y"
DATA_SOURCE = "tradingview"  # tradingview veya yfinance
ALLOW_DATA_FALLBACK = True   # Otomatik yfinance fallback
TV_EXCHANGE = "BIST"
TV_RETRY_COUNT = 2
LAST_DATA_SOURCE_ERROR = ""
EXCEL_FILE  = "Yüzde.xlsx"

# Gösterge Parametreleri
MED_LEN     = 3
RSI_LEN     = 14
STOCH_LEN   = 14
SMOOTH_K    = 3
SMOOTH_D    = 3
EMA_LEN     = 14
LOOKBACK    = 2        # Revize: 4 -> 2
VOL_LEN     = 20
MA_TREND_LEN = 20
MA_SLOW_LEN  = 50
HTF_MA_LEN  = 200

# Stop & Kâr Realizasyon Parametreleri
STOP_LOSS_PCT          = 5.0   # İlk koruma stopu (-%5)
BREAKEVEN_TRIGGER_PCT  = 5.0   # Stopu maliyete çekme eşiği (+%5)
LOCK_PROFIT_TRIGGER_PCT= 10.0  # Taban kâr kilitleme eşiği (+%10)
LOCK_PROFIT_PCT        = 5.0   # Kilitlenen taban kâr (+%5)
TRAILING_TRIGGER_PCT   = 15.0  # Trailing stop tetikleme eşiği (+%15)
TRAILING_PULLBACK_PCT  = 5.0   # Zirveden geri çekilme toleransı (%5)

# Filtre Parametreleri
MAX_MA20_DIST_PCT      = 4.0   # Fiyat MA20'den en fazla %4 yukarıda olabilir
MA_SLOPE_BARS          = 5
MIN_MA_SLOPE_PCT       = 0.5
SIGNAL_VOLUME_MULTIPLIER = 1.0
USE_SIGNAL_VOLUME_FILTER = True
USE_TREND              = True  # MA20 & MA50 trend filtresi
USE_HTF                = True  # BIST Endeks / Üst Zaman Trend Filtresi

# ─────────────────────────────────────────────
# BIST HİSSE LİSTESİ
# ─────────────────────────────────────────────
BIST_HISSELER = sorted(list(set([
    "ACSEL","ADEL","AEFES","AFYON","AGESA","AGHOL","AKBNK","AKCNS","AKFYE",
    "AKGRT","AKMGY","AKSA","AKSEN","AKSGY","ALARK","ALBRK","ALFAS","ALKIM",
    "ALMAD","ALVARK","ANELE","ARCLK","ARDYZ","ARENA","ARSAN","ASELS","ASTOR",
    "ATEKS","AYGAZ","BAGFS","BAKAB","BANVT","BERA","BFREN","BIMAS","BJKAS",
    "BOSSA","BRISA","BRMEN","BRSAN","BTCIM","BUCIM","BURCE","BURVA","CCOLA",
    "CELHA","CEMAS","CEMTS","CIMSA","CLEBI","CONAS","CWENE","DEVA","DITAS",
    "DMSAS","DOAS","DOBUR","DOHOL","DOKTA","DYOBY","ECILC","ECZYT","EGEEN",
    "EGEPO","EGGUB","EGPRO","EKGYO","EREGL","FROTO","GARAN","GENIL","GENTS",
    "GEREL","GESAN","GOLTS","GOODY","GOZDE","GUBRF","HALKB","HATEK","HEKTS",
    "HUBVC","HURGZ","ICBCT","INDES","INFO","INVEO","ISDMR","ISFIN","ISGYO",
    "ISKUR","JANTS","KAREL","KARSN","KARTN","KCHOL","KLKIM","KLMSN","KLSYN",
    "KONYA","KORDS","KOZAA","KOZAL","KRDMA","KRDMB","KRDMD","LOGO","MAALT",
    "MAGEN","MAKIM","MARKA","MAVKG","MEDTR","MEPET","MERCN","MERIT","MERKO",
    "METRO","MIGROS","MNDRS","MOBTL","MPARK","MRSHL","NATEN","NETAS","NTGAZ",
    "NTHOL","NTTUR","NUHCM","ODAS","ORGE","ORMA","OTKAR","OYAKC","PETKM",
    "PETUN","PGSUS","PKART","POLHO","PRKAB","PRKME","QNBFB","RYSAS","SAHOL",
    "SANEL","SANKO","SARKY","SASA","SISE","SKBNK","SKTAS","SOKM","TCELL",
    "THYAO","TKFEN","TOASO","TTKOM","TTRAK","TUPRS","TURGG","VAKBN","VAKKO",
    "VESBE","VESTL","YKBNK","YONGA","ZOREN","AKENR","AKFGY","ANHYT","ARAT",
    "ATATP","AVGYO","AYCES","AYEN","BASGZ","BAYRK","BIENY","BINBN","BIOEN",
    "BIZIM","BLCYT","BNTAS","BRYAT","BVSAN","CANTE","CEOEM","CLKHO","CRFSA",
    "CUSAN","CVKMD","DAGHL","DAGI","DAPGM","DARDL","DENGE","DERHL","DESA",
    "DESPC","DGATE","DGGYO","DGNMO","DNISI","DURDO","DZGYO","EDATA","EDIP",
    "EMKEL","EMNIS","ENPRO","ENRUY","ERSU","ESCAR","ESCOM","ESEN","ETILR",
    "EUREN","EUYO","EVCIL","FADE","FENER","FLAP","FONET","FORMT","FORTE",
    "FZLGY","GARFA","GEDIK","GEDZA","GLBMD","GLCVY","GLYHO","GMTAS","GOKNR",
    "GRNYO","GRSEL","GRTRK","GSDDE","GSDHO","GSRAY","GWIND","GZNMI","HDFGS",
    "HEDEF","HKTM","HLGYO","HPGYO","HRKET","HTTBT","HUNER","IDGYO","IEYHO",
    "IHLGM","IHEVA","IHGZT","IHLAS","IMASM","INTEM","IPEKE","ISGSY","ISKPL",
    "ISMO","ISYAT","ITTFH","IZFAS","IZINV","IZMDC","KAPLM","KATMR","KAYSE",
    "KBORU","KCAER","KENT","KERVN","KERVT","KFEIN","KGYO","KIMMR","KLGYO",
    "KLNMA","KLRHO","KLSER","KMPUR","KNFRT","KOCMT","KOPOL","KRONT","KRPLS",
    "KRSTL","KRTEK","KRVGD","KTLEV","KTSKR","KUTPO","KUVVA","KUYAS","LIDER",
    "LIDFA","LILAK","LKMNH","LMKDC","LRSHO","LUKSK","MACKO","MANAS","MARTI",
    "MEGAP","METUR","MIATK","MMCAS","MNDTR","MOGAN","MRGYO","MSGYO","MTRKS",
    "MZHLD","NIBAS","NUGYO","OBAMS","OBASE","ODINE","OFKGT","ONCSM","ORCAY",
    "OSMEN","OSTIM","OYAYO","OYLUM","OZGYO","OZKGY","OZRDN","OZSUB","PAGYO",
    "PAMEL","PAPIL","PARSN","PASEU","PCILT","PEGYO","PEKMT","PENGD","PENTA",
    "PINSU","PKENT","PLTUR","PNLSN","POLTK","PRDGS","PRZMA","PSDTC","PSGYO",
    "QNBFL","RALYH","RAYSG","RHEAG","RNPOL","RODRG","ROYAL","RTALB","RUBNS",
    "SAYAS","SDTTR","SEGYO","SEKFK","SEKUR","SELEC","SELGD","SELVA","SEYKM",
    "SILVR","SMART","SMRTG","SNGYO","SNICA","SNKRN","SONME","SRVGY","SUMAS",
    "SUNTK","SUWEN","TABGD","TARKM","TATEN","TATGD","TAVHL","TBORG","TDGYO",
    "TEKTU","TERA","TETMT","TGSAS","TKNSA","TLMAN","TMSN","TNZTP","TRCAS",
    "TRGYO","TRILC","TSGYO","TSPOR","TUCLK","TUKAS","ULUUN","ULUSE","UMPAS",
    "UNLU","USAK","VAKFN","VANGD","VBTYZ","VERUS","VKFYO","VKGYO","VKING",
    "YATAS","YAYLA","YBTAS","YEOTK","YGGYO","YKSLN","YOYGD","YPKYO","YUNSA",
    "ZEDUR","ZRGYO"
])))

# ─────────────────────────────────────────────
# GÖSTERGE VE MATEMATİK FONKSİYONLARI
# ─────────────────────────────────────────────
def percentile_nearest_rank(series, length, pct):
    result = series.copy() * np.nan
    arr    = series.values
    for i in range(length - 1, len(arr)):
        w = arr[i - length + 1:i + 1]
        w = w[~np.isnan(w)]
        if len(w) == 0:
            continue
        idx = int(np.ceil(pct / 100.0 * len(w))) - 1
        result.iloc[i] = np.sort(w)[max(0, min(idx, len(w)-1))]
    return result

def ema(series, length):
    return series.ewm(span=length, adjust=False).mean()

def sma(series, length):
    return series.rolling(window=length).mean()

def rma(series, length):
    values = series.astype(float)
    result = pd.Series(np.nan, index=series.index, dtype=float)
    seed = values.rolling(window=length, min_periods=length).mean()

    for i in range(len(values)):
        value = values.iloc[i]
        if np.isnan(value):
            continue
        previous_is_empty = i == 0 or np.isnan(result.iloc[i - 1])
        if previous_is_empty:
            if not np.isnan(seed.iloc[i]):
                result.iloc[i] = seed.iloc[i]
        else:
            result.iloc[i] = (result.iloc[i - 1] * (length - 1) + value) / length

    return result

def rsi_calc(close, length):
    delta    = close.diff()
    gain     = delta.clip(lower=0)
    loss     = (-delta).clip(lower=0)
    avg_gain = rma(gain, length)
    avg_loss = rma(loss, length)
    rs       = avg_gain / (avg_loss + 1e-10)
    return 100 - (100 / (1 + rs))

def stoch_rsi(close, rsi_len, stoch_len, smooth_k, smooth_d):
    rsi_val   = rsi_calc(close, rsi_len)
    rsi_min   = rsi_val.rolling(stoch_len).min()
    rsi_max   = rsi_val.rolling(stoch_len).max()
    stoch_raw = (rsi_val - rsi_min) / (rsi_max - rsi_min + 1e-10) * 100
    K         = sma(stoch_raw, smooth_k)
    D         = sma(K, smooth_d)
    return K, D

def crossover_win(a, b, n):
    cross = (a > b) & (a.shift(1) <= b.shift(1))
    return cross.rolling(n).max().fillna(0).astype(bool)

def buy_grade_text(grade):
    if grade == 3:
        return "GUCLU AL"
    if grade == 2:
        return "NORMAL AL"
    if grade == 1:
        return "ZAYIF AL"
    return "AL"

# ─────────────────────────────────────────────
# VERİ ÇEKME MODÜLLERİ
# ─────────────────────────────────────────────
TV_CLIENT = None

def normalize_ohlcv(df):
    if df is None or len(df) == 0:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    rename_map = {col: str(col).title() for col in df.columns}
    df = df.rename(columns=rename_map)
    required = ["Open", "High", "Low", "Close", "Volume"]
    if not all(col in df.columns for col in required):
        return None
    return df[required].dropna(subset=["High", "Low", "Close"])

def period_to_bars(period):
    if period.endswith("y"):
        return int(period[:-1]) * 260
    if period.endswith("mo"):
        return int(period[:-2]) * 22
    if period.endswith("d"):
        return int(period[:-1])
    return 600

def tv_interval(interval):
    if Interval is None:
        return None
    if interval == "1d":
        return Interval.in_daily
    return None

def tradingview_symbol(ticker):
    return ticker.replace(".IS", "")

def get_tv_client():
    global TV_CLIENT
    if TvDatafeed is None:
        return None
    if TV_CLIENT is None:
        username = os.getenv("TV_USERNAME")
        password = os.getenv("TV_PASSWORD")
        if username and password:
            TV_CLIENT = TvDatafeed(username=username, password=password)
        else:
            TV_CLIENT = TvDatafeed()
    return TV_CLIENT

def veri_cek_yfinance(ticker, period, interval):
    if yf is None:
        return None
    df = yf.download(ticker, period=period, interval=interval,
                     progress=False, auto_adjust=True)
    return normalize_ohlcv(df)

def veri_cek_tradingview(ticker, period, interval):
    tv_int = tv_interval(interval)
    if TvDatafeed is None or tv_int is None:
        return None
    last_error = None
    for _ in range(TV_RETRY_COUNT):
        try:
            client = get_tv_client()
            if client is None:
                return None
            df = client.get_hist(
                symbol=tradingview_symbol(ticker),
                exchange=TV_EXCHANGE,
                interval=tv_int,
                n_bars=period_to_bars(period)
            )
            normalized = normalize_ohlcv(df)
            if normalized is not None and len(normalized) > 0:
                return normalized
            last_error = "veri yok"
        except Exception as e:
            global TV_CLIENT
            TV_CLIENT = None
            last_error = str(e)
    raise RuntimeError(last_error or "TradingView veri alinamadi")

def veri_cek_kaynakli(ticker, period, interval):
    global LAST_DATA_SOURCE_ERROR
    LAST_DATA_SOURCE_ERROR = ""
    sources = [DATA_SOURCE]
    fallback = "yfinance" if DATA_SOURCE == "tradingview" else "tradingview"
    if ALLOW_DATA_FALLBACK and fallback not in sources:
        sources.append(fallback)

    for source in sources:
        try:
            if source == "tradingview":
                df = veri_cek_tradingview(ticker, period, interval)
            elif source == "yfinance":
                df = veri_cek_yfinance(ticker, period, interval)
            else:
                df = None
            if df is not None and len(df) > 0:
                return df, source
            LAST_DATA_SOURCE_ERROR = f"{source}: veri yok"
        except Exception as e:
            LAST_DATA_SOURCE_ERROR = f"{source}: hata - {e}"
            continue
    return None, ""

def son_veri_kaynagi_hatasi():
    return LAST_DATA_SOURCE_ERROR

def veri_cek(ticker, period, interval):
    df, _ = veri_cek_kaynakli(ticker, period, interval)
    return df

def htf_ok(ticker="XU100"):
    try:
        df = veri_cek(ticker, PERIOD_HTF, "1d")
        if df is None or len(df) < HTF_MA_LEN + 5:
            return True
        close = df["Close"]
        ma200 = sma(close, HTF_MA_LEN)
        return bool(float(close.iloc[-1]) > float(ma200.iloc[-1]))
    except:
        return True

# ─────────────────────────────────────────────
# SİNYAL VE İŞLEM HESAPLAMA MOTORU
# ─────────────────────────────────────────────
def sinyal_hesapla(df):
    high  = df["High"]
    low   = df["Low"]
    close = df["Close"]
    vol   = df["Volume"]
    hl2   = (high + low) / 2

    median     = percentile_nearest_rank(hl2, MED_LEN, 50)
    median_ema = ema(median, MED_LEN)

    rsi_val    = rsi_calc(close, RSI_LEN)
    K, D       = stoch_rsi(close, RSI_LEN, STOCH_LEN, SMOOTH_K, SMOOTH_D)
    ema_k      = ema(K, EMA_LEN)

    cross3_raw = (K > ema_k) & (K.shift(1) <= ema_k.shift(1))
    c1 = crossover_win(median, median_ema, LOOKBACK)
    c2 = crossover_win(K, D, LOOKBACK)
    c3 = cross3_raw.rolling(LOOKBACK).max().fillna(0).astype(bool)

    ma20 = sma(close, MA_TREND_LEN)
    ma50 = sma(close, MA_SLOW_LEN)

    ma_slope_ok = ma20 >= ma20.shift(MA_SLOPE_BARS) * (1.0 + MIN_MA_SLOPE_PCT / 100.0)
    trend_aligned = (close >= ma50) & (ma20 >= ma50)
    trend_ok = (ma_slope_ok & trend_aligned) if USE_TREND else pd.Series(True, index=close.index)

    not_extended = close <= (ma20 * (1.0 + MAX_MA20_DIST_PCT / 100.0))
    vol_avg = sma(vol, VOL_LEN)
    signal_vol_ok = (vol >= vol_avg * SIGNAL_VOLUME_MULTIPLIER) if USE_SIGNAL_VOLUME_FILTER else pd.Series(True, index=close.index)

    setup_repeated = c1.shift(1).fillna(False) & c2.shift(1).fillna(False) & c3.shift(1).fillna(False)
    long_raw = c1 & c2 & c3 & trend_ok & not_extended & signal_vol_ok & ~setup_repeated

    grade = pd.Series(0, index=close.index)
    strong_rsi = (rsi_val >= 45) & (rsi_val <= 65)
    strong_vol = vol >= (vol_avg * 1.3)
    
    grade = grade.mask(long_raw & strong_rsi & strong_vol, 3)
    grade = grade.mask(long_raw & ((strong_rsi & ~strong_vol) | (~strong_rsi & strong_vol)), 2)
    grade = grade.mask(long_raw & ~strong_rsi & ~strong_vol, 1)

    al_sinyal  = pd.Series(False, index=close.index)
    sat_sinyal = pd.Series(False, index=close.index)
    grade_sinyal = pd.Series(0, index=close.index)
    stop_fiyat = pd.Series(np.nan, index=close.index)
    sat_neden = pd.Series("", index=close.index)

    pozisyon_acik = False
    entry_price = np.nan
    active_stop = np.nan
    highest_since_entry = np.nan

    for i in range(len(close)):
        fiyat = float(close.iloc[i])
        low_i = float(low.iloc[i])
        high_i = float(high.iloc[i])

        if not pozisyon_acik and bool(long_raw.iloc[i]):
            al_sinyal.iloc[i] = True
            grade_sinyal.iloc[i] = int(grade.iloc[i])
            entry_price = fiyat
            active_stop = entry_price * (1.0 - STOP_LOSS_PCT / 100.0)
            stop_fiyat.iloc[i] = active_stop
            highest_since_entry = high_i
            pozisyon_acik = True
            continue

        if pozisyon_acik:
            highest_since_entry = max(highest_since_entry, high_i)
            peak_profit_pct = (highest_since_entry / entry_price - 1.0) * 100.0 if entry_price > 0 else 0.0

            if peak_profit_pct >= TRAILING_TRIGGER_PCT:
                trailing_stop_level = highest_since_entry * (1.0 - TRAILING_PULLBACK_PCT / 100.0)
                active_stop = max(active_stop, trailing_stop_level)
            elif peak_profit_pct >= LOCK_PROFIT_TRIGGER_PCT:
                lock_level = entry_price * (1.0 + LOCK_PROFIT_PCT / 100.0)
                active_stop = max(active_stop, lock_level)
            elif peak_profit_pct >= BREAKEVEN_TRIGGER_PCT:
                active_stop = max(active_stop, entry_price)

            stop_fiyat.iloc[i] = active_stop

            stop_hit = low_i <= active_stop
            if stop_hit:
                sat_sinyal.iloc[i] = True
                if active_stop > entry_price:
                    sat_neden.iloc[i] = "IZLEYEN KAR STOP"
                elif np.isclose(active_stop, entry_price):
                    sat_neden.iloc[i] = "BASABAS (BE) CIKIS"
                else:
                    sat_neden.iloc[i] = "STOP ZARAR"

                pozisyon_acik = False
                entry_price = np.nan
                active_stop = np.nan
                highest_since_entry = np.nan

    return al_sinyal, sat_sinyal, close, grade_sinyal, stop_fiyat, sat_neden


def gunluk_al_tara(symbols=None, log_func=None):
    symbols = BIST_HISSELER if symbols is None else symbols
    al_listesi = []
    hata_listesi = []
    toplam = len(symbols)

    def log(message):
        if log_func is not None:
            log_func(message)

    if USE_HTF and not htf_ok("XU100"):
        log("UYARI: XU100 MA200 altinda! Yeni pozisyon acilislari sinirlandirildi.")

    for idx, hisse in enumerate(symbols, 1):
        ticker = hisse + ".IS"
        log(f"[{idx:3d}/{toplam}] {hisse}: taraniyor")
        try:
            df, veri_kaynagi = veri_cek_kaynakli(ticker, PERIOD_1D, INTERVAL)
            if df is None or len(df) < max(60, MA_SLOW_LEN + 10, VOL_LEN + 5):
                hata = son_veri_kaynagi_hatasi()
                kaynak_text = veri_kaynagi if veri_kaynagi else "yok"
                log(f"{hisse}: veri yok | veri: {kaynak_text}" + (f" | {hata}" if hata else ""))
                hata_listesi.append(hisse)
                continue

            al, sat, close, grade, stop_fiyat, sat_neden = sinyal_hesapla(df)

            if len(al) < 3:
                log(f"{hisse}: yetersiz veri")
                continue

            son_al = bool(al.iloc[-1])
            son_sat = bool(sat.iloc[-1])

            if son_al:
                sinyal_tarihi = df.index[-1].strftime("%Y-%m-%d")
                sinyal_fiyat = round(float(close.iloc[-1]), 2)
                stop_seviye = round(float(stop_fiyat.iloc[-1]), 2)
                al_gucu = buy_grade_text(int(grade.iloc[-1]))

                al_listesi.append({
                    "Hisse": hisse,
                    "Kapanış Fiyatı": sinyal_fiyat,
                    "Stop Fiyatı": stop_seviye,
                    "AL Gücü": al_gucu,
                    "Sinyal Tarihi": sinyal_tarihi,
                    "Veri Kaynagi": veri_kaynagi,
                    "Not": "Ertesi gün açılışta giriş"
                })
                log(f"{hisse}: {al_gucu} sinyali bulundu @ {sinyal_fiyat} stop {stop_seviye} | veri: {veri_kaynagi}")
            elif son_sat:
                neden = sat_neden.iloc[-1] if sat_neden.iloc[-1] else "SAT"
                log(f"{hisse}: {neden} | veri: {veri_kaynagi}")
            else:
                log(f"{hisse}: sinyal yok | veri: {veri_kaynagi}")

        except Exception as e:
            log(f"{hisse}: hata - {e}")
            hata_listesi.append(hisse)

    return al_listesi, hata_listesi

# ─────────────────────────────────────────────
# EXCEL RAPORLAMA VE TAKİP MOTORU (Yüzde.xlsx)
# ─────────────────────────────────────────────
def excel_takip_guncelle(al_listesi):
    excel_path = Path(EXCEL_FILE)
    print("\n" + "="*60)
    print("  EXCEL TAKİP TABLOSU GÜNCELLENİYOR (Yüzde.xlsx)")
    print("="*60)

    col_names = [
        'İşlem ID', 'Hisse', 'Sektör', 'AL Tarihi', 'AL Gücü', 'Giriş Fiyatı',
        'Stop Fiyatı', 'Durum', 'Çıkış Tarihi', 'Çıkış Fiyatı', 'Çıkış Nedeni',
        'Güncel Fiyat', 'Gerçekleşen Getiri (%)', 'Güncel Getiri (%)',
        'Pozisyonda Gün', 'En Yüksek Fiyat', 'En Düşük Fiyat', 'MFE (%)',
        'MAE (%)', 'BIST Giriş', 'BIST Çıkış', 'BIST Getiri (%)', 'Alpha (%)',
        'Stop Sonrası Güncel (%)', 'Not'
    ]

    df_veriler = pd.DataFrame(columns=col_names)
    df_bist = pd.DataFrame(columns=['Tarih', 'Açılış', 'Kapanış', 'Günlük Değişim'])

    if excel_path.exists():
        try:
            xls = pd.ExcelFile(excel_path)
            if 'VERİLER' in xls.sheet_names:
                df_veriler = pd.read_excel(excel_path, sheet_name='VERİLER')
            elif len(xls.sheet_names) > 0:
                df_veriler = pd.read_excel(excel_path, sheet_name=0)
                if not all(c in df_veriler.columns for c in ['Hisse', 'Durum']):
                    df_veriler = pd.DataFrame(columns=col_names)

            if 'BIST' in xls.sheet_names:
                df_bist = pd.read_excel(excel_path, sheet_name='BIST')
        except Exception as e:
            print(f"  ! Excel okuma uyarısı: {e}, yeni şablon oluşturuluyor.")

    xu100_close_today = np.nan
    try:
        df_xu, _ = veri_cek_kaynakli("XU100", "1mo", "1d")
        if df_xu is not None and len(df_xu) > 0:
            xu100_close_today = float(df_xu["Close"].iloc[-1])
            tarih_today = df_xu.index[-1].strftime("%Y-%m-%d")
            if 'Tarih' in df_bist.columns and len(df_bist) > 0:
                df_bist['Tarih_str'] = pd.to_datetime(df_bist['Tarih']).dt.strftime("%Y-%m-%d")
                if tarih_today not in df_bist['Tarih_str'].values:
                    new_bist_row = pd.DataFrame([{
                        'Tarih': df_xu.index[-1],
                        'Açılış': float(df_xu["Open"].iloc[-1]),
                        'Kapanış': xu100_close_today,
                        'Günlük Değişim': round(float(df_xu["Close"].iloc[-1] / df_xu["Close"].iloc[-2] - 1.0), 4) if len(df_xu) > 1 else 0.0
                    }])
                    df_bist = pd.concat([df_bist, new_bist_row], ignore_index=True)
                df_bist = df_bist.drop(columns=['Tarih_str'], errors='ignore')
    except Exception as e:
        print(f"  ! XU100 veri hatası: {e}")

    yeni_kapanan_sayisi = 0
    guncellenen_satir = 0

    for idx, row in df_veriler.iterrows():
        guncellenen_satir += 1
        hisse = str(row['Hisse']).strip().upper()
        durum = str(row.get('Durum', '')).strip().upper()

        if durum == 'AÇIK':
            ticker = hisse + ".IS"
            df_h, _ = veri_cek_kaynakli(ticker, "6mo", "1d")
            if df_h is None or len(df_h) == 0:
                continue

            last_close = float(df_h['Close'].iloc[-1])
            last_low = float(df_h['Low'].iloc[-1])
            last_high = float(df_h['High'].iloc[-1])
            last_date = df_h.index[-1]

            giris_fiyati = float(row['Giriş Fiyatı']) if not pd.isna(row['Giriş Fiyatı']) else last_close
            prev_high = float(row['En Yüksek Fiyat']) if not pd.isna(row['En Yüksek Fiyat']) else giris_fiyati
            prev_low = float(row['En Düşük Fiyat']) if not pd.isna(row['En Düşük Fiyat']) else giris_fiyati

            new_high = max(prev_high, last_high)
            new_low = min(prev_low, last_low)
            mfe_pct = ((new_high / giris_fiyati) - 1.0) * 100.0
            mae_pct = ((new_low / giris_fiyati) - 1.0) * 100.0
            guncel_getiri_pct = ((last_close / giris_fiyati) - 1.0) * 100.0

            initial_stop = giris_fiyati * (1.0 - STOP_LOSS_PCT / 100.0)
            active_stop = initial_stop

            if mfe_pct >= TRAILING_TRIGGER_PCT:
                active_stop = max(active_stop, new_high * (1.0 - TRAILING_PULLBACK_PCT / 100.0))
            elif mfe_pct >= LOCK_PROFIT_TRIGGER_PCT:
                active_stop = max(active_stop, giris_fiyati * (1.0 + LOCK_PROFIT_PCT / 100.0))
            elif mfe_pct >= BREAKEVEN_TRIGGER_PCT:
                active_stop = max(active_stop, giris_fiyati)

            df_veriler.at[idx, 'Güncel Fiyat'] = round(last_close, 2)
            df_veriler.at[idx, 'En Yüksek Fiyat'] = round(new_high, 2)
            df_veriler.at[idx, 'En Düşük Fiyat'] = round(new_low, 2)
            df_veriler.at[idx, 'MFE (%)'] = round(mfe_pct, 2)
            df_veriler.at[idx, 'MAE (%)'] = round(mae_pct, 2)
            df_veriler.at[idx, 'Güncel Getiri (%)'] = round(guncel_getiri_pct, 2)
            df_veriler.at[idx, 'Stop Fiyatı'] = round(active_stop, 2)

            try:
                al_tarihi = pd.to_datetime(row['AL Tarihi'])
                df_veriler.at[idx, 'Pozisyonda Gün'] = max(1, (pd.to_datetime(last_date) - al_tarihi).days)
            except:
                pass

            if last_low <= active_stop:
                cikis_fiyati = active_stop
                getiri = ((cikis_fiyati / giris_fiyati) - 1.0) * 100.0
                cikis_nedeni = "IZLEYEN KAR STOP" if active_stop > giris_fiyati else "BASABAS (BE)" if np.isclose(active_stop, giris_fiyati) else "STOP"
                
                df_veriler.at[idx, 'Durum'] = 'KAR STOP' if active_stop > giris_fiyati else 'STOP'
                df_veriler.at[idx, 'Çıkış Tarihi'] = last_date
                df_veriler.at[idx, 'Çıkış Fiyatı'] = round(cikis_fiyati, 2)
                df_veriler.at[idx, 'Çıkış Nedeni'] = cikis_nedeni
                df_veriler.at[idx, 'Gerçekleşen Getiri (%)'] = round(getiri, 2)
                df_veriler.at[idx, 'Güncel Getiri (%)'] = np.nan
                yeni_kapanan_sayisi += 1
                print(f"  -> Pozisyon Kapandı: {hisse} ({cikis_nedeni}) @ {cikis_fiyati:.2f} TL (Getiri: %{getiri:.2f})")

    yeni_al_sayisi = 0
    acik_hisseler = set(df_veriler[df_veriler['Durum'] == 'AÇIK']['Hisse'].astype(str).str.strip().str.upper()) if len(df_veriler) > 0 else set()

    for item in al_listesi:
        hisse_kod = str(item['Hisse']).strip().upper()
        if hisse_kod in acik_hisseler:
            print(f"  - {hisse_kod}: Zaten açık pozisyon mevcut, tekrar eklenmedi.")
            continue

        yeni_id = f"ISLEM-{len(df_veriler) + 1:06d}"
        sinyal_fiyat = float(item['Kapanış Fiyatı'])
        stop_fiyat = float(item['Stop Fiyatı'])
        sinyal_tarihi = pd.to_datetime(item['Sinyal Tarihi'])

        new_row = {
            'İşlem ID': yeni_id,
            'Hisse': hisse_kod,
            'Sektör': np.nan,
            'AL Tarihi': sinyal_tarihi,
            'AL Gücü': item['AL Gücü'],
            'Giriş Fiyatı': sinyal_fiyat,
            'Stop Fiyatı': stop_fiyat,
            'Durum': 'AÇIK',
            'Çıkış Tarihi': pd.NaT,
            'Çıkış Fiyatı': np.nan,
            'Çıkış Nedeni': np.nan,
            'Güncel Fiyat': sinyal_fiyat,
            'Gerçekleşen Getiri (%)': np.nan,
            'Güncel Getiri (%)': 0.0,
            'Pozisyonda Gün': 0,
            'En Yüksek Fiyat': sinyal_fiyat,
            'En Düşük Fiyat': sinyal_fiyat,
            'MFE (%)': 0.0,
            'MAE (%)': 0.0,
            'BIST Giriş': xu100_close_today if not np.isnan(xu100_close_today) else np.nan,
            'BIST Çıkış': np.nan,
            'BIST Getiri (%)': 0.0,
            'Alpha (%)': 0.0,
            'Stop Sonrası Güncel (%)': np.nan,
            'Not': 'Ertesi gün açılışta giriş'
        }

        df_veriler = pd.concat([df_veriler, pd.DataFrame([new_row])], ignore_index=True)
        yeni_al_sayisi += 1
        print(f"  + Yeni İşlem Eklendi: {hisse_kod} @ {sinyal_fiyat} TL (Stop: {stop_fiyat} TL)")

    toplam_islem = len(df_veriler)
    acik_islem = (df_veriler['Durum'] == 'AÇIK').sum() if toplam_islem > 0 else 0
    stop_islem = (df_veriler['Durum'] == 'STOP').sum() if toplam_islem > 0 else 0
    kar_stop_islem = (df_veriler['Durum'] == 'KAR STOP').sum() if toplam_islem > 0 else 0

    df_ozet = pd.DataFrame([
        {'Alan': 'Son Güncelleme', 'Değer': datetime.now().strftime("%d.%m.%Y %H:%M:%S")},
        {'Alan': 'Veri Kaynağı', 'Değer': DATA_SOURCE},
        {'Alan': 'Fallback', 'Değer': 'AÇIK' if ALLOW_DATA_FALLBACK else 'KAPALI'},
        {'Alan': 'Yeni AL', 'Değer': yeni_al_sayisi},
        {'Alan': 'Güncellenen Satır', 'Değer': guncellenen_satir},
        {'Alan': 'Yeni Kapanan İşlem', 'Değer': yeni_kapanan_sayisi},
        {'Alan': 'Toplam İşlem', 'Değer': toplam_islem},
        {'Alan': 'Açık İşlem', 'Değer': acik_islem},
        {'Alan': 'STOP İşlem', 'Değer': stop_islem},
        {'Alan': 'KAR STOP İşlem', 'Değer': kar_stop_islem},
        {'Alan': 'Script Versiyon', 'Değer': SCRIPT_VERSION}
    ])

    try:
        with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
            df_ozet.to_excel(writer, sheet_name='ÖZET', index=False)
            df_veriler.to_excel(writer, sheet_name='VERİLER', index=False)
            df_bist.to_excel(writer, sheet_name='BIST', index=False)
        print(f"\n  ✓ {EXCEL_FILE} başarıyla kaydedildi.")
        print(f"  -> Toplam: {toplam_islem} | Açık: {acik_islem} | Yeni AL: {yeni_al_sayisi} | Kapanan: {yeni_kapanan_sayisi}")
    except Exception as e:
        print(f"  X Excel kaydetme hatası: {e}")

# ─────────────────────────────────────────────
# ANA TARAMA ÇALIŞTIRICI
# ─────────────────────────────────────────────
def tara():
    print("\n" + "="*60)
    print("  BIST ESv2 TARAMA & EXCEL TAKİP - GÜNLÜK PERİYOT")
    print(f"  Tarih  : {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    print(f"  Veri   : {DATA_SOURCE} | fallback: {'ACIK' if ALLOW_DATA_FALLBACK else 'KAPALI'}")
    print(f"  HTF    : {'ACIK' if USE_HTF else 'KAPALI'} (Endeks MA200 Kontrolü)")
    print(f"  Stop   : Başabaş (%{BREAKEVEN_TRIGGER_PCT}) | Taban Kâr (%{LOCK_PROFIT_TRIGGER_PCT}) | Trailing (%{TRAILING_TRIGGER_PCT})")
    print(f"  Hisse  : {len(BIST_HISSELER)} adet")
    print("="*60)

    al_listesi   = []
    hata_listesi = []
    toplam       = len(BIST_HISSELER)

    for idx, hisse in enumerate(BIST_HISSELER, 1):
        ticker = hisse + ".IS"
        print(f"  [{idx:3d}/{toplam}] {hisse:<10}", end=" ", flush=True)
        try:
            df, veri_kaynagi = veri_cek_kaynakli(ticker, PERIOD_1D, INTERVAL)
            if df is None or len(df) < max(60, MA_SLOW_LEN + 10, VOL_LEN + 5):
                hata = son_veri_kaynagi_hatasi()
                kaynak_text = veri_kaynagi if veri_kaynagi else "yok"
                print(f"! Veri yok | Veri: {kaynak_text}" + (f" | {hata}" if hata else ""))
                hata_listesi.append(hisse)
                continue

            al, sat, close, grade, stop_fiyat, sat_neden = sinyal_hesapla(df)

            if len(al) < 3:
                print("- Yetersiz veri")
                continue

            son_al = bool(al.iloc[-1])
            son_sat = bool(sat.iloc[-1])

            if son_al:
                sinyal_tarihi = df.index[-1].strftime("%Y-%m-%d")
                sinyal_fiyat  = round(float(close.iloc[-1]), 2)
                stop_seviye    = round(float(stop_fiyat.iloc[-1]), 2)
                al_gucu        = buy_grade_text(int(grade.iloc[-1]))

                al_listesi.append({
                    "Hisse"          : hisse,
                    "Kapanış Fiyatı" : sinyal_fiyat,
                    "Stop Fiyatı"    : stop_seviye,
                    "AL Gücü"        : al_gucu,
                    "Sinyal Tarihi"  : sinyal_tarihi,
                    "Veri Kaynagi"   : veri_kaynagi,
                    "Not"            : "Ertesi gün açılışta giriş"
                })
                print(f"OK {al_gucu} - {sinyal_fiyat} TL | Stop {stop_seviye} TL  ({sinyal_tarihi}) | Veri: {veri_kaynagi}")
            elif son_sat:
                neden = sat_neden.iloc[-1] if sat_neden.iloc[-1] else "SAT"
                print(f"-- {neden} | Veri: {veri_kaynagi}")
            else:
                print(f"- Sinyal yok | Veri: {veri_kaynagi}")

        except Exception as e:
            print(f"X Hata: {e}")
            hata_listesi.append(hisse)

    # ─────────────────────────────────────────────
    # SONUÇLAR VE EXCEL GÜNCELLEME
    # ─────────────────────────────────────────────
    print("\n" + "="*60)
    print(f"  AL SINYALI VEREN HISSELER ({len(al_listesi)} adet)")
    print("="*60)
    if al_listesi:
        for h in al_listesi:
            print(f"  {h['Hisse']:<10} {h['Kapanış Fiyatı']:>10.2f} TL   Stop: {h['Stop Fiyatı']:>10.2f} TL   {h['AL Gücü']:<10} {h['Sinyal Tarihi']}   Veri: {h['Veri Kaynagi']}")
    else:
        print("  Sinyal veren hisse bulunamadı.")

    # Yüzde.xlsx dosyasını otomatik güncelle
    excel_takip_guncelle(al_listesi)

    if hata_listesi:
        print(f"\n  Veri alınamayan: {len(hata_listesi)} hisse")

    print("="*60 + "\n")
    try:
        input("  Çıkmak için Enter'a basın...")
    except EOFError:
        pass

if __name__ == "__main__":
    print("Günlük tarama başlatılıyor...", flush=True)
    tara()
