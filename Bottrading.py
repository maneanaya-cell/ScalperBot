import os
import ccxt
import pandas as pd
import numpy as np

def calcular_rsi(series, periodo=14):
    """Calcula el indicador RSI usando pandas."""
    delta = series.diff()
    ganancia = (delta.where(delta > 0, 0)).rolling(window=periodo).mean()
    perdida = (-delta.where(delta < 0, 0)).rolling(window=periodo).mean()
    rs = ganancia / perdida
    return 100 - (100 / (1 + rs))

def calcular_atr(df, periodo=200):
    """Calcula el Average True Range (ATR) para las bandas del canal."""
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    return true_range.rolling(window=periodo).mean()

def run_bot():
    try:
        # 1. Credenciales y Conexión
        api_key = os.getenv('BINGX_API_KEY')
        secret_key = os.getenv('BINGX_SECRET_KEY')

        if not api_key or not secret_key:
            print("❌ Error: No se encontraron las credenciales de BingX en las variables de entorno.")
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
        print("✅ Conexión exitosa con BingX y mercados cargados.")

        # 2. Consultar balance
        balance = exchange.fetch_balance()
        usdt_free = balance['USDT']['free'] if 'USDT' in balance else 0
        print(f"💰 Balance disponible en USDT: {usdt_free}")

        # 3. Símbolo y Temporalidad
        simbolo = 'BTC/USDT:USDT'
        timeframe = '15m'
        
        print(f"📊 Analizando el mercado para {simbolo} en temporalidad {timeframe}...")
        
        # Obtenemos suficientes velas para el cálculo del canal (mínimo 250 para el ATR y length)
        ohlcv = exchange.fetch_ohlcv(simbolo, timeframe=timeframe, limit=250)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # 4. Calcular Indicadores Técnicos
        df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
        df['RSI'] = calcular_rsi(df['close'], periodo=14)
        
        # Traducción del Canal S&R Power (ChartPrime)
        length = 130
        atr = calcular_atr(df, periodo=200)
        
        rolling_max = df['high'].rolling(window=length).max()
        rolling_min = df['low'].rolling(window=length).min()
        
        df['SR_Top'] = rolling_max + (atr * 0.5)  # Banda Superior (Resistencia)
        df['SR_Bot'] = rolling_min - (atr * 0.5)  # Banda Inferior (Soporte)
        
        # Obtener valores actuales de la última vela
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

        # 5. Estrategia combinada (Canal S&R + EMAs + RSI)
        # Compra si el precio está cerca de la zona de soporte inferior o hay cruce alcista con RSI saludable
        if precio_actual <= (sr_bot_actual * 1.003) or (ema9_actual > ema21_actual and rsi_actual < 65):
            print("🟢 Señal potencial de COMPRA detectada (Rebote en Soporte / Tendencia alcista).")
            # Aquí puedes añadir la orden real en el futuro: exchange.create_market_buy_order(...)
            
        # Venta si el precio está cerca de la resistencia superior o cruce bajista
        elif precio_actual >= (sr_top_actual * 0.997) or (ema9_actual < ema21_actual and rsi_actual > 35):
            print("🔴 Señal potencial de VENTA detectada (Cerca de Resistencia / Tendencia bajista).")
            # Aquí puedes añadir la orden real en el futuro: exchange.create_market_sell_order(...)
            
        else:
            print("⏳ Precio oscilando dentro del canal. Sin señales de ruptura o rebote claro.")

    except Exception as e:
        print(f"⚠️ Ocurrió un error al ejecutar el bot: {e}")

if __name__ == "__main__":
    run_bot()
