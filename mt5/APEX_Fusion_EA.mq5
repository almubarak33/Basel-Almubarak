//+------------------------------------------------------------------+
//|                                              APEX_Fusion_EA.mq5  |
//|  APEX Fusion (gold, H1) as a MetaTrader 5 Expert Advisor.        |
//|                                                                  |
//|  Port of the tested configuration (research/final_config.py,     |
//|  bot test research/bot_gold_check.py):                           |
//|   - 7 trend setups: break & retest, opening range (09:30 NY),    |
//|     Donchian 20 breakout, EMA 9/21 pullback, SuperTrend pullback,|
//|     SuperTrend flip, VWAP reclaim                                |
//|   - gates: Daily trend + 4H trend agree, APEX score >= 5,        |
//|     signal candle opens 08:00-17:00 New York                     |
//|   - stop: 10-bar swing - 0.25 ATR, clamped to 0.8-3.5 ATR        |
//|   - market entry right after the signal candle closes            |
//|   - High Win-Rate: 50% off at 0.5R + stop to entry, 25% off at   |
//|     2R + stop to TP1, rest at 5R (Balanced: 1R / 3R / 5R)        |
//|  Python test of this logic (gold H1, entry at next open, 0.01%   |
//|  cost): PAXG 2021-26 72% win +0.13R, COMEX 2024-26 70% +0.17R,   |
//|  XAUUSDT 2026 69% +0.19R per trade. Not yet run in MT5: test it  |
//|  in the Strategy Tester and on a demo account first.             |
//+------------------------------------------------------------------+
#property copyright "APEX Fusion"
#property version   "1.00"
#property description "APEX Fusion gold H1 Expert Advisor. Test in the Strategy Tester and on a demo account before live use."

#include <Trade/Trade.mqh>

enum ENUM_APEX_PROFILE
  {
   APEX_HIGHWIN  = 0,   // High Win-Rate (0.5R / 2R / 5R)
   APEX_BALANCED = 1    // Balanced (1R / 3R / 5R)
  };

enum ENUM_APEX_SRVTIME
  {
   SRV_NY_PLUS_7 = 0,   // NY+7: server midnight = 17:00 New York (most MT5 brokers)
   SRV_GMT_FIXED = 1    // Fixed GMT offset (set below; e.g. 0 for GMT servers)
  };

input group "Strategy (defaults = the tested gold H1 setup)"
input ENUM_APEX_PROFILE InpProfile = APEX_HIGHWIN; // Trade-management profile
input int    InpMinScore     = 5;     // Minimum APEX confluence score (0-7)
input bool   InpUseAnchor    = true;  // Daily trend must agree
input bool   InpUseHtf       = true;  // 4H trend must agree
input bool   InpUseSession   = true;  // Only signals from candles opening 08:00-17:00 New York
input bool   InpReverse      = true;  // An opposite signal closes and reverses the trade
input bool   InpAllowLongs   = true;  // Allow buys
input bool   InpAllowShorts  = true;  // Allow sells
input bool   InpSetupBRT     = true;  // Setup: break & retest
input bool   InpSetupORB     = true;  // Setup: opening-range break (09:30 New York)
input bool   InpSetupBRK     = true;  // Setup: Donchian 20 breakout
input bool   InpSetupEMA     = true;  // Setup: EMA 9/21 pullback
input bool   InpSetupPB      = true;  // Setup: SuperTrend pullback resume
input bool   InpSetupFLIP    = true;  // Setup: SuperTrend flip
input bool   InpSetupVWAP    = true;  // Setup: VWAP reclaim

input group "Risk"
input double InpRiskPct           = 1.0;   // Equity % lost if the stop is hit
input double InpMaxDailyLossPct   = 3.0;   // Halt for the day at this loss vs the day's starting equity
input bool   InpCloseOnDailyLimit = true;  // Also close the open trade when the daily limit is hit
input double InpMaxSpread         = 0.60;  // Max spread in price units (0.60 = 60 cents on gold)
input int    InpEntryWindowMin    = 15;    // Minutes after the candle opens to wait for a normal spread
input double InpMaxMarginFrac     = 0.5;   // Max share of free margin one trade may use
input ulong  InpMagic             = 20261108; // Magic number
input int    InpDeviationPoints   = 50;    // Max slippage for market orders (points)

input group "Broker server time (sessions are New York time)"
input ENUM_APEX_SRVTIME InpServerTime = SRV_NY_PLUS_7; // How the broker's server clock relates to New York
input int    InpGmtOffset = 0;   // Only for "Fixed GMT offset": server time = GMT + this many hours

input group "Display"
input bool   InpDrawSignals  = true;   // Draw signal arrows on the chart
input bool   InpShowPanel    = true;   // Status panel (chart comment)
input bool   InpAllowOtherTF = false;  // Only H1 was tested; allow another timeframe anyway

//--- strategy constants (same as the tested Python / Pine defaults)
#define NA EMPTY_VALUE
const int    LOOKBACK   = 1500;   // H1 candles used to rebuild every indicator and state machine
const int    HTF_BARS   = 600;
const int    D1_BARS    = 300;
const double ADX_MIN    = 25.0;
const int    DON_LEN    = 20;
const double ST_FACTOR  = 3.0;
const int    ST_LEN     = 10;
const int    PV_LEN     = 5;
const int    VWAP_AWAY  = 6;
const int    EMA_WINDOW = 3;
const double BRT_TOL    = 0.3;
const int    BRT_WINDOW = 20;
const int    ORB_MINUTES = 15;
const int    ORB_START  = 570;    // 09:30 New York, minutes after midnight
const int    ORB_END    = 960;    // 16:00 New York
const int    SWING_LOOK = 10;
const double SL_BUF     = 0.25;
const double SL_MIN_ATR = 0.8;
const double SL_MAX_ATR = 3.5;
const int    MAX_ARROWS = 60;
const int    H4_ANCHOR_SEC = 18 * 3600;   // 4H blocks start 18:00 New York (18, 22, 02, 06, 10, 14), as tested
const int    H4_SEC     = 4 * 3600;

CTrade   g_trade;
datetime g_lastBar = 0;

//--- forward declarations
void DrawArrow(const datetime t, const double price, const int d, const string setup);
bool CloseOurPosition(const string why);
double   g_k1, g_k2, g_k3, g_w1, g_w2;

struct PendingEntry
  {
   bool     active;
   int      dir;          // +1 buy, -1 sell
   double   stop;         // structural stop price from the signal candle
   datetime expires;      // give up if the spread stays too wide until then
   string   setup;
   int      score;
  };
