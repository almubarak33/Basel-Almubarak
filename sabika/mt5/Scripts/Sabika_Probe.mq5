//+------------------------------------------------------------------+
//|                                                 Sabika_Probe.mq5 |
//|  Read-only probe of the account, the server clock and the gold   |
//|  and silver symbols of the connected broker.                     |
//|  It sends, modifies and closes NO orders.                        |
//+------------------------------------------------------------------+
#property copyright   "Sabika project"
#property version     "1.00"
#property description "Read-only probe for gold and silver symbols."
#property description "Writes a text report to MQL5\\Files. Sends NO orders."
#property script_show_inputs

#define MAX_SYMBOLS   16
#define MAX_DETAILED  6

input string InpSymbols     = "";       // Extra symbols, comma-separated (empty = auto-detect)
input double InpCapital     = 10000.0;  // Capital for the feasibility table (account currency)
input double InpRiskPercent = 0.5;      // Risk per trade, percent of capital
input int    InpSpreadDays  = 20;       // Days of M1 history for the spread table
input bool   InpProbeTicks  = true;     // Check real-tick history depth (can take a minute)

int g_file       = INVALID_HANDLE;
int g_user_count = 0;

//+------------------------------------------------------------------+
//| Small helpers                                                    |
//+------------------------------------------------------------------+
void W(const string s)
  {
   if(g_file != INVALID_HANDLE)
      FileWriteString(g_file, s + "\r\n");
  }

string YesNo(const bool v)
  {
   return v ? "yes" : "no";
  }

