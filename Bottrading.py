import os
import ccxt
import pandas as pd

def calcular_rsi(series, periodo=14):
    """Calcula el indicador RSI usando pandas."""
    delta = series.diff()
    ganancia = (delta.where(delta > 0, 0)).rolling(window=periodo).mean()
    perdida = (-delta.where(delta < 0, 0)).rolling(window=periodo).mean()
    rs = ganancia / perdida
    return 100 - (100 / (1 + rs))

def run_bot():
    try:
        # 1. Credenciales y Conexión
        api_key = os.getenv('BINGX_API_KEY')
        secret_key = os.getenv('BINGX_SECRET_KEY')

        if not api_key or not secret_key:
            print("❌ Error: No se encontraron las credenciales de BingX en las variables de entorno.")
            return

        # Inicializamos BingX (enfocado en futuros por defecto o spot según configuración)
        exchange = ccxt.bingx({
            'apiKey': api_key,
            'secret': secret_key,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'swap',  # 'swap' para futuros perpetuos
            }
        })

        exchange.load_markets()
        print("✅ Conexión exitosa con BingX y mercados cargados.")

        # 2. Consultar balance
        balance = exchange.fetch_balance()
        usdt_free = balance['USDT']['free'] if 'USDT' in balance else 0
        print(f"💰 Balance disponible en USDT: {usdt_free}")

        # 3. Definir símbolo y temporalidad para el análisis
        simbolo = 'BTC/USDT:USDT'
        timeframe = '15m'
        
        print(f"📊 Analizando el mercado para {simbolo} en temporalidad {timeframe}...")
        
        # Obtener velas (OHLCV: timestamp, open, high, low, close, volume)
        ohlcv = exchange.fetch_ohlcv(simbolo, timeframe=timeframe, limit=100)
        
        # Convertir a DataFrame de Pandas para análisis técnico
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Calcular Indicadores (EMA y RSI)
        df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
        df['RSI'] = calcular_rsi(df['close'], periodo=14)
        
        # Obtener los valores más recientes de la última vela cerrada
        precio_actual = df['close'].iloc[-1]
        ema9_actual = df['EMA_9'].iloc[-1]
        ema21_actual = df['EMA_21'].iloc[-1]
        rsi_actual = df['RSI'].iloc[-1]

        print(f"📈 Precio Actual: {precio_actual}")
        print(f"📈 EMA 9: {ema9_actual:.2f} | EMA 21: {ema21_actual:.2f}")
        print(f"📈 RSI (14): {rsi_actual:.2f}")

        # 4. Lógica de Estrategia (Ejemplo base: EMA + RSI)
        # Puedes ajustar esta lógica según tus filtros de FVG y cruces
        if ema9_actual > ema21_actual and rsi_actual < 70:
            print("🟢 Señal potencial de COMPRA detectada (Tendencia alcista y RSI saludable).")
            # Aquí puedes agregar la orden: exchange.create_market_buy_order(...)
        elif ema9_actual < ema21_actual and rsi_actual > 30:
            print("🔴 Señal potencial de VENTA detectada (Tendencia bajista).")
            # Aquí puedes agregar la orden: exchange.create_market_sell_order(...)
        else:
            print("⏳ Sin condiciones claras de entrada en este ciclo. Esperando siguiente ejecución...")

    except Exception as e:
        print(f"⚠️ Ocurrió un error al ejecutar el bot: {e}")

if __name__ == "__main__":
    run_bot()
