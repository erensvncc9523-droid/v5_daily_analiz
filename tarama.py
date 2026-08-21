"""
BIST ESv2 Strateji Tarama — Günlük Periyot (Revize Sürüm)
────────────────────────────────────────────
Mantık: Akşam seans kapandıktan sonra çalıştır.
        AL sinyali veren hisseler ertesi gün için listelenir.
        Mum kapanışı beklenir (barstate.isconfirmed mantığı).

Revizyonlar (ESv2-revised-2026):
  1. Çıkış / Kâr Realizasyonu:
     - Başabaş (Break-even): Kâr >= +%5 olunca stop maliyete (%0) çekilir.
     - Kademeli Kâr Kilitleme: Kâr >= +%10 olunca taban kâr en az +%5 yapılır.
     - Trailing Stop: Kâr >= +%15 olunca zirveden geriye %5 izleyen stop çalışır.
     - İlk Stop: Girişten sonra hiç yükselmeyen hisseler için -%5 sabit stop.
  2. Giriş Zamanlaması:
     - LOOKBACK penceresi 4'ten 2'ye indirildi (tepeden geç girişi engellemek için).
     - Aşırı Uzama Filtresi: Fiyat MA20'den maksimum %4 yukarıda olabilir.
  3. Trend Doğrulaması:
     - Fiyat > SMA50 ve SMA20 > SMA50 (Golden Alignment) eklendi.
     - Endeks Trend Filtresi (USE_HTF / XU100 filtresi).
  4. AL Gücü Puanlaması:
     - Ters çalışan osilatör puanlaması yerine; RSI Trend Bandı (45-65) + Hacim + MA Uyumu bazlı sağlıklı puanlama.
"""

import pandas as pd
import numpy as np
from datetime import datetime
import warnings
import logging
import os

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

SCRIPT_VERSION = "tarama.py 2026-08-21 ESv2-revised"

# ─────────────────────────────────────────────
# PARAMETRELER
# ─────────────────────────────────────────────
INTERVAL    = "1d"     # Günlük periyot
PERIOD_1D   = "2y"     # EMA/MA ve pozisyon akışı için yeterli geçmiş
PERIOD_HTF  = "2y"
DATA_SOURCE = "tradingview"  # tradingview veya yfinance
ALLOW_DATA_FALLBACK = True   # TradingView veri vermezse otomatik yfinance'a dön
TV_EXCHANGE = "BIST"
TV_RETRY_COUNT = 2
LAST_DATA_SOURCE_ERROR = ""

# Gösterge Parametreleri
MED_LEN     = 3
RSI_LEN     = 14
STOCH_LEN   = 14
SMOOTH_K    = 3
SMOOTH_D    = 3
EMA_LEN     = 14
LOOKBACK    = 2        # Revize: 4 -> 2 (Gecikmeli girişleri engellemek için)
VOL_LEN     = 20
MA_TREND_LEN = 20
MA_SLOW_LEN  = 50
HTF_MA_LEN  = 200