string Sanitize(const string s)
  {
   string out = "";
   int n = StringLen(s);
   for(int i = 0; i < n; i++)
     {
      ushort c = StringGetCharacter(s, i);
      bool ok = (c >= '0' && c <= '9') || (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z');
      if(ok)
         out += ShortToString(c);
      else
         out += "_";
     }
   return out;
  }

// Session times are returned as seconds from midnight; 24:00 must print as 24:00.
string HHMM(const datetime t)
  {
   long sec = (long)t;
   int h = (int)(sec / 3600);
   int m = (int)((sec % 3600) / 60);
   return StringFormat("%02d:%02d", h, m);
  }

bool StartsWith(const string s, const string prefix)
  {
   return StringFind(s, prefix) == 0;
  }

// 2 = the name starts like a spot metal, 1 = the name or description mentions one, 0 = no match
int MetalRank(const string name)
  {
   string a = name;
   StringToUpper(a);
   if(StartsWith(a, "XAU") || StartsWith(a, "XAG") || StartsWith(a, "GOLD") || StartsWith(a, "SILVER"))
      return 2;
   if(StringFind(a, "XAU") >= 0 || StringFind(a, "XAG") >= 0 || StringFind(a, "GOLD") >= 0 || StringFind(a, "SILVER") >= 0)
      return 1;
   string b = SymbolInfoString(name, SYMBOL_DESCRIPTION);
   StringToUpper(b);
   if(StringFind(b, "XAU") >= 0 || StringFind(b, "XAG") >= 0)
      return 1;
   return 0;
  }

void AddUnique(string &list[], const string name)
  {
   int n = ArraySize(list);
   for(int i = 0; i < n; i++)
     {
      if(list[i] == name)
         return;
     }
   ArrayResize(list, n + 1);
   list[n] = name;
  }

int CopyRatesRetry(const string sym, const ENUM_TIMEFRAMES tf, const int start, const int count, MqlRates &r[])
  {
   int n = -1;
   for(int k = 0; k < 6; k++)
     {
      ResetLastError();
      n = CopyRates(sym, tf, start, count, r);
      if(n > 0)
         break;
      if(IsStopped())
         break;
      Sleep(500);
     }
   return n;
  }

//+------------------------------------------------------------------+
//| Symbol discovery                                                 |
//+------------------------------------------------------------------+
int CollectSymbols(string &list[], int &skipped)
  {
   ArrayResize(list, 0);
   skipped = 0;
   g_user_count = 0;
   if(StringLen(InpSymbols) > 0)
     {
      string parts[];
      int k = StringSplit(InpSymbols, ',', parts);
      for(int i = 0; i < k; i++)
        {
         string s = parts[i];
         StringTrimLeft(s);
         StringTrimRight(s);
         if(StringLen(s) > 0)
            AddUnique(list, s);
        }
      g_user_count = ArraySize(list);
     }
   int total = SymbolsTotal(false);
   for(int pass = 2; pass >= 1; pass--)
     {
      for(int i = 0; i < total; i++)
        {
         string name = SymbolName(i, false);
         if(MetalRank(name) != pass)
            continue;
         if(ArraySize(list) >= MAX_SYMBOLS)
           {
            skipped++;
            continue;
           }
         AddUnique(list, name);
        }
     }
   return ArraySize(list);
  }

//+------------------------------------------------------------------+
//| Account, terminal and clock                                      |
//+------------------------------------------------------------------+
void ReportAccount()
  {
   W("=== TERMINAL ===");
   W("terminal: " + TerminalInfoString(TERMINAL_NAME) + ", build " + IntegerToString(TerminalInfoInteger(TERMINAL_BUILD)));
   W("connected to server: " + YesNo(TerminalInfoInteger(TERMINAL_CONNECTED) != 0));
   W("max bars in chart: " + IntegerToString(TerminalInfoInteger(TERMINAL_MAXBARS)));
   W("");
   W("=== ACCOUNT (no number, name or balance is recorded) ===");
   W("broker company: " + AccountInfoString(ACCOUNT_COMPANY));
   W("server: " + AccountInfoString(ACCOUNT_SERVER));
   W("account type: " + EnumToString((ENUM_ACCOUNT_TRADE_MODE)AccountInfoInteger(ACCOUNT_TRADE_MODE)));
   W("position accounting: " + EnumToString((ENUM_ACCOUNT_MARGIN_MODE)AccountInfoInteger(ACCOUNT_MARGIN_MODE)));
   W("account currency: " + AccountInfoString(ACCOUNT_CURRENCY));
   W("leverage: 1:" + IntegerToString(AccountInfoInteger(ACCOUNT_LEVERAGE)));
   W("stop-out mode: " + EnumToString((ENUM_ACCOUNT_STOPOUT_MODE)AccountInfoInteger(ACCOUNT_MARGIN_SO_MODE)));
   W("margin call level: " + DoubleToString(AccountInfoDouble(ACCOUNT_MARGIN_SO_CALL), 2));
   W("stop-out level: " + DoubleToString(AccountInfoDouble(ACCOUNT_MARGIN_SO_SO), 2));
   W("trading allowed for the account: " + YesNo(AccountInfoInteger(ACCOUNT_TRADE_ALLOWED) != 0));
   W("Expert Advisors allowed by the server: " + YesNo(AccountInfoInteger(ACCOUNT_TRADE_EXPERT) != 0));
   W("max active pending orders (0 = no limit): " + IntegerToString(AccountInfoInteger(ACCOUNT_LIMIT_ORDERS)));
   W("FIFO close rule: " + YesNo(AccountInfoInteger(ACCOUNT_FIFO_CLOSE) != 0));
   W("");
   W("=== CLOCKS ===");
   datetime ts = TimeTradeServer();
   datetime tg = TimeGMT();
   datetime tl = TimeLocal();
   datetime tc = TimeCurrent();
   double off = (double)((long)ts - (long)tg) / 3600.0;
   W("server time (estimated now): " + TimeToString(ts, TIME_DATE | TIME_SECONDS));
   W("time of the last quote: " + TimeToString(tc, TIME_DATE | TIME_SECONDS));
   W("GMT according to this PC: " + TimeToString(tg, TIME_DATE | TIME_SECONDS));
   W("local PC time: " + TimeToString(tl, TIME_DATE | TIME_SECONDS));
   W("server minus GMT, hours: " + DoubleToString(off, 2) + " (valid only if the PC clock is right and the terminal is connected)");
  }

//+------------------------------------------------------------------+
//| Volatility helpers                                               |
//+------------------------------------------------------------------+
double MedianRange(const string sym, const ENUM_TIMEFRAMES tf, const int count)
  {
   MqlRates r[];
   int n = CopyRatesRetry(sym, tf, 1, count, r);
   if(n <= 0)
      return 0.0;
   double a[];
   ArrayResize(a, n);
   for(int i = 0; i < n; i++)
      a[i] = r[i].high - r[i].low;
   ArraySort(a);
   return a[n / 2];
  }

double AtrD1(const string sym, const int period)
  {
   MqlRates r[];
   int n = CopyRatesRetry(sym, PERIOD_D1, 1, period + 1, r);
   if(n < 2)
      return 0.0;
   double sum = 0.0;
   int cnt = 0;
   for(int i = 1; i < n; i++)
     {
      double hl = r[i].high - r[i].low;
      double hc = MathAbs(r[i].high - r[i - 1].close);
      double lc = MathAbs(r[i].low - r[i - 1].close);
      sum += MathMax(hl, MathMax(hc, lc));
      cnt++;
     }
   if(cnt == 0)
      return 0.0;
   return sum / cnt;
  }

//+------------------------------------------------------------------+
//| Spread recorded in M1 bars, grouped by server hour               |
//+------------------------------------------------------------------+
void SpreadByHour(const string sym, const double point, const int digits)
  {
   int want = InpSpreadDays * 1440;
   if(want < 1440)
      want = 1440;
   if(want > 200000)
      want = 200000;
   MqlRates r[];
   int n = CopyRatesRetry(sym, PERIOD_M1, 1, want, r);
   if(n <= 0)
     {
      W("  M1 history not available (returned " + IntegerToString(n) + ", error " + IntegerToString(GetLastError()) + ")");
      return;
     }
   double sum[24];
   double rng[24];
   int    cnt[24];
   int    mx[24];
   ArrayInitialize(sum, 0.0);
   ArrayInitialize(rng, 0.0);
   ArrayInitialize(cnt, 0);
   ArrayInitialize(mx, 0);
   int all[];
   ArrayResize(all, n);
   MqlDateTime dt;
   for(int i = 0; i < n; i++)
     {
      TimeToStruct(r[i].time, dt);
      int h = dt.hour;
      int sp = r[i].spread;
      sum[h] += sp;
      rng[h] += (r[i].high - r[i].low);
      cnt[h]++;
      if(sp > mx[h])
         mx[h] = sp;
      all[i] = sp;
     }
   ArraySort(all);
   int i90 = (int)(n * 0.90);
   int i99 = (int)(n * 0.99);
   W("  M1 bars used: " + IntegerToString(n) + ", from " + TimeToString(r[0].time) + " to " + TimeToString(r[n - 1].time));
   W("  note: the spread stored in an M1 bar is one value per minute and can understate the live spread");
   W("  spread in points: median " + IntegerToString(all[n / 2]) + ", 90th pct " + IntegerToString(all[i90]) +
     ", 99th pct " + IntegerToString(all[i99]) + ", max " + IntegerToString(all[n - 1]));
   W("  server hour | bars | mean spread points | max spread points | mean spread price | mean M1 range price");
   for(int h = 0; h < 24; h++)
     {
      if(cnt[h] == 0)
        {
         W(StringFormat("  %02d | 0 | - | - | - | -", h));
         continue;
        }
      double ms = sum[h] / cnt[h];
      double mr = rng[h] / cnt[h];
      W(StringFormat("  %02d | %d | %.1f | %d | %s | %s", h, cnt[h], ms, mx[h],
                     DoubleToString(ms * point, digits + 1), DoubleToString(mr, digits + 1)));
     }
  }

//+------------------------------------------------------------------+
//| How far back real ticks are available                            |
//+------------------------------------------------------------------+
void TickDepth(const string sym)
  {
   int days_back[8] = {7, 30, 90, 180, 365, 730, 1095, 1825};
   datetime now = TimeTradeServer();
   for(int i = 0; i < 8; i++)
     {
      if(IsStopped())
         break;
      datetime from = (datetime)((long)now - (long)days_back[i] * 86400);
      MqlTick t[];
      ResetLastError();
      int got = CopyTicks(sym, t, COPY_TICKS_ALL, (ulong)from * 1000, 1);
      if(got <= 0)
        {
         W(StringFormat("  %d days back (%s): no ticks (returned %d, error %d)",
                        days_back[i], TimeToString(from, TIME_DATE), got, GetLastError()));
         break;
        }
      long gap_days = ((long)t[0].time - (long)from) / 86400;
      W(StringFormat("  %d days back (%s): first tick found at %s",
                     days_back[i], TimeToString(from, TIME_DATE), TimeToString(t[0].time, TIME_DATE | TIME_MINUTES)));
      if(gap_days > 5)
        {
         W("  -> real tick history starts about here; older ticks are not available on this server");
         break;
        }
     }
  }

//+------------------------------------------------------------------+
//| Position size that fits the risk budget for several stop sizes   |
//+------------------------------------------------------------------+
void FeasibilityRow(const string sym, const string label, const double ref, const double dist,
                    const double vmin, const double vstep, const double contract, const int digits)
  {
   if(ref <= 0.0 || dist <= 0.0 || dist >= ref || vmin <= 0.0 || vstep <= 0.0)
     {
      W("  " + label + " | not computable");
      return;
     }
   double loss_min = 0.0;
   if(!OrderCalcProfit(ORDER_TYPE_BUY, sym, vmin, ref, ref - dist, loss_min))
     {
      W("  " + label + " | OrderCalcProfit failed, error " + IntegerToString(GetLastError()));
      return;
     }
   loss_min = MathAbs(loss_min);
   double risk_money = InpCapital * InpRiskPercent / 100.0;
   double lots = 0.0;
   if(loss_min > 0.0)
     {
      double raw = risk_money / (loss_min / vmin);
      lots = MathFloor(raw / vstep + 0.000000001) * vstep;
      if(lots < vmin)
         lots = 0.0;
     }
   double loss_pct = 0.0;
   if(InpCapital > 0.0)
      loss_pct = 100.0 * loss_min / InpCapital;
   double notional_mult = 0.0;
   if(InpCapital > 0.0)
      notional_mult = lots * contract * ref / InpCapital;
   W("  " + label + " | stop distance " + DoubleToString(dist, digits) +
     " | loss at MIN lot " + DoubleToString(loss_min, 2) + " (" + DoubleToString(loss_pct, 2) + "% of capital)" +
     " | lots within budget " + DoubleToString(lots, 2) +
     " | position value / capital " + DoubleToString(notional_mult, 2));
  }

//+------------------------------------------------------------------+
//| One symbol                                                       |
//+------------------------------------------------------------------+
void ReportSymbol(const string sym, const bool detailed)
  {
   W("");
   W("=== SYMBOL: " + sym + " ===");
   bool was_selected = (SymbolInfoInteger(sym, SYMBOL_SELECT) != 0);
   if(!was_selected)
     {
      ResetLastError();
      if(!SymbolSelect(sym, true))
        {
         W("  cannot select this symbol (not found on this server?), error " + IntegerToString(GetLastError()));
         return;
        }
     }

   MqlTick tk;
   ZeroMemory(tk);
   bool have_tick = false;
   for(int k = 0; k < 10; k++)
     {
      if(SymbolInfoTick(sym, tk) && tk.bid > 0.0 && tk.ask > 0.0)
        {
         have_tick = true;
         break;
        }
      Sleep(300);
     }

   int    digits   = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   double point    = SymbolInfoDouble(sym, SYMBOL_POINT);
   double tsize    = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   double tval     = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
   double tval_p   = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE_PROFIT);
   double tval_l   = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE_LOSS);
   double contract = SymbolInfoDouble(sym, SYMBOL_TRADE_CONTRACT_SIZE);
   double vmin     = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
   double vstep    = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
   double vmax     = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
   double vlimit   = SymbolInfoDouble(sym, SYMBOL_VOLUME_LIMIT);
   long   stops    = SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL);
   long   freeze   = SymbolInfoInteger(sym, SYMBOL_TRADE_FREEZE_LEVEL);
   long   fill     = SymbolInfoInteger(sym, SYMBOL_FILLING_MODE);
   long   omode    = SymbolInfoInteger(sym, SYMBOL_ORDER_MODE);
   long   emode    = SymbolInfoInteger(sym, SYMBOL_EXPIRATION_MODE);

   W("description: " + SymbolInfoString(sym, SYMBOL_DESCRIPTION));
   W("path: " + SymbolInfoString(sym, SYMBOL_PATH));
   W("currencies base/profit/margin: " + SymbolInfoString(sym, SYMBOL_CURRENCY_BASE) + " / " +
     SymbolInfoString(sym, SYMBOL_CURRENCY_PROFIT) + " / " + SymbolInfoString(sym, SYMBOL_CURRENCY_MARGIN));
   W("digits: " + IntegerToString(digits) + ", point: " + DoubleToString(point, digits + 2));
   W("tick size: " + DoubleToString(tsize, digits + 2));
   W("tick value (reported / profit side / loss side): " + DoubleToString(tval, 6) + " / " +
     DoubleToString(tval_p, 6) + " / " + DoubleToString(tval_l, 6));
   W("contract size (units per 1.00 lot): " + DoubleToString(contract, 2));
   W("volume min / step / max / limit: " + DoubleToString(vmin, 4) + " / " + DoubleToString(vstep, 4) + " / " +
     DoubleToString(vmax, 2) + " / " + DoubleToString(vlimit, 2));
   W("stops level points: " + IntegerToString(stops) + ", freeze level points: " + IntegerToString(freeze));
   W("trade mode: " + EnumToString((ENUM_SYMBOL_TRADE_MODE)SymbolInfoInteger(sym, SYMBOL_TRADE_MODE)));
   W("execution mode: " + EnumToString((ENUM_SYMBOL_TRADE_EXECUTION)SymbolInfoInteger(sym, SYMBOL_TRADE_EXEMODE)));
   W("calculation mode: " + EnumToString((ENUM_SYMBOL_CALC_MODE)SymbolInfoInteger(sym, SYMBOL_TRADE_CALC_MODE)));
   W("filling flags (raw " + IntegerToString(fill) + "): FOK=" + YesNo((fill & 1) != 0) + " IOC=" + YesNo((fill & 2) != 0) +
     " BOC=" + YesNo((fill & 4) != 0));
   W("order flags (raw " + IntegerToString(omode) + "): market=" + YesNo((omode & 1) != 0) + " limit=" + YesNo((omode & 2) != 0) +
     " stop=" + YesNo((omode & 4) != 0) + " stop-limit=" + YesNo((omode & 8) != 0) + " SL=" + YesNo((omode & 16) != 0) +
     " TP=" + YesNo((omode & 32) != 0) + " close-by=" + YesNo((omode & 64) != 0));
   W("expiration flags (raw " + IntegerToString(emode) + "): GTC=" + YesNo((emode & 1) != 0) + " day=" + YesNo((emode & 2) != 0) +
     " specified=" + YesNo((emode & 4) != 0) + " specified-day=" + YesNo((emode & 8) != 0));
   W("swap mode: " + EnumToString((ENUM_SYMBOL_SWAP_MODE)SymbolInfoInteger(sym, SYMBOL_SWAP_MODE)));
   W("swap long / short: " + DoubleToString(SymbolInfoDouble(sym, SYMBOL_SWAP_LONG), 4) + " / " +
     DoubleToString(SymbolInfoDouble(sym, SYMBOL_SWAP_SHORT), 4));
   W("triple swap day: " + EnumToString((ENUM_DAY_OF_WEEK)SymbolInfoInteger(sym, SYMBOL_SWAP_ROLLOVER3DAYS)));
   W("floating spread: " + YesNo(SymbolInfoInteger(sym, SYMBOL_SPREAD_FLOAT) != 0));

   //--- current quote
   double ref = 0.0;
   string ref_src = "none";
   if(have_tick)
     {
      ref = tk.ask;
      ref_src = "current ask";
      long age = (long)TimeTradeServer() - (long)tk.time;
      W("bid / ask: " + DoubleToString(tk.bid, digits) + " / " + DoubleToString(tk.ask, digits) +
        ", spread price " + DoubleToString(tk.ask - tk.bid, digits) +
        ", spread points " + DoubleToString((point > 0.0) ? (tk.ask - tk.bid) / point : 0.0, 0));
      W("quote time: " + TimeToString(tk.time, TIME_DATE | TIME_SECONDS) + ", age seconds: " + IntegerToString(age) +
        ((age > 600) ? " (market closed or no fresh ticks: this spread is NOT representative)" : ""));
     }
   else
     {
      MqlRates lr[];
      if(CopyRatesRetry(sym, PERIOD_M1, 0, 1, lr) > 0)
        {
         ref = lr[0].close;
         ref_src = "last M1 close (no live quote)";
        }
      W("bid / ask: no live quote received");
     }
   W("reference price for the calculations below: " + DoubleToString(ref, digits) + " (" + ref_src + ")");

   //--- money facts computed by the terminal itself
   if(ref > 1.0)
     {
      double p_lot = 0.0;
      double p_min = 0.0;
      double p_tick = 0.0;
      double margin_min = 0.0;
      if(OrderCalcProfit(ORDER_TYPE_BUY, sym, 1.0, ref, ref - 1.0, p_lot))
         W("money for a 1.00 price move, 1.00 lot: " + DoubleToString(MathAbs(p_lot), 2));
      else
         W("money for a 1.00 price move, 1.00 lot: OrderCalcProfit failed, error " + IntegerToString(GetLastError()));
      if(vmin > 0.0 && OrderCalcProfit(ORDER_TYPE_BUY, sym, vmin, ref, ref - 1.0, p_min))
         W("money for a 1.00 price move, MIN lot: " + DoubleToString(MathAbs(p_min), 4));
      if(tsize > 0.0 && OrderCalcProfit(ORDER_TYPE_BUY, sym, 1.0, ref, ref + tsize, p_tick))
         W("tick value recomputed with OrderCalcProfit (compare with the reported one): " + DoubleToString(MathAbs(p_tick), 6));
      if(vmin > 0.0 && OrderCalcMargin(ORDER_TYPE_BUY, sym, vmin, ref, margin_min))
        {
         double notional_min = vmin * contract * ref;
         W("margin for MIN lot: " + DoubleToString(margin_min, 2) + ", position value of MIN lot (profit currency): " +
           DoubleToString(notional_min, 2) +
           ((notional_min > 0.0) ? ", margin rate percent: " + DoubleToString(100.0 * margin_min / notional_min, 2) : ""));
        }
      else
         W("margin for MIN lot: OrderCalcMargin failed, error " + IntegerToString(GetLastError()));
     }

   //--- trading sessions in server time
   W("trade sessions (server time):");
   for(int d = 0; d < 7; d++)
     {
      string line = "  " + EnumToString((ENUM_DAY_OF_WEEK)d) + ": ";
      bool any = false;
      for(uint s = 0; s < 10; s++)
        {
         datetime from = 0;
         datetime to = 0;
         if(!SymbolInfoSessionTrade(sym, (ENUM_DAY_OF_WEEK)d, s, from, to))
            break;
         any = true;
         line += HHMM(from) + "-" + HHMM(to) + " ";
        }
      if(!any)
         line += "closed";
      W(line);
     }

   if(detailed)
     {
      //--- history depth
      MqlRates tmp[];
      CopyRatesRetry(sym, PERIOD_M1, 0, 10, tmp);
      CopyRatesRetry(sym, PERIOD_D1, 0, 10, tmp);
      W("history:");
      W("  first date on the server: " + TimeToString((datetime)SeriesInfoInteger(sym, PERIOD_M1, SERIES_SERVER_FIRSTDATE), TIME_DATE));
      W("  first M1 bar in this terminal: " + TimeToString((datetime)SeriesInfoInteger(sym, PERIOD_M1, SERIES_FIRSTDATE), TIME_DATE) +
        ", M1 bars loaded: " + IntegerToString(Bars(sym, PERIOD_M1)));
      W("  first D1 bar in this terminal: " + TimeToString((datetime)SeriesInfoInteger(sym, PERIOD_D1, SERIES_FIRSTDATE), TIME_DATE) +
        ", D1 bars loaded: " + IntegerToString(Bars(sym, PERIOD_D1)));

      //--- volatility scale
      double atr_d1 = AtrD1(sym, 14);
      double med_h1 = MedianRange(sym, PERIOD_H1, 240);
      double med_m15 = MedianRange(sym, PERIOD_M15, 960);
      W("volatility (price units):");
      W("  ATR(14) on D1: " + DoubleToString(atr_d1, digits) +
        ((ref > 0.0) ? " (" + DoubleToString(100.0 * atr_d1 / ref, 2) + "% of price)" : ""));
      W("  median H1 bar range, last 240 bars: " + DoubleToString(med_h1, digits));
      W("  median M15 bar range, last 960 bars: " + DoubleToString(med_m15, digits));

      //--- feasibility for the chosen capital and risk
      W("position sizing for capital " + DoubleToString(InpCapital, 2) + " and risk " + DoubleToString(InpRiskPercent, 2) +
        "% (" + DoubleToString(InpCapital * InpRiskPercent / 100.0, 2) + " per trade):");
      double pct[5] = {0.10, 0.25, 0.50, 1.00, 2.00};
      for(int i = 0; i < 5; i++)
        {
         string label = "stop " + DoubleToString(pct[i], 2) + "% of price";
         FeasibilityRow(sym, label, ref, ref * pct[i] / 100.0, vmin, vstep, contract, digits);
        }
      if(atr_d1 > 0.0)
         FeasibilityRow(sym, "stop 3 x ATR(D1)", ref, 3.0 * atr_d1, vmin, vstep, contract, digits);

      //--- spread by hour
      W("spread recorded in M1 bars, by server hour:");
      SpreadByHour(sym, point, digits);

      //--- tick depth
      if(InpProbeTicks)
        {
         W("real tick history depth:");
         TickDepth(sym);
        }
     }

   if(!was_selected)
      SymbolSelect(sym, false);
  }