PendingEntry g_pend;

struct LastSignal
  {
   datetime time;
   int      dir;
   string   setup;
   int      score;
   int      htf;
   int      anchor;
   int      scoreL;
   int      scoreS;
   bool     inSession;
  };
LastSignal g_last;

//+------------------------------------------------------------------+
//| Small helpers                                                    |
//+------------------------------------------------------------------+
bool IsNA(const double x) { return x == NA; }

string Prefix() { return "APEX_" + IntegerToString((long)InpMagic) + "_"; }

int VolumeDigits()
  {
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   int d = 0;
   while(step < 1.0 - 1e-9 && d < 8) { step *= 10.0; d++; }
   return d;
  }

double RoundToTick(const double price)
  {
   double tick = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tick <= 0.0) return NormalizeDouble(price, _Digits);
   return NormalizeDouble(MathRound(price / tick) * tick, _Digits);
  }

double NormalizeVolume(const double v)
  {
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double mn   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double mx   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   if(step <= 0.0) return 0.0;
   double x = MathFloor(v / step + 1e-9) * step;
   if(x < mn) return 0.0;
   if(x > mx) x = mx;
   return NormalizeDouble(x, VolumeDigits());
  }

//--- New York time from broker server time (US daylight saving handled for fixed-GMT servers)
datetime NthSunday(const int year, const int month, const int nth)
  {
   MqlDateTime d;
   ZeroMemory(d);
   d.year = year; d.mon = month; d.day = 1;
   datetime first = StructToTime(d);
   MqlDateTime f;
   TimeToStruct(first, f);
   int firstSunday = 1 + (7 - f.day_of_week) % 7;
   d.day = firstSunday + 7 * (nth - 1);
   return StructToTime(d);
  }

bool IsUsDst(const datetime gmt)
  {
   MqlDateTime d;
   TimeToStruct(gmt, d);
   datetime start = NthSunday(d.year, 3, 2) + 7 * 3600;    // 02:00 EST
   datetime end   = NthSunday(d.year, 11, 1) + 6 * 3600;   // 02:00 EDT
   return gmt >= start && gmt < end;
  }

datetime ToNewYork(const datetime server)
  {
   if(InpServerTime == SRV_NY_PLUS_7) return server - 7 * 3600;
   datetime gmt = server - InpGmtOffset * 3600;
   return gmt - (IsUsDst(gmt) ? 4 : 5) * 3600;
  }

int NyMinutes(const datetime server)
  {
   MqlDateTime d;
   TimeToStruct(ToNewYork(server), d);
   return d.hour * 60 + d.min;
  }

int NyDayId(const datetime server)   // trading day starting 17:00 New York
  {
   MqlDateTime d;
   TimeToStruct(ToNewYork(server) - 17 * 3600, d);
   return d.year * 10000 + d.mon * 100 + d.day;
  }

//+------------------------------------------------------------------+
//| Indicator maths on chronological arrays (index 0 = oldest).      |
//| Same definitions as TradingView ta.* (SMA-seeded EMA/RMA).       |
//+------------------------------------------------------------------+
void Seeded(const double &src[], const int n, const int len, const double alpha, double &out[])
  {
   ArrayResize(out, n);
   double prev = NA, sum = 0.0;
   int cnt = 0;
   for(int i = 0; i < n; i++)
     {
      out[i] = NA;
      double v = src[i];
      if(IsNA(prev))
        {
         if(IsNA(v)) { sum = 0.0; cnt = 0; continue; }
         sum += v; cnt++;
         if(cnt > len) { sum -= src[i - len]; cnt = len; }
         if(cnt == len) { prev = sum / len; out[i] = prev; }
        }
      else
        {
         if(!IsNA(v)) prev = alpha * v + (1.0 - alpha) * prev;
         out[i] = prev;
        }
     }
  }

void Ema(const double &src[], const int n, const int len, double &out[]) { Seeded(src, n, len, 2.0 / (len + 1), out); }
void Rma(const double &src[], const int n, const int len, double &out[]) { Seeded(src, n, len, 1.0 / len, out); }

void TrueRange(const MqlRates &r[], const int n, const bool handleNa, double &tr[])
  {
   ArrayResize(tr, n);
   for(int i = 0; i < n; i++)
     {
      if(i == 0) { tr[0] = handleNa ? r[0].high - r[0].low : NA; continue; }
      double pc = r[i - 1].close;
      tr[i] = MathMax(r[i].high - r[i].low, MathMax(MathAbs(r[i].high - pc), MathAbs(r[i].low - pc)));
     }
  }

void Atr(const MqlRates &r[], const int n, const int len, double &out[])
  {
   double tr[];
   TrueRange(r, n, true, tr);
   Rma(tr, n, len, out);
  }

void Rsi(const double &c[], const int n, const int len, double &out[])
  {
   double up[], dn[], ru[], rd[];
   ArrayResize(up, n); ArrayResize(dn, n); ArrayResize(out, n);
   up[0] = NA; dn[0] = NA;
   for(int i = 1; i < n; i++)
     {
      double ch = c[i] - c[i - 1];
      up[i] = MathMax(ch, 0.0);
      dn[i] = MathMax(-ch, 0.0);
     }
   Rma(up, n, len, ru);
   Rma(dn, n, len, rd);
   for(int i = 0; i < n; i++)
     {
      if(IsNA(ru[i]) || IsNA(rd[i])) { out[i] = NA; continue; }
      out[i] = rd[i] == 0.0 ? 100.0 : (ru[i] == 0.0 ? 0.0 : 100.0 - 100.0 / (1.0 + ru[i] / rd[i]));
     }
  }

