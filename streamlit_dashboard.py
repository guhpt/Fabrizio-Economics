"""
FABRIZIO ECONOMICS — Dashboard
================================
Dashboard Streamlit para monitorização do bot de paper trading.

Instalar: pip install streamlit plotly pandas
Correr:   streamlit run streamlit_dashboard.py
Abre em:  http://localhost:8501
"""

import sqlite3
import os
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timezone
import streamlit as st

# ── Configuração da página ────────────────────────────────────
st.set_page_config(
    page_title="FabrizioEconomics",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Modo: local (DB) ou online (CSV) ─────────────────────────
# Quando corre no Streamlit Cloud não há DB local — lê o CSV.
# Quando corre localmente lê directamente da DB para dados em tempo real.
DB_FILE     = r"C:\Users\hn\Desktop\BOT\trading_bot.db"
CSV_FILE    = "data/trades.csv"
INITIAL_CAP = 10_000.0
ONLINE_MODE = not os.path.exists(DB_FILE)  # True no Streamlit Cloud

# ── Estilos ───────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Syne:wght@400;600;800&display=swap');

html, body, [class*="css"] {
    font-family: 'Syne', sans-serif;
    background-color: #0a0a0f;
    color: #e8e8e8;
}
h1, h2, h3 { font-family: 'Syne', sans-serif; font-weight: 800; }
code, .metric-value { font-family: 'Space Mono', monospace; }

.stMetric {
    background: #111118;
    border: 1px solid #1e1e2e;
    border-radius: 12px;
    padding: 1rem 1.2rem;
}
.stMetric label { color: #666 !important; font-size: 0.75rem !important; letter-spacing: 0.1em; text-transform: uppercase; }
.stMetric [data-testid="stMetricValue"] { font-family: 'Space Mono', monospace; font-size: 1.6rem !important; color: #e8e8e8 !important; }
.stMetric [data-testid="stMetricDelta"] { font-size: 0.85rem !important; }

.trade-win  { color: #00d4aa; }
.trade-loss { color: #ff4757; }

[data-testid="stDataFrame"] { border: 1px solid #1e1e2e; border-radius: 8px; }
div[data-testid="column"] { padding: 0 0.3rem; }

.section-title {
    font-size: 0.7rem;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: #444;
    margin-bottom: 0.5rem;
    padding-bottom: 0.3rem;
    border-bottom: 1px solid #1a1a2e;
}
.open-trade-card {
    background: #111118;
    border: 1px solid #1e1e2e;
    border-radius: 10px;
    padding: 0.8rem 1rem;
    margin-bottom: 0.5rem;
}
</style>
""", unsafe_allow_html=True)


# ── Funções de dados ──────────────────────────────────────────

@st.cache_data(ttl=60)
def load_closed_trades():
    try:
        if ONLINE_MODE:
            # Modo online — lê CSV do repositório
            df = pd.read_csv(CSV_FILE)
            df["closed_at"] = pd.to_datetime(df["closed_at"], format="ISO8601", utc=True)
            df["opened_at"] = pd.to_datetime(df["opened_at"], format="ISO8601", utc=True)
        else:
            # Modo local — lê directamente da DB
            conn = sqlite3.connect(DB_FILE)
            df = pd.read_sql_query("""
                SELECT id, symbol, signal_type, entry_zone_method,
                       exec_price, exit_price, pnl_pct, pnl_usd,
                       exit_reason, score_pct, opened_at, closed_at,
                       open_fear_greed, open_regime, open_rsi_1h, open_adx_1h
                FROM paper_trades
                WHERE closed_at IS NOT NULL
                ORDER BY closed_at ASC
            """, conn)
            conn.close()
            df["closed_at"] = pd.to_datetime(df["closed_at"], format="ISO8601", utc=True)
            df["opened_at"] = pd.to_datetime(df["opened_at"], format="ISO8601", utc=True)

        df["sym"]     = df["symbol"].str.replace("USDT", "")
        df["win"]     = df["pnl_pct"] > 0
        df["cum_pnl"] = df["pnl_usd"].cumsum()
        df["equity"]  = INITIAL_CAP + df["cum_pnl"]
        return df
    except Exception as e:
        st.error(f"Erro ao carregar trades: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=60)
def load_open_trades():
    if ONLINE_MODE:
        return pd.DataFrame()
    try:
        conn = sqlite3.connect(DB_FILE)
        df = pd.read_sql_query("""
            SELECT id, symbol, signal_type, exec_price, sl, tp1,
                   score_pct, opened_at, position_size_usdt, partial_closed
            FROM paper_trades
            WHERE closed_at IS NULL
            ORDER BY opened_at DESC
        """, conn)
        conn.close()
        df["opened_at"] = pd.to_datetime(df["opened_at"], format="ISO8601", utc=True)
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=60)
def load_pending():
    if ONLINE_MODE:
        return pd.DataFrame()
    try:
        conn = sqlite3.connect(DB_FILE)
        df = pd.read_sql_query("""
            SELECT symbol, signal_type, added_at, expires_at,
                   added_fear_greed, added_regime
            FROM pending_signals
            WHERE status = 'PENDING'
            ORDER BY added_at DESC
        """, conn)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=60)
def load_capital():
    try:
        if ONLINE_MODE:
            # No modo online calcula a partir do CSV
            df = load_closed_trades()
            return INITIAL_CAP + df["pnl_usd"].sum() if not df.empty else INITIAL_CAP
        conn = sqlite3.connect(DB_FILE)
        row = conn.execute(
            "SELECT value FROM bot_state WHERE key='sim_capital'"
        ).fetchone()
        conn.close()
        return float(row[0]) if row else INITIAL_CAP
    except Exception:
        return INITIAL_CAP


@st.cache_data(ttl=60)
def load_rejections_today():
    if ONLINE_MODE:
        return []
    try:
        conn = sqlite3.connect(DB_FILE)
        rows = conn.execute("""
            SELECT reason, COUNT(*) as n
            FROM signal_rejections
            WHERE recorded_at > datetime('now', '-24 hours')
            GROUP BY reason ORDER BY n DESC
        """).fetchall()
        conn.close()
        return rows
    except Exception:
        return []


# ── Header ────────────────────────────────────────────────────

st.markdown("""
<div style="display:flex; align-items:baseline; gap:1rem; margin-bottom:0.2rem;">
  <h1 style="margin:0; font-size:2rem; letter-spacing:-0.02em;">FabrizioEconomics</h1>
  <span style="color:#444; font-size:0.85rem; font-family:'Space Mono',monospace;">paper trading</span>
</div>
""", unsafe_allow_html=True)

now_utc = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
st.markdown(f'<p style="color:#444; font-size:0.8rem; margin-top:0; font-family:\'Space Mono\',monospace;">{now_utc}</p>', unsafe_allow_html=True)

if ONLINE_MODE:
    st.info("📊 Modo público — dados actualizados semanalmente. Trades abertos e pendentes não são mostrados.", icon="ℹ️")

df = load_closed_trades()
capital = load_capital()

# ── KPIs principais ───────────────────────────────────────────
st.markdown("---")

if not df.empty:
    n       = len(df)
    wins    = df["win"].sum()
    losses  = n - wins
    wr      = wins / n * 100
    net_usd = df["pnl_usd"].sum()
    eq_pct  = (capital - INITIAL_CAP) / INITIAL_CAP * 100
    win_sum = df[df["win"]]["pnl_usd"].sum()
    los_sum = abs(df[~df["win"]]["pnl_usd"].sum())
    pf      = round(win_sum / los_sum, 2) if los_sum > 0 else 0
    avg_win = df[df["win"]]["pnl_usd"].mean()
    avg_los = df[~df["win"]]["pnl_usd"].mean()
    expect  = (wr/100 * avg_win) + ((1 - wr/100) * avg_los)

    # Max drawdown
    running_max = df["equity"].cummax()
    dd_series   = (df["equity"] - running_max) / running_max * 100
    max_dd      = dd_series.min()

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Capital", f"${capital:,.2f}", f"{eq_pct:+.2f}%")
    c2.metric("Net P&L", f"${net_usd:+.2f}", f"{n} trades")
    c3.metric("Win Rate", f"{wr:.1f}%", f"{int(wins)}W / {int(losses)}L")
    c4.metric("Profit Factor", f"{pf}", f"Expect: ${expect:+.2f}")
    c5.metric("Max Drawdown", f"{max_dd:.2f}%", "")
    c6.metric("Capital Inicial", f"${INITIAL_CAP:,.0f}", "")
else:
    st.info("Sem trades fechados ainda.")

st.markdown("---")

# ── Layout principal ──────────────────────────────────────────
col_left, col_right = st.columns([3, 2], gap="large")

with col_left:

    # Equity curve
    st.markdown('<p class="section-title">Equity Curve</p>', unsafe_allow_html=True)
    if not df.empty:
        fig_eq = go.Figure()
        fig_eq.add_trace(go.Scatter(
            x=df["closed_at"],
            y=df["equity"],
            mode="lines",
            line=dict(color="#00d4aa", width=2.5),
            fill="tozeroy",
            fillcolor="rgba(0, 212, 170, 0.06)",
            name="Equity",
            hovertemplate="<b>%{x|%d/%m %H:%M}</b><br>$%{y:,.2f}<extra></extra>",
        ))
        fig_eq.add_hline(
            y=INITIAL_CAP,
            line_dash="dot",
            line_color="#333",
            annotation_text=f"Inicial ${INITIAL_CAP:,.0f}",
            annotation_font_color="#444",
        )
        fig_eq.update_layout(
            plot_bgcolor="#0a0a0f",
            paper_bgcolor="#0a0a0f",
            font_color="#888",
            margin=dict(l=0, r=0, t=10, b=0),
            height=220,
            showlegend=False,
            xaxis=dict(showgrid=False, zeroline=False, tickfont_color="#444"),
            yaxis=dict(showgrid=True, gridcolor="#111118", zeroline=False,
                       tickformat="$,.0f", tickfont_color="#444"),
        )
        st.plotly_chart(fig_eq, use_container_width=True)

    # Trades fechados
    st.markdown('<p class="section-title">Trades Fechados</p>', unsafe_allow_html=True)
    if not df.empty:
        df_show = df.sort_values("closed_at", ascending=False).copy()
        df_show["Data"] = df_show["closed_at"].dt.strftime("%d/%m %H:%M")
        df_show["Par"]  = df_show["sym"]
        df_show["Tipo"] = df_show["signal_type"].str.replace("_FUTURES", "F").str.replace("_SPOT", "S")
        df_show["Método"] = df_show["entry_zone_method"]
        df_show["Score"]  = df_show["score_pct"].apply(lambda x: f"{x:.0f}%" if x else "—")
        df_show["PnL %"]  = df_show["pnl_pct"].apply(lambda x: f"{x:+.2f}%" if x else "—")
        df_show["PnL $"]  = df_show["pnl_usd"].apply(lambda x: f"${x:+.2f}" if x else "—")
        df_show["Saída"]  = df_show["exit_reason"].map({
            "tp1_hit": "✅ TP1", "tp2_hit": "🎯 TP2",
            "stop_loss": "🔴 SL", "sl_hit": "🔴 SL",
        }).fillna(df_show["exit_reason"])
        df_show["F&G"]  = df_show["open_fear_greed"].apply(lambda x: str(int(x)) if pd.notna(x) else "—")

        st.dataframe(
            df_show[["Data", "Par", "Tipo", "Método", "Score", "PnL %", "PnL $", "Saída", "F&G"]],
            use_container_width=True,
            hide_index=True,
            height=320,
        )


with col_right:

    # Trades abertos
    open_df = load_open_trades()
    st.markdown(f'<p class="section-title">Abertos ({len(open_df)})</p>', unsafe_allow_html=True)

    if not open_df.empty:
        now = pd.Timestamp.now(tz="UTC")
        for _, t in open_df.iterrows():
            sym   = t["symbol"].replace("USDT", "")
            stype = t["signal_type"].replace("_FUTURES", " F").replace("_SPOT", " S")
            dur   = now - t["opened_at"]
            dur_h = int(dur.total_seconds() // 3600)
            dur_m = int((dur.total_seconds() % 3600) // 60)
            tag   = "partial" if t.get("partial_closed") else ""
            st.markdown(f"""
            <div class="open-trade-card">
              <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="font-weight:700; font-size:1rem;">{sym}</span>
                <span style="color:#444; font-size:0.75rem; font-family:'Space Mono',monospace;">{dur_h}h {dur_m}min</span>
              </div>
              <div style="color:#666; font-size:0.8rem;">{stype} · score {t['score_pct']:.0f}%{' · '+tag if tag else ''}</div>
              <div style="font-family:'Space Mono',monospace; font-size:0.8rem; margin-top:0.4rem; color:#888;">
                Entry: ${t['exec_price']:,.4f} · SL: ${t['sl']:,.4f}
              </div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.markdown('<p style="color:#444; font-size:0.85rem;">Sem trades abertos.</p>', unsafe_allow_html=True)

    # Pendentes
    pend_df = load_pending()
    st.markdown(f'<p class="section-title" style="margin-top:1rem;">Pendentes ({len(pend_df)})</p>', unsafe_allow_html=True)
    if not pend_df.empty:
        now = pd.Timestamp.now(tz="UTC")
        for _, p in pend_df.iterrows():
            sym   = p["symbol"].replace("USDT", "")
            stype = p["signal_type"].replace("_FUTURES", " F").replace("_SPOT", " S")
            try:
                exp   = pd.to_datetime(p["expires_at"], utc=True)
                rem_m = max(0, int((exp - now).total_seconds() / 60))
                rem_s = f"{rem_m}min"
            except Exception:
                rem_s = "?"
            st.markdown(f"""
            <div style="display:flex; justify-content:space-between; padding:0.4rem 0;
                        border-bottom:1px solid #111118; font-size:0.82rem;">
              <span><b>{sym}</b> <span style="color:#555;">{stype}</span></span>
              <span style="color:#444; font-family:'Space Mono',monospace;">{rem_s}</span>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.markdown('<p style="color:#444; font-size:0.85rem;">Sem sinais pendentes.</p>', unsafe_allow_html=True)

    # Rejeições hoje
    rejections = load_rejections_today()
    if rejections:
        total_rej = sum(r[1] for r in rejections)
        st.markdown(f'<p class="section-title" style="margin-top:1rem;">Rejeições 24h ({total_rej})</p>', unsafe_allow_html=True)
        for reason, n in rejections[:4]:
            pct = round(n / total_rej * 100)
            st.markdown(f"""
            <div style="display:flex; justify-content:space-between; align-items:center;
                        padding:0.3rem 0; border-bottom:1px solid #111118; font-size:0.8rem;">
              <span style="color:#888;">{reason}</span>
              <span style="font-family:'Space Mono',monospace; color:#555;">{n} <span style="color:#333;">({pct}%)</span></span>
            </div>
            """, unsafe_allow_html=True)

st.markdown("---")

# ── Análise por símbolo e método ─────────────────────────────
if not df.empty:
    col_a, col_b, col_c = st.columns(3, gap="large")

    with col_a:
        st.markdown('<p class="section-title">Por Símbolo</p>', unsafe_allow_html=True)
        sym_stats = df.groupby("sym").agg(
            n=("pnl_usd", "count"),
            wins=("win", "sum"),
            net=("pnl_usd", "sum"),
        ).reset_index()
        sym_stats["WR"] = (sym_stats["wins"] / sym_stats["n"] * 100).round(1)

        colors = ["#00d4aa" if v >= 0 else "#ff4757" for v in sym_stats["net"]]
        fig_sym = go.Figure(go.Bar(
            x=sym_stats["sym"],
            y=sym_stats["net"],
            marker_color=colors,
            text=[f"${v:+.0f}" for v in sym_stats["net"]],
            textposition="outside",
            textfont=dict(color="#888", size=11, family="Space Mono"),
            hovertemplate="<b>%{x}</b><br>Net: $%{y:+.2f}<br>WR: %{customdata}%<extra></extra>",
            customdata=sym_stats["WR"],
        ))
        fig_sym.update_layout(
            plot_bgcolor="#0a0a0f", paper_bgcolor="#0a0a0f",
            margin=dict(l=0, r=0, t=20, b=0), height=200,
            showlegend=False,
            xaxis=dict(showgrid=False, tickfont_color="#666"),
            yaxis=dict(showgrid=True, gridcolor="#111118", tickformat="$,.0f",
                       tickfont_color="#444", zeroline=True, zerolinecolor="#222"),
        )
        st.plotly_chart(fig_sym, use_container_width=True)

    with col_b:
        st.markdown('<p class="section-title">Por Método de Entrada</p>', unsafe_allow_html=True)
        met_stats = df.groupby("entry_zone_method").agg(
            n=("pnl_usd", "count"),
            wins=("win", "sum"),
            net=("pnl_usd", "sum"),
        ).reset_index()
        met_stats["WR"] = (met_stats["wins"] / met_stats["n"] * 100).round(1)
        met_stats["label"] = met_stats["entry_zone_method"].str.replace("bos_retest_", "bos_").str.replace("fibonacci_", "fib_")

        colors_m = ["#00d4aa" if v >= 0 else "#ff4757" for v in met_stats["net"]]
        fig_met = go.Figure(go.Bar(
            x=met_stats["label"],
            y=met_stats["net"],
            marker_color=colors_m,
            text=[f"WR {wr:.0f}%" for wr in met_stats["WR"]],
            textposition="outside",
            textfont=dict(color="#888", size=10, family="Space Mono"),
            hovertemplate="<b>%{x}</b><br>Net: $%{y:+.2f}<br>WR: %{customdata}%<extra></extra>",
            customdata=met_stats["WR"],
        ))
        fig_met.update_layout(
            plot_bgcolor="#0a0a0f", paper_bgcolor="#0a0a0f",
            margin=dict(l=0, r=0, t=20, b=0), height=200,
            showlegend=False,
            xaxis=dict(showgrid=False, tickfont_color="#666", tickangle=-15),
            yaxis=dict(showgrid=True, gridcolor="#111118", tickformat="$,.0f",
                       tickfont_color="#444", zeroline=True, zerolinecolor="#222"),
        )
        st.plotly_chart(fig_met, use_container_width=True)

    with col_c:
        st.markdown('<p class="section-title">Por Fear & Greed</p>', unsafe_allow_html=True)
        df_fg = df[df["open_fear_greed"].notna()].copy()
        if not df_fg.empty:
            df_fg["fg_bucket"] = pd.cut(
                df_fg["open_fear_greed"],
                bins=[0, 15, 25, 45, 75, 100],
                labels=["<15\nExtreme Fear", "15-25\nFear", "25-45\nNormal", "45-75\nGreed", ">75\nExt.Greed"],
            )
            fg_stats = df_fg.groupby("fg_bucket", observed=True).agg(
                n=("pnl_usd", "count"),
                wins=("win", "sum"),
            ).reset_index()
            fg_stats["WR"] = (fg_stats["wins"] / fg_stats["n"] * 100).round(1)

            colors_fg = ["#00d4aa" if wr >= 60 else ("#f0a500" if wr >= 45 else "#ff4757")
                         for wr in fg_stats["WR"]]
            fig_fg = go.Figure(go.Bar(
                x=fg_stats["fg_bucket"].astype(str),
                y=fg_stats["WR"],
                marker_color=colors_fg,
                text=[f"{wr:.0f}%" for wr in fg_stats["WR"]],
                textposition="outside",
                textfont=dict(color="#888", size=11, family="Space Mono"),
                hovertemplate="<b>%{x}</b><br>WR: %{y:.1f}%<br>N: %{customdata}<extra></extra>",
                customdata=fg_stats["n"],
            ))
            fig_fg.update_layout(
                plot_bgcolor="#0a0a0f", paper_bgcolor="#0a0a0f",
                margin=dict(l=0, r=0, t=20, b=0), height=200,
                showlegend=False,
                xaxis=dict(showgrid=False, tickfont_color="#666", tickfont_size=9),
                yaxis=dict(showgrid=True, gridcolor="#111118", ticksuffix="%",
                           tickfont_color="#444", range=[0, 110]),
            )
            st.plotly_chart(fig_fg, use_container_width=True)
        else:
            st.markdown('<p style="color:#444;">Sem dados de F&G.</p>', unsafe_allow_html=True)

# ── Footer ────────────────────────────────────────────────────
st.markdown("""
<div style="text-align:center; color:#222; font-size:0.7rem;
            font-family:'Space Mono',monospace; margin-top:2rem; padding-top:1rem;
            border-top:1px solid #111118;">
  FabrizioEconomics · Paper Trading
</div>
""", unsafe_allow_html=True)
