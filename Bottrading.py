import os
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timezone

# Archivo donde se guardará el registro
CSV_FILE = 'historial_operaciones.csv'

def registrar_operacion(evento, simbolo, tipo, precio_entrada, precio_salida=0.0, resultado_pct=0.0, estado="ABIERTA", id_orden=""):
    """Guarda un registro estructurado de cada operación en el archivo CSV."""
    encabezados = ['Fecha_Hora', 'Evento', 'Simbolo', 'Tipo', 'Precio_Entrada', 'Precio_Salida', 'Resultado_Pct', 'Estado', 'ID_Orden']
    
    fecha_actual = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    nueva_fila = {
        'Fecha_Hora': fecha_actual,
        'Evento': evento,
        'Simbolo': simbolo,
        'Tipo': tipo.upper(),
        'Precio_Entrada': precio_entrada,
        'Precio_Salida': precio_salida,
        'Resultado_Pct': round(resultado_pct, 2),
        'Estado': estado,
        'ID_Orden': id_orden
    }
    
    if not os.path.exists(CSV_FILE):
        df_log = pd.DataFrame([nueva_fila], columns=encabezados)
        df_log.to_csv(CSV_FILE, index=False)
    else:
        df_log = pd.DataFrame([nueva_fila])
        df_log.to_csv(CSV_FILE, mode='a', header=False, index=False)
        
    print(f"📝 Registrado en CSV -> Evento: {evento} | Tipo: {tipo} | Estado: {estado}")

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

def detectar_divergencias(df):
    """
    Detecta divergencias simples en las últimas velas:
    - Alcista: Precio hace mínimo más bajo, RSI hace mínimo más alto.
    - Bajista: Precio hace máximo más alto, RSI hace máximo más bajo.
    """
    if len(df) < 15:
        return False, False

    # Tomamos una ventana reciente para buscar pivotes
    p_reciente = df['close'].iloc[-1]
    p_anterior = df['close'].iloc[-6]
    p_pasado = df['close'].iloc[-12]

    rsi_reciente = df['RSI'].iloc[-1]
    rsi_anterior = df['RSI'].iloc[-6]
    rsi_pasado = df['RSI'].iloc[-12]

    # Divergencia Alcista: Precio cae (mínimo más bajo) pero RSI sube (mínimo más alto)
    divergencia_alcista = (p_reciente < p_anterior) and (rsi_reciente > rsi_anterior) and (rsi_reciente < 45)

    # Divergencia Bajista: Precio sube (máximo más alto) pero RSI baja (máximo más bajo)
    divergencia_bajista = (p_reciente > p_anterior) and (rsi_reciente < rsi_anterior) and (rsi_reciente > 55)

    return divergencia_alcista, divergencia_bajista

def es_horario_operativo():
    """Valida si alguna de las tres grandes sesiones (Tokio, Londres, Nueva York) está activa en UTC."""
    now_utc = datetime.now(timezone.utc)
    hora = now_utc.hour + now_utc.minute / 60.0
    
    tokio = 0 <= hora < 9          # 00:00 a 09:00 UTC
    londres = 8 <= hora < 16.5     # 08:00 a 16:30 UTC
    ny = 13.5 <= hora < 20         # 13:30 a 20:00 UTC
    
    return tokio or londres or ny

