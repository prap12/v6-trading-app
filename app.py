import streamlit as st
import pandas as pd

st.set_page_config(page_title="V6 Pro Engine", layout="centered")

st.title("📊 V6 Pro Trading Engine")

uploaded_file = st.file_uploader("Upload CSV", type=["csv"])

required_cols = [
    "Stock","Price","EMA20","EMA50","EMA200",
        "RSI","ADX","MACD","Signal","Sector","Volume","ATR"
        ]

        if uploaded_file:

            df = pd.read_csv(uploaded_file)

                missing = [c for c in required_cols if c not in df.columns]

                    if missing:
                            st.error(f"Missing: {missing}")
                                    st.stop()

                                        # ===== CORE =====
                                            df['trend'] = ((df['Price'] > df['EMA200']) &
                                                               (df['EMA20'] > df['EMA50'])).astype(int)

                                                                   df['momentum'] = ((df['RSI'] > 50) &
                                                                                         (df['RSI'] < 65) &
                                                                                                               (df['ADX'] > 20)).astype(int)

                                                                                                                   df['trigger'] = (df['MACD'] > df['Signal']).astype(int)

                                                                                                                       df['base_score'] = df[['trend','momentum','trigger']].sum(axis=1)

                                                                                                                           # Sector strength
                                                                                                                               sector_strength = df.groupby('Sector')['RSI'].mean().sort_values(ascending=False)
                                                                                                                                   top_sectors = sector_strength.head(2).index.tolist()

                                                                                                                                       df['sector_flag'] = df['Sector'].isin(top_sectors).astype(int)

                                                                                                                                           df['final_score'] = df['base_score'] * 20 + df['sector_flag'] * 20

                                                                                                                                               df = df[(df['final_score'] >= 60) & (df['sector_flag'] == 1)]
                                                                                                                                                   df = df.sort_values(by='final_score', ascending=False)

                                                                                                                                                       # ===== TRADE METRICS =====
                                                                                                                                                           capital = st.number_input("Capital (₹)", value=100000)

                                                                                                                                                               df['SL'] = df['Price'] - (1.5 * df['ATR'])
                                                                                                                                                                   df['Target'] = df['Price'] + 2 * (df['Price'] - df['SL'])
                                                                                                                                                                       df['Risk'] = df['Price'] - df['SL']
                                                                                                                                                                           df['Qty'] = (capital * 0.01) / df['Risk']

                                                                                                                                                                               # ===== UI =====

                                                                                                                                                                                   st.subheader("🔥 Top Sectors")
                                                                                                                                                                                       for s, v in sector_strength.head(3).items():
                                                                                                                                                                                               st.write(f"{s}: {round(v,1)}")

                                                                                                                                                                                                   st.divider()

                                                                                                                                                                                                       st.subheader("🚀 Top Picks")

                                                                                                                                                                                                           for _, row in df.head(5).iterrows():
                                                                                                                                                                                                                   st.markdown(f"""
                                                                                                                                                                                                                           ### {row['Stock']}
                                                                                                                                                                                                                                   Sector: {row['Sector']} | Score: {row['final_score']}

                                                                                                                                                                                                                                           Entry: ₹{round(row['Price'],2)}
                                                                                                                                                                                                                                                   SL: ₹{round(row['SL'],2)}
                                                                                                                                                                                                                                                           Target: ₹{round(row['Target'],2)}

                                                                                                                                                                                                                                                                   Qty: {int(row['Qty'])}
                                                                                                                                                                                                                                                                           """)
                                                                                                                                                                                                                                                                                   st.divider()

                                                                                                                                                                                                                                                                                   else:
                                                                                                                                                                                                                                                                                       st.info("Upload CSV to start")