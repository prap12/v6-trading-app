import streamlit as st
import pandas as pd
import sqlite3
import requests

st.set_page_config(page_title="V8 Institutional Engine", layout="centered")

# ================= DB =================
conn = sqlite3.connect("trading.db", check_same_thread=False)
c = conn.cursor()

c.execute("""
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY,
    stock TEXT,
    sector TEXT,
    setup TEXT,
    entry REAL,
    exit REAL,
    qty INTEGER,
    pnl REAL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")
conn.commit()

# ================= TELEGRAM =================
def send_telegram(msg):
    TOKEN = "YOUR_TOKEN"
    CHAT_ID = "YOUR_CHAT_ID"
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

# ================= SETUP CLASSIFICATION =================
def get_setup(row):
    if abs(row['Price'] - row['EMA20']) / row['EMA20'] < 0.02:
        return "Pullback"
    elif row['RSI'] > 60:
        return "Breakout"
    else:
        return "Momentum"

# ================= UI =================
st.title("📊 V8 Institutional Trading Engine")

capital = st.number_input("Capital ₹", value=100000)

uploaded_file = st.file_uploader("Upload CSV", type=["csv"])

required_cols = [
    "Stock","Price","EMA20","EMA50","EMA200",
    "RSI","ADX","MACD","Signal","Sector","Volume","ATR"
]

if uploaded_file:

    df = pd.read_csv(uploaded_file)

    # ===== VALIDATION =====
    if any(col not in df.columns for col in required_cols):
        st.error("Invalid CSV format")
        st.stop()

    # ===== CORE LOGIC =====
    df['trend'] = ((df['Price'] > df['EMA200']) &
                   (df['EMA20'] > df['EMA50'])).astype(int)

    df['momentum'] = ((df['RSI'] > 50) &
                      (df['RSI'] < 65) &
                      (df['ADX'] > 20)).astype(int)

    df['trigger'] = (df['MACD'] > df['Signal']).astype(int)

    df['base_score'] = df[['trend','momentum','trigger']].sum(axis=1)

    # ===== SECTOR =====
    sector_strength = df.groupby('Sector')['RSI'].mean().sort_values(ascending=False)
    top_sectors = sector_strength.head(2).index.tolist()

    df['sector_flag'] = df['Sector'].isin(top_sectors).astype(int)
    df['final_score'] = df['base_score'] * 20 + df['sector_flag'] * 20

    # ===== SETUP =====
    df['setup'] = df.apply(get_setup, axis=1)

    # ===== TRADE CALC =====
    df['SL'] = df['Price'] - (1.5 * df['ATR'])
    df['Target'] = df['Price'] + 2 * (df['Price'] - df['SL'])
    df['Risk'] = df['Price'] - df['SL']

    # ===== CONFIDENCE =====
    df['confidence'] = df['final_score']

    def risk_pct(conf):
        if conf >= 80: return 0.02
        elif conf >= 65: return 0.015
        else: return 0.01

    df['risk_pct'] = df['confidence'].apply(risk_pct)
    df['risk_amt'] = capital * df['risk_pct']
    df['Qty'] = df['risk_amt'] / df['Risk']

    df = df.sort_values(by='confidence', ascending=False)

    # ===== PORTFOLIO FILTER =====
    max_portfolio_risk = 0.05
    max_sector_exposure = 0.3

    selected = []
    total_risk = 0
    sector_alloc = {}
    sector_count = {}

    for _, row in df.iterrows():

        risk = row['risk_amt']
        sec = row['Sector']

        if total_risk + risk > capital * max_portfolio_risk:
            continue

        if sector_alloc.get(sec, 0) + risk > capital * max_sector_exposure:
            continue

        if sector_count.get(sec, 0) >= 2:
            continue

        selected.append(row)
        total_risk += risk
        sector_alloc[sec] = sector_alloc.get(sec, 0) + risk
        sector_count[sec] = sector_count.get(sec, 0) + 1

    final_df = pd.DataFrame(selected)

    # ===== DISPLAY =====
    st.subheader("🚀 Final Portfolio")

    for i, row in final_df.iterrows():
        st.markdown(f"""
        **{row['Stock']}** | {row['Sector']}  
        Conf: {row['confidence']}  

        Entry: ₹{round(row['Price'],2)}  
        SL: ₹{round(row['SL'],2)}  
        Target: ₹{round(row['Target'],2)}  

        Qty: {int(row['Qty'])}
        """)

        if st.button(f"Add Trade {i}"):
            c.execute("""
            INSERT INTO trades (stock, sector, setup, entry, qty, pnl)
            VALUES (?, ?, ?, ?, ?, 0)
            """, (row['Stock'], row['Sector'], row['setup'], row['Price'], int(row['Qty'])))
            conn.commit()

    # ===== JOURNAL =====
    journal = pd.read_sql("SELECT * FROM trades", conn)

    if not journal.empty:
        journal['pnl'] = journal['pnl'].fillna(0)
        journal['equity'] = journal['pnl'].cumsum()
        journal['peak'] = journal['equity'].cummax()
        journal['drawdown'] = journal['equity'] - journal['peak']

        st.subheader("📈 Equity Curve")
        st.line_chart(journal['equity'])

        st.subheader("📉 Drawdown")
        st.line_chart(journal['drawdown'])

        # ===== ANALYTICS =====
        st.subheader("📊 Performance")

        wins = journal[journal['pnl'] > 0]
        losses = journal[journal['pnl'] <= 0]

        win_rate = len(wins) / len(journal) if len(journal) else 0

        st.write(f"Win Rate: {round(win_rate*100,2)}%")
        st.write(f"Total PnL: ₹{round(journal['pnl'].sum(),2)}")

        # ===== REPORT =====
        if st.button("Send Daily Report"):

            msg = f"📊 Daily Report\nRisk Used: {round(total_risk,2)}\n\n"

            for _, r in final_df.iterrows():
                msg += f"{r['Stock']} | {r['confidence']}\n"

            send_telegram(msg)

else:
    st.info("Upload CSV to begin")
