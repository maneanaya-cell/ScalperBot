import os
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timezone

# --- CONFIGURACIÓN DE CREDENCIALES Y BINGX ---
# Se obtienen de las variables de entorno de GitHub Actions (Secrets)
api_key = os.getenv('BINGX_API_KEY')
api_secret = os.getenv('BINGX_API_SECRET')

exchange = ccxt.bingx({
    'apiKey': api_key,
    'secret': api_secret,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'swap',  # Mercado de Futuros Perpetuos
    }
})

# Cargar mercados para asegurar compatibilidad
exchange.load_markets()

# --- PARÁMETROS DE TRADING ---
SYMBOL = 'BTC/USDT:USDT'
TIMEFRAME = '15m'
LEVERAGE = 10
MARGEN_USDT = 1.0  # Margen fijo ajustado a $1.00 USDT

# --- 1. VERIFICACIÓN DE HORARIO INSTITUCIONAL ---
def es_horario_operativo():
    """
    Valida si la hora UTC actual se encuentra dentro de las ventanas 
    de alta liquidez institucional: Tokio, Londres o Nueva York.
    """
    now_utc = datetime.now(timezone.utc)
    hora_decimal = now_utc.hour + now_utc.minute / 60.0
    
    # Tokio: 00:00 - 09:00 UTC
    # Londres: 08:00 - 16:30 UTC
    # Nueva York: 13:30 - 20:00 UTC
    tokio = 0.0 <= hora_decimal <= 9.0
    londres = 8.0 <= hora_decimal <= 16.5
    ny = 13.5 <= hora_decimal <= 20.0
    
    return tokio or londres or ny

# --- 2. INDICADORES TÉCNICOS ---
def calcular_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calcular_canal_sr(df, lookback=130):
    """Calcula el canal de Soporte y Resistencia basado en máximos y mínimos con ATR"""
    highs = df['high'].rolling(window=lookback).max()
    lows = df['low'].rolling(window=lookback).min()
    atr = (df['high'] - df['low']).rolling(window=200).mean()
    resistencia = highs - (atr * 0.5)
    soporte = lows + (atr * 0.5)
    return soporte, resistencia

def detectar_divergencias(df):
    """Detecta divergencias simples entre el precio y el RSI"""
    close = df['close']
    rsi = df['rsi']
    
    # Pivotes simples en las últimas 5 velas
    div_alcista = (close.iloc[-1] < close.iloc[-5]) and (rsi.iloc[-1] > rsi.iloc[-5]) and (rsi.iloc[-1] < 45)
    div_bajista = (close.iloc[-1] > close.iloc[-5]) and (rsi.iloc[-1] < rsi.iloc[-15]) and (rsi.iloc[-1] > 55)
    
    return bool(div_alcista), bool(div_bajista)

# --- 3. REGISTRO EN BITÁCORA (CSV) ---
def registrar_en_csv(evento, tipo, precio_entrada, precio_salida, resultado_pct, estado, id_orden=""):
    archivo = "historial_operaciones.csv"
    columnas = ["Fecha_Hora", "Evento", "Simbolo", "Tipo", "Precio_Entrada", "Precio_Salida", "Resultado_Pct", "Estado", "ID_Orden"]
    
    # Si no existe el archivo, crearlo con encabezados
    if not os.path.exists(archivo):
        df_init = pd.DataFrame(columns=columnas)
        df_init.to_csv(archivo, index=False)
        
    nueva_fila = {
        "Fecha_Hora": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "Evento": evento,
        "Simbolo": SYMBOL,
        "Tipo": tipo,
        "Precio_Entrada": precio_entrada,
        "Precio_Salida": precio_salida,
        "Resultado_Pct": resultado_pct,
        "Estado": estado,
        "ID_Orden": id_orden
    }
    
    df = pd.DataFrame([nueva_fila])
    df.to_csv(archivo, mode='a', header=False, index=False)