void Dmi(const MqlRates &r[], const int n, double &plus[], double &minus[], double &adx[])
  {
   double pdm[], mdm[], tr[], trur[], rp[], rm[], dx[];
   ArrayResize(pdm, n); ArrayResize(mdm, n); ArrayResize(plus, n); ArrayResize(minus, n); ArrayResize(dx, n);
   pdm[0] = NA; mdm[0] = NA;
   for(int i = 1; i < n; i++)
     {
      double up = r[i].high - r[i - 1].high;
      double down = r[i - 1].low - r[i].low;
      pdm[i] = (up > down && up > 0) ? up : 0.0;
      mdm[i] = (down > up && down > 0) ? down : 0.0;
     }
   TrueRange(r, n, false, tr);
   Rma(tr, n, 14, trur);
   Rma(pdm, n, 14, rp);
   Rma(mdm, n, 14, rm);
   double lastP = NA, lastM = NA;
   for(int i = 0; i < n; i++)
     {
      if(!IsNA(trur[i]) && trur[i] > 0 && !IsNA(rp[i]) && !IsNA(rm[i]))
        {
         lastP = 100.0 * rp[i] / trur[i];
         lastM = 100.0 * rm[i] / trur[i];
        }
      plus[i] = lastP;     // fixnan: keep the last valid value
      minus[i] = lastM;
      if(IsNA(lastP) || IsNA(lastM)) { dx[i] = NA; continue; }
      double s = lastP + lastM;
      dx[i] = MathAbs(lastP - lastM) / (s == 0.0 ? 1.0 : s);
     }
   Rma(dx, n, 14, adx);
   for(int i = 0; i < n; i++)
      if(!IsNA(adx[i])) adx[i] *= 100.0;
  }

void SuperTrend(const MqlRates &r[], const int n, const double factor, const int len, double &dir[])
  {
   double a[];
   Atr(r, n, len, a);
   ArrayResize(dir, n);
   double pub = NA, plb = NA, prevSt = NA;
   for(int i = 0; i < n; i++)
     {
      double src = (r[i].high + r[i].low) / 2.0;
      double ub = IsNA(a[i]) ? NA : src + factor * a[i];
      double lb = IsNA(a[i]) ? NA : src - factor * a[i];
      double ppl = IsNA(plb) ? 0.0 : plb;
      double ppu = IsNA(pub) ? 0.0 : pub;
      bool hasPc = i > 0;
      double pc = hasPc ? r[i - 1].close : 0.0;
      if(!IsNA(lb)) lb = (lb > ppl || (hasPc && pc < ppl)) ? lb : ppl;
      if(!IsNA(ub)) ub = (ub < ppu || (hasPc && pc > ppu)) ? ub : ppu;
      int di;
      if(i == 0 || IsNA(a[i - 1])) di = 1;
      else if(prevSt == ppu)       di = r[i].close > ub ? -1 : 1;
      else                         di = r[i].close < lb ? 1 : -1;
      double s = di == -1 ? lb : ub;
      dir[i] = di;
      prevSt = s; pub = ub; plb = lb;
     }
  }

double Highest(const double &x[], const int end, const int len)   // max of x[end-len+1 .. end]
  {
   if(end - len + 1 < 0) return NA;
   double m = x[end];
   for(int k = end - len + 1; k < end; k++) if(x[k] > m) m = x[k];
   return m;
  }

double Lowest(const double &x[], const int end, const int len)
  {
   if(end - len + 1 < 0) return NA;
   double m = x[end];
   for(int k = end - len + 1; k < end; k++) if(x[k] < m) m = x[k];
   return m;
  }

double PivotHigh(const MqlRates &r[], const int i, const int left, const int right)
  {
   if(i < left + right) return NA;
   int p = i - right;
   double v = r[p].high;
   for(int k = p - left; k < p; k++) if(r[k].high >= v) return NA;
   for(int k = p + 1; k <= i; k++) if(r[k].high > v) return NA;
   return v;
  }

double PivotLow(const MqlRates &r[], const int i, const int left, const int right)
  {
   if(i < left + right) return NA;
   int p = i - right;
   double v = r[p].low;
   for(int k = p - left; k < p; k++) if(r[k].low <= v) return NA;
   for(int k = p + 1; k <= i; k++) if(r[k].low < v) return NA;
   return v;
  }

//--- higher-timeframe trend: +1 close > EMA and SuperTrend up, -1 both down, 0 otherwise
void HtfTrendSeries(const MqlRates &h[], const int n, const int emaLen, int &tr[])
  {
   double c[], e[], d[];
   ArrayResize(c, n); ArrayResize(tr, n);
   for(int i = 0; i < n; i++) c[i] = h[i].close;
   Ema(c, n, emaLen, e);
   SuperTrend(h, n, 3.0, 10, d);
   for(int i = 0; i < n; i++)
     {
      if(IsNA(e[i])) { tr[i] = 0; continue; }
      tr[i] = (c[i] > e[i] && d[i] < 0) ? 1 : ((c[i] < e[i] && d[i] > 0) ? -1 : 0);
     }
  }

//--- value of the HTF bar that completed before the HTF bar containing time t (no repainting)
int HtfValueAt(const datetime t, const MqlRates &h[], const int &tr[], const int n, const int periodSec)
  {
   int lo = 0, hi = n - 1, k = -1;
   while(lo <= hi)
     {
      int mid = (lo + hi) / 2;
      if(h[mid].time <= t) { k = mid; lo = mid + 1; }
      else hi = mid - 1;
     }
   if(k < 0) return 0;
   if(t >= h[k].time + periodSec) return tr[k];   // t is in a later (still forming) HTF bar
   return k >= 1 ? tr[k - 1] : 0;
  }

//--- 4H trend built from the chart's candles in New York 4-hour blocks starting 18:00, as in the tested
//--- version. Independent of the broker's server time. Returns the trend of the block that completed
//--- before the block of the last candle (no repainting).
int H4TrendFromChart(const MqlRates &r[], const int n)
  {
   MqlRates agg[];
   ArrayResize(agg, n);
   long key = -1;
   int m = -1;
   for(int k = 0; k < n; k++)
     {
      long kk = ((long)ToNewYork(r[k].time) - H4_ANCHOR_SEC) / H4_SEC;
      if(m < 0 || kk != key)
        {
         m++;
         key = kk;
         agg[m] = r[k];
        }
      else
        {
         agg[m].high = MathMax(agg[m].high, r[k].high);
         agg[m].low = MathMin(agg[m].low, r[k].low);
         agg[m].close = r[k].close;
        }
     }
   if(m < 1) return 0;
   int tr[];
   HtfTrendSeries(agg, m + 1, 50, tr);
   return tr[m - 1];
  }

