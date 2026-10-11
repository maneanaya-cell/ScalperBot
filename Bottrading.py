import os
import ccxt
import pandas as pd
import numpy as np

def calcular_rsi(series, periodo=14):
    delta = series.diff()
    ganancia = (delta.where(delta > 0, 0)).rolling(window=periodo).mean()
    perdida = (-delta.where(delta < 0, 0)).rolling(window=periodo).mean()
    rs = ganancia / perdida
    return 100 - (100 / (1 + rs))

def calcular_atr(df, periodo=200):
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    return true_range.rolling(window=periodo).mean()

def run_bot():
    try:
        # 1. Credenciales y Conexión Real
        api_key = os.getenv('BINGX_API_KEY')
        secret_key = os.getenv('BINGX_SECRET_KEY')

        if not api_key or not secret_key:
            print("❌ Error: No se encontraron las credenciales en las variables de entorno.")
            return

        exchange = ccxt.bingx({
            'apiKey': api_key,
            'secret': secret_key,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'swap',  # Futuros perpetuos
            }
        })

        exchange.load_markets()
        print("✅ Conexión establecida con la cuenta de BingX.")

        # 2. Consultar balance real
        balance = exchange.fetch_balance()
        usdt_free = balance['USDT']['free'] if 'USDT' in balance else 0
        print(f"💰 Balance disponible en USDT (Real): {usdt_free}")

        # 3. Símbolo y Temporalidad
        simbolo = 'BTC/USDT:USDT'
        timeframe = '15m'
        
        print(f"📊 Analizando el mercado para {simbolo} en temporalidad {timeframe}...")
        
        ohlcv = exchange.fetch_ohlcv(simbolo, timeframe=timeframe, limit=250)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # 4. Indicadores Técnicos
        df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
        df['RSI'] = calcular_rsi(df['close'], periodo=14)
        
        length = 130
        atr = calcular_atr(df, periodo=200)
        rolling_max = df['high'].rolling(window=length).max()
        rolling_min = df['low'].rolling(window=length).min()
        
        df['SR_Top'] = rolling_max + (atr * 0.5)
        df['SR_Bot'] = rolling_min - (atr * 0.5)
        
        precio_actual = df['close'].iloc[-1]
        ema9_actual = df['EMA_9'].iloc[-1]
        ema21_actual = df['EMA_21'].iloc[-1]
        rsi_actual = df['RSI'].iloc[-1]
        sr_top_actual = df['SR_Top'].iloc[-1]
        sr_bot_actual = df['SR_Bot'].iloc[-1]

        print(f"📈 Precio Actual: {precio_actual}")
        print(f"📈 EMA 9: {ema9_actual:.2f} | EMA 21: {ema21_actual:.2f}")
        print(f"📈 RSI (14): {rsi_actual:.2f}")
        print(f"📊 Canal S&R -> Soporte: {sr_bot_actual:.2f} | Resistencia: {sr_top_actual:.2f}")

        # Definir el monto en USD que deseas arriesgar por operación (ej. 0.10 USDT)
        inversion_usd = 0.10 
        
        # Calcular los BTC necesarios en función del precio actual y redondeando a 4 decimales
        cantidad_btc = round(inversion_usd / precio_actual, 4)
        if cantidad_btc < 0.0001:
            cantidad_btc = 0.0001 # Aseguramos el mínimo aceptado

        print(f"⚙️ Monto calculado para la orden: {cantidad_btc} BTC (aprox. {inversion_usd} USDT)")

        # 5. Lógica de Estrategia y Ejecución Real
        if precio_actual <= (sr_bot_actual * 1.003) or (ema9_actual > ema21_actual and rsi_actual < 65):
            print("🟢 Señal de COMPRA detectada...")
            if usdt_free >= 0.05:
                orden = exchange.create_market_buy_order(simbolo, cantidad_btc)
                print(f"✅ ¡Orden de COMPRA ejecutada con éxito! ID: {orden['id']}")
            else:
                print("⚠️ Balance insuficiente para operar.")

        elif precio_actual >= (sr_top_actual * 0.997) or (ema9_actual < ema21_actual and rsi_actual > 35):
            print("🔴 Señal de VENTA detectada...")
            if usdt_free >= 0.05:
                orden = exchange.create_market_sell_order(simbolo, cantidad_btc)
                print(f"✅ ¡Orden de VENTA ejecutada con éxito! ID: {orden['id']}")
            else:
                print("⚠️ Balance insuficiente para operar.")
        else:
            print("⏳ Sin señales de ejecución en este ciclo.")

    except Exception as e:
        print(f"⚠️ Error al operar: {e}")

if __name__ == "__main__":
    run_bot()