//+------------------------------------------------------------------+
//| Script entry point                                               |
//+------------------------------------------------------------------+
void OnStart()
  {
   string server = AccountInfoString(ACCOUNT_SERVER);
   string fname = "Sabika_Probe_" + Sanitize(server) + ".txt";
   g_file = FileOpen(fname, FILE_WRITE | FILE_TXT | FILE_ANSI, 0, CP_UTF8);
   if(g_file == INVALID_HANDLE)
     {
      Print("Sabika_Probe: cannot create ", fname, ", error ", GetLastError());
      return;
     }
   Print("Sabika_Probe: started. This is read-only and can take a minute or two.");

   W("SABIKA PROBE REPORT v1.00");
   W("Read-only: this script sends, modifies and closes NO orders.");
   W("");
   ReportAccount();

   string list[];
   int skipped = 0;
   int n = CollectSymbols(list, skipped);
   W("");
   W("=== MATCHED SYMBOLS (" + IntegerToString(n) + ") ===");
   for(int i = 0; i < n; i++)
      W("  " + list[i] + " | " + SymbolInfoString(list[i], SYMBOL_DESCRIPTION));
   if(skipped > 0)
      W("  (" + IntegerToString(skipped) + " more matches were not listed; name them in the InpSymbols input if needed)");
   if(n == 0)
      W("  no gold or silver symbol was found; type the exact names in the InpSymbols input and run again");

   int detailed_used = 0;
   for(int i = 0; i < n; i++)
     {
      if(IsStopped())
         break;
      Print("Sabika_Probe: ", list[i], " (", i + 1, " of ", n, ")");
      bool detailed = false;
      if(detailed_used < MAX_DETAILED)
        {
         if(i < g_user_count)
            detailed = true;
         else
            if(MetalRank(list[i]) == 2 && SymbolInfoString(list[i], SYMBOL_CURRENCY_PROFIT) == "USD")
               detailed = true;
        }
      if(detailed)
         detailed_used++;
      ReportSymbol(list[i], detailed);
      FileFlush(g_file);
     }

   W("");
   W("END OF REPORT");
   FileClose(g_file);
   g_file = INVALID_HANDLE;
   Print("Sabika_Probe: finished. Report file: MQL5\\Files\\", fname);
   MessageBox("Report written to:\nMQL5\\Files\\" + fname + "\n\nOpen it from File > Open Data Folder > MQL5 > Files.",
              "Sabika Probe", MB_OK | MB_ICONINFORMATION);
  }
//+------------------------------------------------------------------+