//+------------------------------------------------------------------+
//| Signal on the last closed candle                                 |
//+------------------------------------------------------------------+
bool ComputeSignal(int &dirOut, double &stopOut, string &setupOut, int &scoreOut, bool &retryOut)
  {
   dirOut = 0;
   retryOut = false;
   MqlRates r[], h4[], d1[];
   ArraySetAsSeries(r, false); ArraySetAsSeries(h4, false); ArraySetAsSeries(d1, false);
   int n = CopyRates(_Symbol, _Period, 1, LOOKBACK, r);          // closed candles only
   bool buildH4 = PeriodSeconds(_Period) < H4_SEC;              // H1 (and lower): build 4H from the chart
   int nh = buildH4 ? 0 : CopyRates(_Symbol, PERIOD_H4, 1, HTF_BARS, h4);
   int nd = CopyRates(_Symbol, PERIOD_D1, 1, D1_BARS, d1);
   if(n < 400 || (!buildH4 && nh < 100) || nd < 60)
     {
      static datetime lastWarn = 0;
      if(TimeCurrent() - lastWarn >= 60)
        {
         PrintFormat("APEX: not enough history yet (H1 %d, H4 %d, D1 %d) — retrying", n, nh, nd);
         lastWarn = TimeCurrent();
        }
      retryOut = true;
      return false;
     }
   int i = n - 1;

   double o[], hh[], ll[], c[], v[];
   ArrayResize(o, n); ArrayResize(hh, n); ArrayResize(ll, n); ArrayResize(c, n); ArrayResize(v, n);
   for(int k = 0; k < n; k++)
     {
      o[k] = r[k].open; hh[k] = r[k].high; ll[k] = r[k].low; c[k] = r[k].close; v[k] = (double)r[k].tick_volume;
     }

   double atr[], e9[], e21[], e50[], e55[], e200[], st[], diP[], diM[], adx[], rsi[];
   Atr(r, n, 14, atr);
   Ema(c, n, 9, e9); Ema(c, n, 21, e21); Ema(c, n, 50, e50); Ema(c, n, 55, e55); Ema(c, n, 200, e200);
   SuperTrend(r, n, ST_FACTOR, ST_LEN, st);
   Dmi(r, n, diP, diM, adx);
   Rsi(c, n, 14, rsi);
   if(IsNA(atr[i]) || atr[i] <= 0 || IsNA(e200[i]) || IsNA(adx[i]) || IsNA(rsi[i]) || IsNA(adx[i - 3])) return false;

   //--- higher timeframes (previous completed bar)
   int trH4[], trD1[];
   int htf = 0;
   if(buildH4) htf = H4TrendFromChart(r, n);
   else
     {
      HtfTrendSeries(h4, nh, 50, trH4);
      htf = HtfValueAt(r[i].time, h4, trH4, nh, PeriodSeconds(PERIOD_H4));
     }
   HtfTrendSeries(d1, nd, 21, trD1);
   int anchor = HtfValueAt(r[i].time, d1, trD1, nd, PeriodSeconds(PERIOD_D1));

   //--- APEX confluence score
   int sc[2];
   for(int s = 0; s < 2; s++)
     {
      int d = s == 0 ? 1 : -1;
      int x = 0;
      x += htf == d ? 1 : 0;
      x += (c[i] - e200[i]) * d > 0 ? 1 : 0;
      x += (e21[i] - e55[i]) * d > 0 ? 1 : 0;
      x += adx[i] > ADX_MIN ? 1 : 0;
      x += (adx[i] > adx[i - 3] && adx[i] > 18) ? 1 : 0;
      x += (diP[i] - diM[i]) * d > 0 ? 1 : 0;
      x += (rsi[i] - 50) * d > 0 ? 1 : 0;
      sc[s] = x;
     }

   //--- volume filter (tick volume vs its 20-candle average)
   double volMa = 0.0;
   for(int k = i - 19; k <= i; k++) volMa += v[k];
   volMa /= 20.0;
   bool volOk = volMa <= 0 || v[i] >= volMa;

   //--- APEX: Donchian breakout
   double donHi = Highest(hh, i - 1, DON_LEN), donHiP = Highest(hh, i - 2, DON_LEN);
   double donLo = Lowest(ll, i - 1, DON_LEN),  donLoP = Lowest(ll, i - 2, DON_LEN);
   bool brkL = c[i] > donHi && c[i - 1] <= donHiP;
   bool brkS = c[i] < donLo && c[i - 1] >= donLoP;
   //--- APEX: SuperTrend flip
   bool flipL = st[i] < 0 && st[i - 1] > 0;
   bool flipS = st[i] > 0 && st[i - 1] < 0;
   //--- APEX: trend pullback resume
   bool touchUp = false, touchDn = false;
   for(int k = i - 4; k <= i; k++)
     {
      if(ll[k] - e21[k] <= 0) touchUp = true;
      if(hh[k] - e21[k] >= 0) touchDn = true;
     }
   bool pbL = st[i] < 0 && touchUp && c[i] > hh[i - 1] && c[i] > e21[i] && c[i] > o[i];
   bool pbS = st[i] > 0 && touchDn && c[i] < ll[i - 1] && c[i] < e21[i] && c[i] < o[i];
   //--- GBB: EMA pullback
   bool trendUp = e21[i] > e50[i] && e50[i] > e50[i - 3];
   bool trendDn = e21[i] < e50[i] && e50[i] < e50[i - 3];
   bool touchedUp = false, touchedDn = false;
   for(int k = i - EMA_WINDOW; k <= i; k++)
     {
      if(ll[k] <= e21[k]) touchedUp = true;
      if(hh[k] >= e21[k]) touchedDn = true;
     }
   bool emaL = trendUp && touchedUp && c[i] > e9[i] && c[i] > o[i] && c[i] > hh[i - 1] && volOk;
   bool emaS = trendDn && touchedDn && c[i] < e9[i] && c[i] < o[i] && c[i] < ll[i - 1] && volOk;

   //--- state machines replayed over the window: VWAP runs, break & retest, opening range
   double cpv = 0.0, cv = 0.0, vwPrev = NA, vwNow = NA;
   int dayPrev = -1, below = 0, above = 0, belowPrev = 0, abovePrev = 0;
   double hiLvl = NA, loLvl = NA, hiPend = NA, loPend = NA;
   bool hiBrk = false, loBrk = false;
   int hiBar = -1, loBar = -1;
   bool brtL = false, brtS = false;
   double orH = NA, orL = NA;
   bool orDone = false, orFired = false, inPrev = false;
   datetime orStart = 0;
   bool orbL = false, orbS = false;
   for(int k = 0; k <= i; k++)
     {
      //--- session VWAP (hlc3 x tick volume), day starts 17:00 New York
      int day = NyDayId(r[k].time);
      if(day != dayPrev) { cpv = 0.0; cv = 0.0; dayPrev = day; }
      cpv += (hh[k] + ll[k] + c[k]) / 3.0 * v[k];
      cv += v[k];
      vwPrev = vwNow;
      vwNow = cv > 0 ? cpv / cv : NA;
      belowPrev = below; abovePrev = above;
      if(!IsNA(vwNow))
        {
         below = c[k] < vwNow ? below + 1 : 0;
         above = c[k] > vwNow ? above + 1 : 0;
        }
      //--- break & retest of confirmed pivots
      double ph = PivotHigh(r, k, PV_LEN, PV_LEN), pl = PivotLow(r, k, PV_LEN, PV_LEN);
      bool hiBusy = hiBrk && hiBar >= 0 && k - hiBar <= BRT_WINDOW;
      bool loBusy = loBrk && loBar >= 0 && k - loBar <= BRT_WINDOW;
      if(!IsNA(ph)) { if(hiBusy) hiPend = ph; else { hiLvl = ph; hiBrk = false; hiPend = NA; } }
      if(!IsNA(pl)) { if(loBusy) loPend = pl; else { loLvl = pl; loBrk = false; loPend = NA; } }
      if(!IsNA(hiLvl) && !hiBrk && c[k] > hiLvl) { hiBrk = true; hiBar = k; }
      if(!IsNA(loLvl) && !loBrk && c[k] < loLvl) { loBrk = true; loBar = k; }
      bool liveL = hiBrk && hiBar >= 0 && k - hiBar <= BRT_WINDOW && k > hiBar;
      bool liveS = loBrk && loBar >= 0 && k - loBar <= BRT_WINDOW && k > loBar;
      bool okAtr = !IsNA(atr[k]) && atr[k] > 0;
      bool sL = liveL && okAtr && ll[k] <= hiLvl + atr[k] * BRT_TOL && c[k] > hiLvl && c[k] > o[k];
      bool sS = liveS && okAtr && hh[k] >= loLvl - atr[k] * BRT_TOL && c[k] < loLvl && c[k] < o[k];
      if(sL) hiBrk = false;
      if(sS) loBrk = false;
      if(!(hiBrk && hiBar >= 0 && k - hiBar <= BRT_WINDOW) && !IsNA(hiPend)) { hiLvl = hiPend; hiBrk = false; hiPend = NA; }
      if(!(loBrk && loBar >= 0 && k - loBar <= BRT_WINDOW) && !IsNA(loPend)) { loLvl = loPend; loBrk = false; loPend = NA; }
      if(k == i) { brtL = sL; brtS = sS; }
      //--- opening range (first 15 minutes from 09:30 New York), one break per session
      int nyMin = NyMinutes(r[k].time);
      bool inS = nyMin >= ORB_START && nyMin < ORB_END;
      bool oL = false, oS = false;
      if(inS && !inPrev) { orH = hh[k]; orL = ll[k]; orDone = false; orFired = false; orStart = r[k].time; }
      else if(inS && !orDone)
        {
         if(orStart > 0 && r[k].time - orStart >= ORB_MINUTES * 60) orDone = true;
         else { orH = IsNA(orH) ? hh[k] : MathMax(orH, hh[k]); orL = IsNA(orL) ? ll[k] : MathMin(orL, ll[k]); }
        }
      oL = inS && orDone && !orFired && !IsNA(orH) && c[k] > orH;
      oS = inS && orDone && !orFired && !IsNA(orL) && c[k] < orL;
      if(oL || oS) orFired = true;
      inPrev = inS;
      if(k == i) { orbL = oL; orbS = oS; }
     }
   bool vwapL = !IsNA(vwNow) && !IsNA(vwPrev) && c[i] > vwNow && c[i - 1] <= vwPrev && belowPrev >= VWAP_AWAY && volOk;
   bool vwapS = !IsNA(vwNow) && !IsNA(vwPrev) && c[i] < vwNow && c[i - 1] >= vwPrev && abovePrev >= VWAP_AWAY && volOk;

   //--- gates
   int nyMinI = NyMinutes(r[i].time);
   bool inSession = !InpUseSession || (nyMinI >= 8 * 60 && nyMinI < 17 * 60);
   bool gateL = inSession && (!InpUseAnchor || anchor == 1) && sc[0] >= InpMinScore && (!InpUseHtf || htf == 1);
   bool gateS = inSession && (!InpUseAnchor || anchor == -1) && sc[1] >= InpMinScore && (!InpUseHtf || htf == -1);

   string setL = (InpSetupBRT && brtL) ? "B&R" : (InpSetupORB && orbL) ? "ORB" : (InpSetupBRK && brkL) ? "BRK" :
                 (InpSetupEMA && emaL) ? "EMA" : (InpSetupPB && pbL) ? "PB" : (InpSetupFLIP && flipL) ? "FLIP" :
                 (InpSetupVWAP && vwapL) ? "VWAP" : "";
   string setS = (InpSetupBRT && brtS) ? "B&R" : (InpSetupORB && orbS) ? "ORB" : (InpSetupBRK && brkS) ? "BRK" :
                 (InpSetupEMA && emaS) ? "EMA" : (InpSetupPB && pbS) ? "PB" : (InpSetupFLIP && flipS) ? "FLIP" :
                 (InpSetupVWAP && vwapS) ? "VWAP" : "";
   bool goL = setL != "" && gateL && InpAllowLongs;
   bool goS = setS != "" && gateS && InpAllowShorts && !goL;

   g_last.time = r[i].time; g_last.htf = htf; g_last.anchor = anchor;
   g_last.scoreL = sc[0]; g_last.scoreS = sc[1]; g_last.inSession = inSession;
   if(!goL && !goS) return true;

   int d = goL ? 1 : -1;
   double swing = d == 1 ? Lowest(ll, i, SWING_LOOK) - SL_BUF * atr[i] : Highest(hh, i, SWING_LOOK) + SL_BUF * atr[i];
   double dist = MathMin(MathMax((c[i] - swing) * d, SL_MIN_ATR * atr[i]), SL_MAX_ATR * atr[i]);
   dirOut = d;
   stopOut = c[i] - d * dist;
   setupOut = goL ? setL : setS;
   scoreOut = goL ? sc[0] : sc[1];
   g_last.dir = d; g_last.setup = setupOut; g_last.score = scoreOut;
   if(InpDrawSignals) DrawArrow(r[i].time, d == 1 ? r[i].low : r[i].high, d, setupOut);
   return true;
  }

