import streamlit as st
import pandas as pd
import sqlite3
import requests

st.set_page_config(page_title="V10 Trading Engine", layout="centered")

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
    result TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")
conn.commit()

# ================= TELEGRAM =================
def send_telegram(msg):
    TOKEN = "YOUR_TOKEN"
    CHAT_ID = "YOUR_CHAT_ID"
    if TOKEN != "YOUR_TOKEN":
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

# ================= SETUP =================
def get_setup(row):
    try:
        if abs(row['Price'] - row['EMA20']) / row['EMA20'] < 0.02:
            return "Pullback"
        elif row['RSI'] > 60:
            return "Breakout"
        else:
            return "Momentum"
    except:
        return "Unknown"

# ================= UI =================
st.title("📊 V10 Institutional Trading Engine")

capital = st.number_input("Capital ₹", value=100000)
uploaded_file = st.file_uploader("Upload CSV", type=["csv"])

required_cols = [
    "Stock","Price","EMA20","EMA50","EMA200",
    "RSI","ADX","MACD","Signal","Sector","Volume","ATR"
]

if uploaded_file:

    # ===== LOAD =====
    df = pd.read_csv(uploaded_file)
    df.columns = df.columns.str.strip()
    df = df.loc[:, ~df.columns.duplicated()]

    # ===== NORMALIZE =====
    def normalize(col):
        return col.lower().replace(" ", "").replace("(", "").replace(")", "").replace("_", "")

    col_map = {}
    for col in df.columns:
        n = normalize(col)

        if "stock" in n or "symbol" in n:
            col_map[col] = "Stock"
        elif "close" in n or "price" in n:
            col_map[col] = "Price"
        elif "rsi" in n:
            col_map[col] = "RSI"
        elif "adx" in n:
            col_map[col] = "ADX"
        elif "macd" in n and "signal" not in n:
            col_map[col] = "MACD"
        elif "signal" in n:
            col_map[col] = "Signal"
        elif "volume" in n:
            col_map[col] = "Volume"
        elif "atr" in n or "avgtruerange" in n:
            col_map[col] = "ATR"
        elif "sector" in n:
            col_map[col] = "Sector"

    df = df.rename(columns=col_map)

    # ===== EMA FIX =====
    ema_cols = [col for col in df.columns if "ema" in col.lower()]
    if len(ema_cols) >= 3:
        df = df.rename(columns={
            ema_cols[0]: "EMA20",
            ema_cols[1]: "EMA50",
            ema_cols[2]: "EMA200"
        })

    # ===== VALIDATE =====
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        st.error(f"Missing columns: {missing}")
        st.stop()

    # ===== NUMERIC FIX =====
    numeric_cols = ["Price","EMA20","EMA50","EMA200","RSI","ADX","MACD","Signal","Volume","ATR"]
    for col in numeric_cols:
        df[col] = df[col].astype(str).str.replace(",", "").str.strip()
        df[col] = pd.to_numeric(df[col], errors='coerce')

    df = df.dropna(subset=["Price","EMA20","EMA50","EMA200","RSI","ADX"])

    # ===== LOGIC =====
    df['trend'] = ((df['Price'] > df['EMA200']) & (df['EMA20'] > df['EMA50'])).astype(int)
    df['momentum'] = ((df['RSI'] > 50) & (df['RSI'] < 65) & (df['ADX'] > 20)).astype(int)
    df['trigger'] = (df['MACD'] > df['Signal']).astype(int)

    df['base_score'] = df[['trend','momentum','trigger']].sum(axis=1)

    sector_strength = df.groupby('Sector')['RSI'].mean().sort_values(ascending=False)
    top_sectors = sector_strength.head(2).index.tolist()

    df['sector_flag'] = df['Sector'].isin(top_sectors).astype(int)
    df['confidence'] = df['base_score'] * 20 + df['sector_flag'] * 20

    df['setup'] = df.apply(get_setup, axis=1)

    # ===== TRADE CALC =====
    df['SL'] = df['Price'] - (1.5 * df['ATR'])
    df['Target'] = df['Price'] + 2 * (df['Price'] - df['SL'])
    df['Risk'] = df['Price'] - df['SL']

    df = df[df['Risk'] > 0]

    df['RR'] = (df['Target'] - df['Price']) / df['Risk']

    def risk_pct(c):
        if c >= 80: return 0.02
        elif c >= 65: return 0.015
        else: return 0.01

    df['risk_amt'] = capital * df['confidence'].apply(risk_pct)
    df['Qty'] = df['risk_amt'] / df['Risk']

    df = df.sort_values(by=['confidence','RR'], ascending=False)

    # ===== BEST TRADE =====
    st.subheader("🏆 Best Trade")
    best = df.iloc[0]
    st.success(f"{best['Stock']} | RR {round(best['RR'],2)} | Score {best['confidence']}")

    # ===== TOP TRADES =====
    st.subheader("🚀 Top Trades")

    for i, row in df.head(3).iterrows():
        st.markdown(f"""
        **{row['Stock']} ({row['Sector']})**  
        Entry ₹{round(row['Price'],2)} | SL ₹{round(row['SL'],2)}  
        Target ₹{round(row['Target'],2)} | Qty {int(row['Qty'])}  
        RR {round(row['RR'],2)} | Score {row['confidence']}
        """)

        if st.button(f"Add Trade {i}"):
            c.execute("""
            INSERT INTO trades (stock, sector, setup, entry, qty, pnl)
            VALUES (?, ?, ?, ?, ?, 0)
            """, (row['Stock'], row['Sector'], row['setup'], row['Price'], int(row['Qty'])))
            conn.commit()

    # ===== TRADE UPDATE =====
    st.subheader("📌 Update Trade")

    journal = pd.read_sql("SELECT * FROM trades", conn)

    if not journal.empty:

        trade_id = st.selectbox("Select Trade", journal['id'])

        exit_price = st.number_input("Exit Price", value=0.0)
        result = st.selectbox("Result", ["Win", "Loss"])

        if st.button("Update Trade"):
            trade = journal[journal['id']==trade_id].iloc[0]
            pnl = (exit_price - trade['entry']) * trade['qty']

            c.execute("""
            UPDATE trades SET exit=?, pnl=?, result=? WHERE id=?
            """, (exit_price, pnl, result, trade_id))
            conn.commit()

            st.success("Updated")

    # ===== PERFORMANCE =====
    st.subheader("📊 Performance")

    completed = journal.dropna(subset=['result'])

    if not completed.empty:

        wins = completed[completed['result']=="Win"]
        losses = completed[completed['result']=="Loss"]

        win_rate = len(wins)/len(completed)

        avg_win = wins['pnl'].mean() if not wins.empty else 0
        avg_loss = losses['pnl'].mean() if not losses.empty else 0

        expectancy = (win_rate * avg_win) + ((1-win_rate) * avg_loss)

        st.write(f"Win Rate: {round(win_rate*100,2)}%")
        st.write(f"Avg Win: ₹{round(avg_win,2)}")
        st.write(f"Avg Loss: ₹{round(avg_loss,2)}")
        st.write(f"Expectancy: ₹{round(expectancy,2)}")

        # ===== SETUP PERFORMANCE =====
        st.subheader("🧠 Setup Performance")
        st.dataframe(completed.groupby('setup')['pnl'].mean())

        # ===== SECTOR PERFORMANCE =====
        st.subheader("🌍 Sector Performance")
        st.dataframe(completed.groupby('sector')['pnl'].mean())

else:
    st.info("Upload CSV to start")