# --- 4. EJECUCIÓN PRINCIPAL DEL BOT ---
def ejecutar_bot():
    print("--------------------------------------------------")
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC] Iniciando ciclo del bot...")
    
    # Verificar horario institucional
    if not es_horario_operativo():
        print("⏳ Fuera de horario institucional (Tokio/Londres/NY). El bot se pausa por seguridad.")
        return

    try:
        # Sincronizar apalancamiento
        try:
            exchange.set_leverage(LEVERAGE, SYMBOL)
        except Exception:
            pass

        # Obtener balance disponible
        balance = exchange.fetch_balance()
        usdt_free = balance['USDT']['free']
        print(f"💰 Balance disponible en USDT (Real): {usdt_free:.4f}")

        if usdt_free < MARGEN_USDT:
            print("⚠️ Advertencia: El balance disponible es menor al margen configurado ($1 USDT).")

        # Obtener datos de mercado (Velas de 15m)
        print(f"📊 Analizando el mercado para {SYMBOL} en temporalidad {TIMEFRAME}...")
        bars = exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=250)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Calcular indicadores
        df['ema_9'] = df['close'].ewm(span=9).mean()
        df['ema_21'] = df['close'].ewm(span=21).mean()
        df['ema_200'] = df['close'].ewm(span=200).mean()
        df['rsi'] = calcular_rsi(df['close'], 14)
        
        soporte, resistencia = calcular_canal_sr(df, lookback=130)
        df['soporte'] = soporte
        df['resistencia'] = resistencia
        
        precio_actual = df['close'].iloc[-1]
        ema_200 = df['ema_200'].iloc[-1]
        sup_actual = df['soporte'].iloc[-1]
        res_actual = df['resistencia'].iloc[-1]
        rsi_actual = df['rsi'].iloc[-1]
        
        div_alcista, div_bajista = detectar_divergencias(df)
        
        print(f"📈 Precio Actual: {precio_actual}")
        print(f"📉 EMA 200 (Tendencia): {ema_200:.2f}")
        print(f"📊 Canal S&R -> Soporte: {sup_actual:.2f} | Resistencia: {res_actual:.2f}")
        print(f"📊 RSI Actual: {rsi_actual:.2f} | Div Alcista: {div_alcista} | Div Bajista: {div_bajista}")

        # Calcular tamaño de la orden (Margen $1 * 10x Leverage = $10 Posición Nominal)
        monto_nominal_usdt = MARGEN_USDT * LEVERAGE
        cantidad_btc = round(monto_nominal_usdt / precio_actual, 4)
        if cantidad_btc < 0.0001:
            cantidad_btc = 0.0001
            
        print(f"⚙️ Monto calculado para la orden: {cantidad_btc} BTC (Margen: ${MARGEN_USDT} USDT)")

        # --- LÓGICA DE ENTRADA ---
        # LONG: Precio > EMA 200, RSI < 45 u oversold, divergencia alcista y lejos de la resistencia
        condicion_long = (
            precio_actual > ema_200 and 
            rsi_actual < 45 and 
            div_alcista and 
            (res_actual - precio_actual) > (precio_actual * 0.005)
        )

        # SHORT: Precio < EMA 200, RSI > 55 o overbought, divergencia bajista y lejos del soporte
        condicion_short = (
            precio_actual < ema_200 and 
            rsi_actual > 55 and 
            div_bajista and 
            (precio_actual - sup_actual) > (precio_actual * 0.005)
        )

        # Verificar si ya existen posiciones abiertas en BingX
        posiciones = exchange.fetch_positions([SYMBOL])
        posicion_abierta = any(float(p['contracts']) > 0 for p in posiciones if p['symbol'] == SYMBOL)

        if not posicion_abierta:
            if condicion_long:
                print("🚀 ¡Señal de COMPRA (LONG) detectada! Abriendo posición...")
                order = exchange.create_market_buy_order(SYMBOL, cantidad_btc)
                registrar_en_csv("APERTURA", "LONG", precio_actual, 0.0, 0.0, "ABIERTA", order.get('id', ''))
                print("✅ Orden LONG ejecutada y registrada con éxito.")
                
            elif condicion_short:
                print("📉 ¡Señal de VENTA (SHORT) detectada! Abriendo posición...")
                order = exchange.create_market_sell_order(SYMBOL, cantidad_btc)
                registrar_en_csv("APERTURA", "SHORT", precio_actual, 0.0, 0.0, "ABIERTA", order.get('id', ''))
                print("✅ Orden SHORT ejecutada y registrada con éxito.")
            else:
                print("⏳ Sin señales válidas (filtrado por horario, tendencia, canal o ausencia de divergencia/momentum).")
        else:
            print("🔒 Ya existe una posición abierta. El bot mantiene el monitoreo de riesgo activo.")

    except Exception as e:
        print(f"❌ Error durante la ejecución del bot: {e}")

if __name__ == "__main__":
    ejecutar_bot()
