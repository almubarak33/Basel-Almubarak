import sys, zipfile, io, glob, os, datetime as dt
import numpy as np

def load(folder):
    rows=[]
    for f in sorted(glob.glob(os.path.join(folder,'XAUUSDT-1m-*.zip'))):
        with zipfile.ZipFile(f) as z:
            name=z.namelist()[0]
            txt=z.read(name).decode()
        for line in txt.splitlines():
            p=line.split(',')
            if not p[0].isdigit(): continue
            rows.append((int(p[0]),float(p[1]),float(p[2]),float(p[3]),float(p[4])))
    a=np.array(rows,dtype=np.float64)
    t=a[:,0].astype(np.int64)//1000
    if t.max()>4e10: t=t//1000   # microsecond timestamps
    return t,a[:,1],a[:,2],a[:,3],a[:,4]

def cfd_hours_mask(t):
    # keep bars when a spot/CFD gold market is open: closed Fri 22:00 UTC -> Sun 23:00 UTC
    wd=((t//86400)+3)%7          # 0=Mon ... 6=Sun
    hr=(t%86400)//3600
    closed=((wd==4)&(hr>=22))|(wd==5)|((wd==6)&(hr<23))
    return ~closed

def first_hit(cond_fn, i, n):
    # scan forward in growing windows; return first index >= i where cond is true, or -1
    w=256
    j=i
    while j<n:
        k=min(n,j+w)
        c=cond_fn(j,k)
        idx=np.argmax(c)
        if c[idx]:
            return j+int(idx)
        j=k; w=min(w*2,65536)
    return -1

def run(O,H,L,start,rng,cfg,max_bars):
    n=len(O); end=min(n,start+max_bars)
    bal=cfg['balance']; i=start; cyc=0; wins=0; peak=bal
    seq=cfg['seq']; s=cfg['spread']
    while i<end:
        d=seq[cyc%len(seq)]
        k=int(rng.integers(cfg['cmin'],cfg['cmax']+1))
        lot=cfg['lot'] if cfg['fixed_lot'] else max(0.01,np.floor(cfg['lot']*bal/cfg['balance']*100)/100)
        oz=k*lot*100.0
        T=rng.uniform(cfg['pmin'],cfg['pmax'])/100.0*bal
        o=O[i]
        tgt=T/oz; wipe=bal/oz
        stop=cfg['stop_mult']*tgt if cfg['stop_mult']>0 else None
        if d>0:
            lvl_t=o+s+tgt
            lvl_x=o+s-(stop if stop is not None else wipe)
            jt=first_hit(lambda a,b: H[a:b]>=lvl_t, i, end)
            jx=first_hit(lambda a,b: L[a:b]<=lvl_x, i, end)
        else:
            lvl_t=o-s-tgt
            lvl_x=o-s+(stop if stop is not None else wipe)
            jt=first_hit(lambda a,b: L[a:b]<=lvl_t, i, end)
            jx=first_hit(lambda a,b: H[a:b]>=lvl_x, i, end)
        if jt<0 and jx<0:
            # still open at the horizon: mark to market at last bar open
            px=O[end-1]
            pl=((px-o-s) if d>0 else (o-px-s))*oz
            return dict(final=max(0.0,bal+pl),wiped=False,cycles=cyc,wins=wins,peak=peak,bars=end-start,open_pl=pl)
        # same-bar ambiguity: cfg['optimistic'] decides which one counts first
        target_first = (jt>=0) and (jx<0 or jt<jx or (jt==jx and cfg['optimistic']))
        cyc+=1
        if target_first:
            bal+=T; wins+=1; peak=max(peak,bal); i=jt+1
        else:
            if stop is None:
                return dict(final=0.0,wiped=True,cycles=cyc,wins=wins,peak=peak,bars=jx-start,open_pl=0.0)
            bal-=stop*oz+0.0   # loss at the stop (spread already inside the level)
            i=jx+1
            if bal<=0: return dict(final=0.0,wiped=True,cycles=cyc,wins=wins,peak=peak,bars=jx-start,open_pl=0.0)
    return dict(final=bal,wiped=False,cycles=cyc,wins=wins,peak=peak,bars=end-start,open_pl=0.0)

def summarize(name,res,bars_per_day,balance):
    f=np.array([r['final'] for r in res]); w=np.array([r['wiped'] for r in res]); b=np.array([r['bars'] for r in res])
    cyc=np.array([r['cycles'] for r in res]); wins=np.array([r['wins'] for r in res]); pk=np.array([r['peak'] for r in res])
    days=b/bars_per_day
    print(f'--- {name}: runs={len(res)}')
    print(f'   wiped out: {100*w.mean():.1f}%   | within 1 day: {100*(w&(days<=1)).mean():.1f}%  within 5 days: {100*(w&(days<=5)).mean():.1f}%  within 21 days: {100*(w&(days<=21)).mean():.1f}%')
    if w.any(): print(f'   time to wipe-out (trading days): median {np.median(days[w]):.2f}, 25th pct {np.percentile(days[w],25):.2f}, 75th pct {np.percentile(days[w],75):.2f}')
    print(f'   cycle win rate: {100*wins.sum()/max(1,cyc.sum()):.2f}%  | cycles per run: median {np.median(cyc):.0f}')
    print(f'   final equity: mean {f.mean():,.0f}  median {np.median(f):,.0f}  (start {balance:,.0f})  | runs ending above start: {100*(f>balance).mean():.1f}%  | above 2x: {100*(f>2*balance).mean():.1f}%')
    print(f'   peak balance before the end: median {np.median(pk):,.0f}; among wiped runs median peak {np.median(pk[w]) if w.any() else float("nan"):,.0f}')

if __name__=='__main__':
    folder=sys.argv[1]
    t,O,H,L,C=load(folder)
    m=cfd_hours_mask(t); t,O,H,L,C=t[m],O[m],H[m],L[m],C[m]
    print('bars',len(t),'from',dt.datetime.utcfromtimestamp(int(t[0])),'to',dt.datetime.utcfromtimestamp(int(t[-1])),'price',O[0],'->',C[-1])
    print('median 1-min range',np.median(H-L),'mean',np.mean(H-L))
    bars_per_day=1380.0   # 23 hours
    horizon=int(21*bars_per_day)
    starts=np.arange(0,len(t)-horizon, int(bars_per_day/3))   # every ~8 trading hours
    base=dict(balance=10000.0,lot=0.07,seq=[1,-1,-1],cmin=10,cmax=20,pmin=1.0,pmax=3.0,spread=0.30,fixed_lot=True,stop_mult=0.0,optimistic=True)
    variants=[('A: as in the video, no stop, FIXED lot (most favourable to the bot)',dict()),
              ('B: as in the video, no stop, lot grows with balance (what the video does)',dict(fixed_lot=False)),
              ('C: fixed lot, spread 0.20',dict(spread=0.20)),
              ('D: fixed lot, stop-loss = same distance as target (1:1)',dict(stop_mult=1.0)),
              ('E: fixed lot, stop-loss = 3x target distance',dict(stop_mult=3.0))]
    for name,ov in variants:
        cfg=dict(base); cfg.update(ov)
        res=[]
        for q,s0 in enumerate(starts):
            rng=np.random.default_rng(1000+q)
            res.append(run(O,H,L,int(s0),rng,cfg,horizon))
        summarize(name,res,bars_per_day,cfg['balance'])