void DrawArrow(const datetime t, const double price, const int d, const string setup)
  {
   string name = Prefix() + "SIG_" + IntegerToString((long)t);
   if(ObjectFind(0, name) >= 0) return;
   ObjectCreate(0, name, d == 1 ? OBJ_ARROW_BUY : OBJ_ARROW_SELL, 0, t, price);
   ObjectSetInteger(0, name, OBJPROP_COLOR, d == 1 ? clrMediumSeaGreen : clrCrimson);
   ObjectSetString(0, name, OBJPROP_TOOLTIP, (d == 1 ? "BUY " : "SELL ") + setup);
   //--- keep the chart light: remove the oldest arrows
   int total = ObjectsTotal(0, 0, -1);
   int count = 0;
   for(int k = total - 1; k >= 0; k--)
     {
      string nm = ObjectName(0, k, 0, -1);
      if(StringFind(nm, Prefix() + "SIG_") == 0)
        {
         count++;
         if(count > MAX_ARROWS) ObjectDelete(0, nm);
        }
     }
  }

//+------------------------------------------------------------------+
//| Position state (restart-safe through terminal global variables)  |
//+------------------------------------------------------------------+
bool SelectOurPosition(ulong &ticket, long &posId)
  {
   for(int k = PositionsTotal() - 1; k >= 0; k--)
     {
      ulong tk = PositionGetTicket(k);
      if(tk == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      ticket = tk;
      posId = PositionGetInteger(POSITION_IDENTIFIER);
      return true;
     }
   return false;
  }

string GvName(const long posId, const string key) { return Prefix() + IntegerToString(posId) + "_" + key; }

void SaveState(const long posId, const double vol0, const double entry, const double risk, const int stage)
  {
   GlobalVariableSet(GvName(posId, "vol0"), vol0);
   GlobalVariableSet(GvName(posId, "entry"), entry);
   GlobalVariableSet(GvName(posId, "risk"), risk);
   GlobalVariableSet(GvName(posId, "stage"), stage);
  }

//--- the partial close of the next stage already happened (only the stop move is pending)
bool PartialDone(const long posId, const int nextStage) { return GlobalVariableCheck(GvName(posId, "p" + IntegerToString(nextStage))); }
void MarkPartial(const long posId, const int nextStage) { GlobalVariableSet(GvName(posId, "p" + IntegerToString(nextStage)), 1.0); }

//--- move the stop to `level` if it improves it; true when the stop is at or beyond the level afterwards
bool MoveStopTo(const ulong tk, const int d, const double level, const double px, const double minGap)
  {
   double curSl = PositionGetDouble(POSITION_SL);
   if(curSl != 0.0 && (curSl - level) * d >= 0) return true;               // already there or better
   if(MathAbs(px - level) < minGap) return false;                          // too close to price now; retry next tick
   if(!g_trade.PositionModify(tk, level, PositionGetDouble(POSITION_TP)))
     {
      PrintFormat("APEX: stop move failed %d %s — retrying", g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
      return false;
     }
   return true;
  }

bool LoadState(const long posId, double &vol0, double &entry, double &risk, int &stage)
  {
   if(!GlobalVariableCheck(GvName(posId, "vol0"))) return false;
   vol0 = GlobalVariableGet(GvName(posId, "vol0"));
   entry = GlobalVariableGet(GvName(posId, "entry"));
   risk = GlobalVariableGet(GvName(posId, "risk"));
   stage = (int)GlobalVariableGet(GvName(posId, "stage"));
   return true;
  }

void CleanupState()
  {
   ulong tk = 0; long posId = -1;
   bool has = SelectOurPosition(tk, posId);
   string keep = has ? Prefix() + IntegerToString(posId) + "_" : "";
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   string today = IntegerToString(dt.year * 10000 + dt.mon * 100 + dt.day);
   for(int k = GlobalVariablesTotal() - 1; k >= 0; k--)
     {
      string nm = GlobalVariableName(k);
      if(StringFind(nm, Prefix()) != 0) continue;
      if(StringFind(nm, Prefix() + "dayeq_") == 0 || StringFind(nm, Prefix() + "halt_") == 0)
        {
         if(StringFind(nm, today) < 0) GlobalVariableDel(nm);   // only today's values matter
         continue;
        }
      if(has && StringFind(nm, keep) == 0) continue;
      GlobalVariableDel(nm);
     }
  }

//+------------------------------------------------------------------+
//| Daily loss limit (server day)                                    |
//+------------------------------------------------------------------+
bool DailyHalted()
  {
   MqlDateTime d;
   TimeToStruct(TimeCurrent(), d);
   string key = IntegerToString(d.year * 10000 + d.mon * 100 + d.day);
   string eqName = Prefix() + "dayeq_" + key, haltName = Prefix() + "halt_" + key;
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   if(!GlobalVariableCheck(eqName)) GlobalVariableSet(eqName, equity);
   if(GlobalVariableCheck(haltName)) return true;
   double start = GlobalVariableGet(eqName);
   if(start > 0 && equity <= start * (1.0 - InpMaxDailyLossPct / 100.0))
     {
      GlobalVariableSet(haltName, 1.0);
      PrintFormat("APEX: daily loss limit hit (equity %.2f vs %.2f at day start). No new trades today.", equity, start);
      if(InpCloseOnDailyLimit) CloseOurPosition("daily loss limit");
      return true;
     }
   return false;
  }

//+------------------------------------------------------------------+
//| Orders                                                           |
//+------------------------------------------------------------------+
bool IsHedging() { return AccountInfoInteger(ACCOUNT_MARGIN_MODE) == ACCOUNT_MARGIN_MODE_RETAIL_HEDGING; }

bool ClosePartial(const ulong tk, const double volume)
  {
   return IsHedging() ? g_trade.PositionClosePartial(tk, volume) : g_trade.PositionClosePartial(_Symbol, volume);
  }

bool CloseOurPosition(const string why)
  {
   ulong tk = 0; long posId = -1;
   if(!SelectOurPosition(tk, posId)) return true;
   bool done = IsHedging() ? g_trade.PositionClose(tk) : g_trade.PositionClose(_Symbol);
   if(done)
     {
      PrintFormat("APEX: closed position (%s)", why);
      return true;
     }
   PrintFormat("APEX: close failed (%s): %d %s", why, g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
   return false;
  }

double LotsForRisk(const int d, const double price, const double stop)
  {
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double tickSize = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE_LOSS);
   if(tickValue <= 0) tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double dist = MathAbs(price - stop);
   if(tickSize <= 0 || tickValue <= 0 || dist <= 0) return 0.0;
   double lossPerLot = dist / tickSize * tickValue;
   double lots = NormalizeVolume(equity * InpRiskPct / 100.0 / lossPerLot);
   //--- margin cap
   double margin = 0.0;
   ENUM_ORDER_TYPE type = d == 1 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   double freeMargin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   while(lots > 0 && OrderCalcMargin(type, _Symbol, lots, price, margin) && margin > freeMargin * InpMaxMarginFrac)
     {
      double smaller = NormalizeVolume(lots * 0.9);
      if(smaller >= lots) { lots = 0.0; break; }
      lots = smaller;
     }
   return lots;
  }

void TryEnter()
  {
   if(!g_pend.active) return;
   ulong openTk = 0; long openId = -1;
   if(SelectOurPosition(openTk, openId))      // a previous attempt already filled (e.g. timeout or partial fill)
     {
      g_pend.active = false;
      return;
     }
   if(TimeCurrent() > g_pend.expires)
     {
      Print("APEX: signal dropped — spread stayed above the limit during the entry window");
      g_pend.active = false;
      return;
     }
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK), bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if(ask <= 0 || bid <= 0 || ask - bid > InpMaxSpread) return;   // wait for a normal spread
   int d = g_pend.dir;
   double price = d == 1 ? ask : bid;
   double stop = RoundToTick(g_pend.stop);
   if((d == 1 && price <= stop) || (d == -1 && price >= stop))
     {
      Print("APEX: price is already beyond the stop — signal skipped");
      g_pend.active = false;
      return;
     }
   double risk = MathAbs(price - stop);
   double tp3 = RoundToTick(price + d * g_k3 * risk);
   long stopsLevel = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   if(risk < stopsLevel * _Point)
     {
      Print("APEX: stop closer than the broker's minimum distance — signal skipped");
      g_pend.active = false;
      return;
     }
   double lots = LotsForRisk(d, price, stop);
   if(lots <= 0)
     {
      Print("APEX: size below the broker minimum for this stop and risk — signal skipped");
      g_pend.active = false;
      return;
     }
   string comment = "APEX " + g_pend.setup;
   bool ok = d == 1 ? g_trade.Buy(lots, _Symbol, ask, stop, tp3, comment) : g_trade.Sell(lots, _Symbol, bid, stop, tp3, comment);
   uint rc = g_trade.ResultRetcode();
   if(!ok || (rc != TRADE_RETCODE_DONE && rc != TRADE_RETCODE_PLACED && rc != TRADE_RETCODE_DONE_PARTIAL))
     {
      PrintFormat("APEX: order failed %d %s — will retry while the entry window is open", g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
      return;
     }
   g_pend.active = false;
   ulong tk = 0; long posId = -1;
   if(SelectOurPosition(tk, posId))
     {
      double fill = PositionGetDouble(POSITION_PRICE_OPEN);
      double vol = PositionGetDouble(POSITION_VOLUME);
      double fillRisk = MathAbs(fill - stop);
      SaveState(posId, vol, fill, fillRisk, 0);
      double tpFromFill = RoundToTick(fill + d * g_k3 * fillRisk);
      if(MathAbs(tpFromFill - tp3) >= _Point)
         g_trade.PositionModify(tk, stop, tpFromFill);   // targets are measured from the real fill
      PrintFormat("APEX: %s %s %.2f lots @ %s  stop %s  risk %s", d == 1 ? "BUY" : "SELL", g_pend.setup, vol,
                  DoubleToString(fill, _Digits), DoubleToString(stop, _Digits), DoubleToString(fillRisk, _Digits));
     }
  }

//--- partial targets and stop moves, every tick
void ManagePosition()
  {
   ulong tk = 0; long posId = -1;
   if(!SelectOurPosition(tk, posId)) return;
   double vol0 = 0.0, entry = 0.0, risk = 0.0;
   int stage = 0;
   long type = PositionGetInteger(POSITION_TYPE);
   int d = type == POSITION_TYPE_BUY ? 1 : -1;
   double sl = PositionGetDouble(POSITION_SL), tp = PositionGetDouble(POSITION_TP);
   double vol = PositionGetDouble(POSITION_VOLUME);
   if(!LoadState(posId, vol0, entry, risk, stage))
     {
      //--- adopted without saved state (e.g. lost terminal variables): rebuild conservatively
      entry = PositionGetDouble(POSITION_PRICE_OPEN);
      vol0 = vol;
      if(sl > 0 && (entry - sl) * d > 0)
        {
         risk = MathAbs(entry - sl);    // stop still on the loss side: no partial has happened yet
         stage = 0;
        }
      else
        {
         risk = 0.0;                    // stop already moved: leave the rest to the broker-side stop and target
         stage = 3;
         if(sl <= 0) Print("APEX: WARNING — position ", posId, " has no stop loss. Set one manually.");
        }
      SaveState(posId, vol0, entry, risk, stage);
      Print("APEX: managing an existing position with rebuilt state (stage ", stage, ")");
     }
   if(risk <= 0 || stage >= 2) return;
   double px = d == 1 ? SymbolInfoDouble(_Symbol, SYMBOL_BID) : SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double tp1 = entry + d * g_k1 * risk, tp2 = entry + d * g_k2 * risk;
   long stopsLevel = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   double minGap = stopsLevel * _Point;

   if(stage == 0 && (px - tp1) * d >= 0)
     {
      if(!PartialDone(posId, 1))
        {
         double part = NormalizeVolume(vol0 * g_w1);
         if(part > 0 && part < vol)
           {
            if(!ClosePartial(tk, part)) { PrintFormat("APEX: TP1 partial failed %d", g_trade.ResultRetcode()); return; }
           }
         else Print("APEX: TP1 reached; volume too small to split — moving the stop only");
         MarkPartial(posId, 1);
        }
      if(SelectOurPosition(tk, posId) && MoveStopTo(tk, d, RoundToTick(entry), px, minGap))
         SaveState(posId, vol0, entry, risk, 1);
      return;
     }
   if(stage == 1 && (px - tp2) * d >= 0)
     {
      if(!PartialDone(posId, 2))
        {
         if(!SelectOurPosition(tk, posId)) return;
         double cur = PositionGetDouble(POSITION_VOLUME);
         double part = NormalizeVolume(vol0 * g_w2);
         if(part > 0 && part < cur)
           {
            if(!ClosePartial(tk, part)) { PrintFormat("APEX: TP2 partial failed %d", g_trade.ResultRetcode()); return; }
           }
         MarkPartial(posId, 2);
        }
      if(SelectOurPosition(tk, posId) && MoveStopTo(tk, d, RoundToTick(tp1), px, minGap))
         SaveState(posId, vol0, entry, risk, 2);
     }
  }

//+------------------------------------------------------------------+
//| Panel                                                            |
//+------------------------------------------------------------------+
string Arrow(const int t) { return t == 1 ? "up" : (t == -1 ? "down" : "flat"); }

void UpdatePanel(const bool halted)
  {
   static uint lastMs = 0;
   if(!InpShowPanel) return;
   uint nowMs = GetTickCount();
   if(nowMs - lastMs < 1000 && lastMs != 0) return;    // at most once per second
   lastMs = nowMs;
   string s = "APEX Fusion EA  |  " + _Symbol + " " + EnumToString(_Period) + "  |  " +
              (InpProfile == APEX_HIGHWIN ? "High Win-Rate 0.5R/2R/5R" : "Balanced 1R/3R/5R") + "\n";
   s += "Daily " + Arrow(g_last.anchor) + "   4H " + Arrow(g_last.htf) + "   score buy " + IntegerToString(g_last.scoreL) +
        " / sell " + IntegerToString(g_last.scoreS) + "   session " + (g_last.inSession ? "open" : "closed") + "\n";
   if(g_last.dir != 0)
      s += "Last signal: " + (g_last.dir == 1 ? "BUY " : "SELL ") + g_last.setup + " (" + TimeToString(g_last.time) + ")\n";
   ulong tk = 0; long posId = -1;
   if(SelectOurPosition(tk, posId))
     {
      double vol0 = 0.0, entry = 0.0, risk = 0.0; int stage = 0;
      LoadState(posId, vol0, entry, risk, stage);
      s += StringFormat("Position: %s %.2f lots @ %s  stop %s  stage %d  P/L %.2f\n",
                        PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY ? "BUY" : "SELL",
                        PositionGetDouble(POSITION_VOLUME), DoubleToString(PositionGetDouble(POSITION_PRICE_OPEN), _Digits),
                        DoubleToString(PositionGetDouble(POSITION_SL), _Digits), stage, PositionGetDouble(POSITION_PROFIT));
     }
   else s += g_pend.active ? "Waiting to enter (spread)\n" : "No position\n";
   s += halted ? "Status: HALTED for today (daily loss limit)\n" : "Status: active\n";
   Comment(s);
  }

//+------------------------------------------------------------------+
//| Expert events                                                    |
//+------------------------------------------------------------------+
int OnInit()
  {
   if(_Period != PERIOD_H1 && !InpAllowOtherTF)
     {
      Print("APEX: attach the EA to an H1 chart (only H1 was tested), or set 'Allow another timeframe'.");
      return INIT_PARAMETERS_INCORRECT;
     }
   if(InpRiskPct <= 0 || InpRiskPct > 5 || InpMaxDailyLossPct <= 0 || InpMaxDailyLossPct > 20 || InpMinScore < 0 || InpMinScore > 7 ||
      InpMaxMarginFrac <= 0 || InpMaxMarginFrac > 1)
     {
      Print("APEX: an input is outside its safe range (risk 0-5%, daily loss 0-20%, score 0-7, margin 0-1).");
      return INIT_PARAMETERS_INCORRECT;
     }
   if(StringFind(_Symbol, "XAU") < 0 && StringFind(_Symbol, "GOLD") < 0)
      Print("APEX: warning — this EA was tested on gold only; results on ", _Symbol, " are unknown.");
   if(InpProfile == APEX_HIGHWIN) { g_k1 = 0.5; g_k2 = 2.0; g_k3 = 5.0; }
   else                           { g_k1 = 1.0; g_k2 = 3.0; g_k3 = 5.0; }
   g_w1 = 0.50; g_w2 = 0.25;
   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetDeviationInPoints(InpDeviationPoints);
   g_trade.SetTypeFillingBySymbol(_Symbol);
   g_pend.active = false;
   g_last.time = 0; g_last.dir = 0; g_last.setup = ""; g_last.score = 0; g_last.htf = 0; g_last.anchor = 0;
   g_last.scoreL = 0; g_last.scoreS = 0; g_last.inSession = false;
   g_lastBar = iTime(_Symbol, _Period, 0);   // never trade a signal from before the EA was attached
   if(InpServerTime == SRV_NY_PLUS_7)
      Print("APEX: server time assumed New York + 7h. If your broker's server runs on fixed GMT, change 'Broker server time'.");
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   Comment("");
  }

void OnTick()
  {
   ManagePosition();
   bool halted = DailyHalted();

   datetime bar = iTime(_Symbol, _Period, 0);
   static datetime barSeen = 0;
   if(bar != g_lastBar && bar > 0)
     {
      if(bar != barSeen)                 // first tick of the new candle
        {
         barSeen = bar;
         g_pend.active = false;
         CleanupState();
        }
      int d = 0, score = 0; double stop = 0; string setup = ""; bool retry = false;
      bool got = ComputeSignal(d, stop, setup, score, retry);
      bool inWindow = TimeCurrent() < bar + InpEntryWindowMin * 60;
      if(retry && inWindow)
        {
         if(!halted) TryEnter();
         UpdatePanel(halted);
         return;                         // history still loading: try this candle again on the next tick
        }
      g_lastBar = bar;
      if(got && d != 0 && !halted)
        {
         ulong tk = 0; long posId = -1;
         bool has = SelectOurPosition(tk, posId);
         int curDir = has ? (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY ? 1 : -1) : 0;
         if(has && curDir == d)
            PrintFormat("APEX: %s signal ignored — already in a %s trade", setup, d == 1 ? "buy" : "sell");
         else if(has && !InpReverse)
            PrintFormat("APEX: %s signal ignored — opposite trade open and reversing is off", setup);
         else
           {
            bool flat = true;
            if(has) flat = CloseOurPosition("reverse on opposite signal");
            if(flat)
              {
               g_pend.active = true;
               g_pend.dir = d;
               g_pend.stop = stop;
               g_pend.setup = setup;
               g_pend.score = score;
               g_pend.expires = bar + InpEntryWindowMin * 60;
              }
           }
        }
     }
   if(!halted) TryEnter();
   UpdatePanel(halted);
  }
//+------------------------------------------------------------------+