def run_bot():
    try:
        if not es_horario_operativo():
            print(f"⏳ Fuera de horario institucional (Tokio/Londres/Nueva York). Bot en pausa.")
            return

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
                'defaultType': 'swap',
            }
        })

        exchange.load_markets()
        print("✅ Conexión establecida con la cuenta de BingX (Sesión activa).")

        balance = exchange.fetch_balance()
        usdt_free = balance['USDT']['free'] if 'USDT' in balance else 0
        print(f"💰 Balance disponible en USDT (Real): {usdt_free}")

        simbolo = 'BTC/USDT:USDT'
        timeframe = '15m'

        posiciones = exchange.fetch_positions([simbolo])
        posicion_activa = None
        for p in posiciones:
            if float(p['contracts']) > 0:
                posicion_activa = p
                break

        print(f"📊 Analizando el mercado para {simbolo} en temporalidad {timeframe}...")
        ohlcv = exchange.fetch_ohlcv(simbolo, timeframe=timeframe, limit=250)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
        df['EMA_200'] = df['close'].ewm(span=200, adjust=False).mean()
        df['RSI'] = calcular_rsi(df['close'], periodo=14)
        
        length = 130
        atr_series = calcular_atr(df, periodo=200)
        rolling_max = df['high'].rolling(window=length).max()
        rolling_min = df['low'].rolling(window=length).min()
        
        df['SR_Top'] = rolling_max + (atr_series * 0.5)
        df['SR_Bot'] = rolling_min - (atr_series * 0.5)
        
        precio_actual = df['close'].iloc[-1]
        ema9_actual = df['EMA_9'].iloc[-1]
        ema21_actual = df['EMA_21'].iloc[-1]
        ema200_actual = df['EMA_200'].iloc[-1]
        rsi_actual = df['RSI'].iloc[-1]
        sr_top_actual = df['SR_Top'].iloc[-1]
        sr_bot_actual = df['SR_Bot'].iloc[-1]

        rango_canal = sr_top_actual - sr_bot_actual
        div_alcista, div_bajista = detectar_divergencias(df)

        print(f"📈 Precio Actual: {precio_actual}")
        print(f"📈 EMA 200 (Tendencia): {ema200_actual:.2f}")
        print(f"📊 Canal S&R -> Soporte: {sr_bot_actual:.2f} | Resistencia: {sr_top_actual:.2f}")
        print(f"📊 RSI Actual: {rsi_actual:.2f} | Div Alcista: {div_alcista} | Div Bajista: {div_bajista}")

        # GESTIÓN DE POSICIÓN ACTIVA CON TRAILING STOP DINÁMICO (Desde +0.3%)
        if posicion_activa:
            side = posicion_activa['side']
            entry_price = float(posicion_activa['entryPrice'])
            amount = float(posicion_activa['contracts'])
            print(f"ℹ️ Posición activa detectada: {side.upper()} | Entrada: {entry_price} | Cantidad: {amount}")

            sl_actual_exchange = None
            try:
                ordenes_abiertas = exchange.fetch_open_orders(simbolo)
                for o in ordenes_abiertas:
                    if o['type'] == 'stop_market' or o.get('info', {}).get('stopPrice'):
                        sl_actual_exchange = float(o['info'].get('stopPrice', o.get('price', 0)))
            except Exception as e_fetch_sl:
                print(f"⚠️ Nota al consultar órdenes abiertas: {e_fetch_sl}")

            if side == 'long':
                ganancia_pct = ((precio_actual - entry_price) / entry_price) * 100
                print(f"⏳ Posición LONG activa. Ganancia actual: {ganancia_pct:.2f}%")

                if ganancia_pct >= 0.3:
                    nuevo_sl = round(precio_actual * 0.998, 1)
                    if sl_actual_exchange and nuevo_sl < sl_actual_exchange:
                        nuevo_sl = sl_actual_exchange

                    print(f"🎯 Ganancia >= 0.3% alcanzada. Actualizando Trailing Stop...")
                    try:
                        ordenes_abiertas = exchange.fetch_open_orders(simbolo)
                        for o in ordenes_abiertas:
                            if o['type'] == 'stop_market' or o.get('info', {}).get('stopPrice'):
                                exchange.cancel_order(o['id'], simbolo)
                        
                        exchange.create_order(simbolo, 'stop_market', 'sell', amount, None, {
                            'stopPrice': nuevo_sl,
                            'reduceOnly': True
                        })
                        print(f"🛡️ Trailing Stop actualizado en: {nuevo_sl}")
                        registrar_operacion("TRAILING_UPDATE", simbolo, "LONG", entry_price, precio_actual, ganancia_pct, "ACTIVA")
                    except Exception as e_sl_up:
                        print(f"⚠️ Error actualizando Trailing Stop: {e_sl_up}")
                        
                elif precio_actual >= sr_top_actual and ganancia_pct > 0:
                    print("🚀 ¡Precio tocó la RESISTENCIA FINAL! Cerrando posición...")
                    exchange.close_position(simbolo)
                    registrar_operacion("TP_FINAL", simbolo, "LONG", entry_price, precio_actual, ganancia_pct, "CERRADA_EXITO")
            
            else: # SHORT
                ganancia_pct = ((entry_price - precio_actual) / entry_price) * 100
                print(f"⏳ Posición SHORT activa. Ganancia actual: {ganancia_pct:.2f}%")

                if ganancia_pct >= 0.3:
                    nuevo_sl = round(precio_actual * 1.002, 1)
                    if sl_actual_exchange and nuevo_sl > sl_actual_exchange:
                        nuevo_sl = sl_actual_exchange

                    print(f"🎯 Ganancia >= 0.3% alcanzada. Actualizando Trailing Stop...")
                    try:
                        ordenes_abiertas = exchange.fetch_open_orders(simbolo)
                        for o in ordenes_abiertas:
                            if o['type'] == 'stop_market' or o.get('info', {}).get('stopPrice'):
                                exchange.cancel_order(o['id'], simbolo)
                        
                        exchange.create_order(simbolo, 'stop_market', 'buy', amount, None, {
                            'stopPrice': nuevo_sl,
                            'reduceOnly': True
                        })
                        print(f"🛡️ Trailing Stop actualizado en: {nuevo_sl}")
                        registrar_operacion("TRAILING_UPDATE", simbolo, "SHORT", entry_price, precio_actual, ganancia_pct, "ACTIVA")
                    except Exception as e_sl_up:
                        print(f"⚠️ Error actualizando Trailing Stop: {e_sl_up}")
                        
                elif precio_actual <= sr_bot_actual and ganancia_pct > 0:
                    print("🚀 ¡Precio tocó el SOPORTE FINAL! Cerrando posición...")
                    exchange.close_position(simbolo)
                    registrar_operacion("TP_FINAL", simbolo, "SHORT", entry_price, precio_actual, ganancia_pct, "CERRADA_EXITO")
            return

        # APERTURA DE NUEVAS ÓRDENES (Con Tendencia, Ubicación en Canal, Momentum y Divergencias)
        inversion_usd = 0.10 
        cantidad_btc = round(inversion_usd / precio_actual, 4)
        if cantidad_btc < 0.0001:
            cantidad_btc = 0.0001

        print(f"⚙️ Monto calculado para la orden: {cantidad_btc} BTC")

        es_ubicacion_valida_long = precio_actual <= (sr_bot_actual + (rango_canal * 0.45))
        es_ubicacion_valida_short = precio_actual >= (sr_top_actual - (rango_canal * 0.45))

        # CONDICIÓN DE COMPRA (LONG): Se activa por toque de soporte, cruce de EMAs con rango o por Divergencia Alcista
        if precio_actual > ema200_actual and es_ubicacion_valida_long and (precio_actual <= (sr_bot_actual * 1.003) or (ema9_actual > ema21_actual and (60 <= rsi_actual < 70)) or div_alcista):
            print("🟢 Señal de COMPRA validada (Tendencia + Zona baja + Momentum / Divergencia Alcista)...")
            if usdt_free >= 0.05:
                orden = exchange.create_market_buy_order(simbolo, cantidad_btc)
                order_id = orden.get('id', '')
                print(f"✅ ¡Orden de COMPRA ejecutada con éxito! ID: {order_id}")
                
                sl_inicial = round(sr_bot_actual * 0.992, 1)
                try:
                    exchange.create_order(simbolo, 'stop_market', 'sell', cantidad_btc, None, {
                        'stopPrice': sl_inicial,
                        'reduceOnly': True
                    })
                    print(f"🛡️ Stop Loss protector colocado en: {sl_inicial}")
                except Exception as e_sl:
                    print(f"⚠️ Detalle al colocar SL inicial: {e_sl}")
                
                registrar_operacion("APERTURA", simbolo, "LONG", precio_actual, 0.0, 0.0, "ABIERTA", order_id)
            else:
                print("⚠️ Balance insuficiente para operar.")

        # CONDICIÓN DE VENTA (SHORT): Se activa por resistencia, cruce de EMAs con rango o por Divergencia Bajista
        elif precio_actual < ema200_actual and es_ubicacion_valida_short and (precio_actual >= (sr_top_actual * 0.997) or (ema9_actual < ema21_actual and (30 < rsi_actual <= 40)) or div_bajista):
            print("🔴 Señal de VENTA validada (Tendencia + Zona alta + Momentum / Divergencia Bajista)...")
            if usdt_free >= 0.05:
                orden = exchange.create_market_sell_order(simbolo, cantidad_btc)
                order_id = orden.get('id', '')
                print(f"✅ ¡Orden de VENTA ejecutada con éxito! ID: {order_id}")
                
                sl_inicial = round(sr_top_actual * 1.008, 1)
                try:
                    exchange.create_order(simbolo, 'stop_market', 'buy', cantidad_btc, None, {
                        'stopPrice': sl_inicial,
                        'reduceOnly': True
                    })
                    print(f"🛡️ Stop Loss protector colocado en: {sl_inicial}")
                except Exception as e_sl:
                    print(f"⚠️ Detalle al colocar SL inicial: {e_sl}")
                
                registrar_operacion("APERTURA", simbolo, "SHORT", precio_actual, 0.0, 0.0, "ABIERTA", order_id)
            else:
                print("⚠️ Balance insuficiente para operar.")
        else:
            print("⏳ Sin señales válidas (filtrado por horario, tendencia, canal o ausencia de divergencia/momentum).")

    except Exception as e:
        print(f"⚠️ Error al operar: {e}")

if __name__ == "__main__":
    run_bot()