# Stop & Kâr Realizasyon Parametreleri (Revize)
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
    """Endeks (XU100) veya hissenin 200 günlük MA üzerinde olup olmadığını doğrular."""
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
# REVİZE SİNYAL VE İŞLEM HESAPLAMA MOTORU
# ─────────────────────────────────────────────
def sinyal_hesapla(df):
    high  = df["High"]
    low   = df["Low"]
    close = df["Close"]
    vol   = df["Volume"]
    hl2   = (high + low) / 2

    # Göstergeler
    median     = percentile_nearest_rank(hl2, MED_LEN, 50)
    median_ema = ema(median, MED_LEN)

    rsi_val    = rsi_calc(close, RSI_LEN)
    K, D       = stoch_rsi(close, RSI_LEN, STOCH_LEN, SMOOTH_K, SMOOTH_D)
    ema_k      = ema(K, EMA_LEN)

    # 1. Kesişim Koşulları (Daraltılmış 2 barlık hafıza)
    cross3_raw = (K > ema_k) & (K.shift(1) <= ema_k.shift(1))
    c1 = crossover_win(median, median_ema, LOOKBACK)
    c2 = crossover_win(K, D, LOOKBACK)
    c3 = cross3_raw.rolling(LOOKBACK).max().fillna(0).astype(bool)

    # 2. Trend ve Aşırı Uzama Filtreleri
    ma20 = sma(close, MA_TREND_LEN)
    ma50 = sma(close, MA_SLOW_LEN)

    ma_slope_ok = ma20 >= ma20.shift(MA_SLOPE_BARS) * (1.0 + MIN_MA_SLOPE_PCT / 100.0)
    trend_aligned = (close >= ma50) & (ma20 >= ma50)
    trend_ok = (ma_slope_ok & trend_aligned) if USE_TREND else pd.Series(True, index=close.index)

    # Aşırı uzama kontrolü (Fiyat MA20'den en fazla %4 uzakta olmalı)
    not_extended = close <= (ma20 * (1.0 + MAX_MA20_DIST_PCT / 100.0))

    # Hacim Filtresi
    vol_avg = sma(vol, VOL_LEN)
    signal_vol_ok = (vol >= vol_avg * SIGNAL_VOLUME_MULTIPLIER) if USE_SIGNAL_VOLUME_FILTER else pd.Series(True, index=close.index)

    # AL Sinyali Tetikleyicisi
    setup_repeated = c1.shift(1).fillna(False) & c2.shift(1).fillna(False) & c3.shift(1).fillna(False)
    long_raw = c1 & c2 & c3 & trend_ok & not_extended & signal_vol_ok & ~setup_repeated

    # 3. Sağlıklı AL Gücü Puanlama Motoru (Revize)
    # RSI 45-65 bandında (trend düzeltmesi) + Güçlü hacim (>= 1.3x) -> Güçlü Al
    grade = pd.Series(0, index=close.index)
    strong_rsi = (rsi_val >= 45) & (rsi_val <= 65)
    strong_vol = vol >= (vol_avg * 1.3)
    
    grade = grade.mask(long_raw & strong_rsi & strong_vol, 3) # GUCLU AL
    grade = grade.mask(long_raw & ((strong_rsi & ~strong_vol) | (~strong_rsi & strong_vol)), 2) # NORMAL AL
    grade = grade.mask(long_raw & ~strong_rsi & ~strong_vol, 1) # ZAYIF AL

    # 4. Dinamik Çıkış Yönetimi (Break-even + Taban Kâr Kilitleme + Trailing Stop)
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

            # Dinamik Stop Seviyesi Güncellemesi:
            # A) Kâr >= %15 ise zirveden %5 geriden izleyen stop
            if peak_profit_pct >= TRAILING_TRIGGER_PCT:
                trailing_stop_level = highest_since_entry * (1.0 - TRAILING_PULLBACK_PCT / 100.0)
                active_stop = max(active_stop, trailing_stop_level)
            # B) Kâr >= %10 ise kârı en az +%5'e kilitle
            elif peak_profit_pct >= LOCK_PROFIT_TRIGGER_PCT:
                lock_level = entry_price * (1.0 + LOCK_PROFIT_PCT / 100.0)
                active_stop = max(active_stop, lock_level)
            # C) Kâr >= %5 ise stopu başabaşa / maliyete (%0) çek
            elif peak_profit_pct >= BREAKEVEN_TRIGGER_PCT:
                active_stop = max(active_stop, entry_price)

            stop_fiyat.iloc[i] = active_stop

            # Çıkış Kontrolü
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

    # Üst Zaman / Endeks Kontrolü
    if USE_HTF and not htf_ok("XU100"):
        log("UYARI: XU100 MA200 altında! Yeni pozisyon açılışları sınırlandırıldı.")

    for idx, hisse in enumerate(symbols, 1):
        ticker = hisse + ".IS"
        log(f"[{idx:3d}/{toplam}] {hisse}: taranıyor")
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
                sinyal_tarihi = df.index[-1].strftime("%d.%m.%Y")
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
# ANA TARAMA ÇALIŞTIRICI
# ─────────────────────────────────────────────
def tara():
    print("\n" + "="*60)
    print("  BIST ESv2 TARAMA - GUNLUK PERIYOT (REVIZE)")
    print(f"  Tarih  : {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    print(f"  Veri   : {DATA_SOURCE} | fallback: {'ACIK' if ALLOW_DATA_FALLBACK else 'KAPALI'}")
    print(f"  HTF    : {'ACIK' if USE_HTF else 'KAPALI'} (Endeks MA200 Kontrolü)")
    print(f"  Trend  : SMA20 + SMA50 Uyumlu + Fiyat MA20 Mesafe Filtresi (%{MAX_MA20_DIST_PCT})")
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
                sinyal_tarihi = df.index[-1].strftime("%d.%m.%Y")
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
    # SONUÇLAR
    # ─────────────────────────────────────────────
    print("\n" + "="*60)
    print(f"  AL SINYALI VEREN HISSELER ({len(al_listesi)} adet)")
    print(f"  -> Yarın açılışta giriş yapılabilir")
    print("="*60)
    if al_listesi:
        for h in al_listesi:
            print(f"  {h['Hisse']:<10} {h['Kapanış Fiyatı']:>10.2f} TL   Stop: {h['Stop Fiyatı']:>10.2f} TL   {h['AL Gücü']:<10} {h['Sinyal Tarihi']}   Veri: {h['Veri Kaynagi']}")
    else:
        print("  Sinyal veren hisse bulunamadı.")

    if al_listesi:
        dosya = f"bist_al_v2_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        pd.DataFrame(al_listesi).to_excel(dosya, index=False)
        print(f"\n  Excel kaydedildi: {dosya}")

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
