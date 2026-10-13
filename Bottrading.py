import os
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime

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
    
    # Crear archivo con encabezados si no existe
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

        # 2. Consultar balance real y posiciones abiertas actuales
        balance = exchange.fetch_balance()
        usdt_free = balance['USDT']['free'] if 'USDT' in balance else 0
        print(f"💰 Balance disponible en USDT (Real): {usdt_free}")

        simbolo = 'BTC/USDT:USDT'
        timeframe = '15m'

        # Verificamos si ya tenemos una posición abierta para gestionarla (Trailing Dinámico)
        posiciones = exchange.fetch_positions([simbolo])
        posicion_activa = None
        for p in posiciones:
            if float(p['contracts']) > 0:
                posicion_activa = p
                break

        # Símbolo y Temporalidad para análisis
        print(f"📊 Analizando el mercado para {simbolo} en temporalidad {timeframe}...")
        ohlcv = exchange.fetch_ohlcv(simbolo, timeframe=timeframe, limit=250)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Indicadores Técnicos
        df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
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
        rsi_actual = df['RSI'].iloc[-1]
        sr_top_actual = df['SR_Top'].iloc[-1]
        sr_bot_actual = df['SR_Bot'].iloc[-1]

        print(f"📈 Precio Actual: {precio_actual}")
        print(f"📈 EMA 9: {ema9_actual:.2f} | EMA 21: {ema21_actual:.2f}")
        print(f"📈 RSI (14): {rsi_actual:.2f}")
        print(f"📊 Canal S&R -> Soporte: {sr_bot_actual:.2f} | Resistencia: {sr_top_actual:.2f}")

        # 3. GESTIÓN DE POSICIÓN ABIERTA (Si ya hay una posición en marcha)
        if posicion_activa:
            side = posicion_activa['side'] # 'long' o 'short'
            entry_price = float(posicion_activa['entryPrice'])
            amount = float(posicion_activa['contracts'])
            print(f"ℹ️ Posición activa detectada: {side.upper()} | Entrada: {entry_price} | Cantidad: {amount}")

            # Calcular ganancia porcentual actual
            if side == 'long':
                ganancia_pct = ((precio_actual - entry_price) / entry_price) * 100
            else:
                ganancia_pct = ((entry_price - precio_actual) / entry_price) * 100

            print(f"📊 Ganancia actual de la posición: {ganancia_pct:.2f}%")

            # Si la ganancia supera o iguala el 0.5%, aplicamos / actualizamos el Trailing Stop dinámico
            if ganancia_pct >= 0.5:
                print("🎯 ¡Meta de 0.5% alcanzada! Ajustando Trailing Stop (asegurando 0.2% y distancia 0.3%)...")
                
                try:
                    exchange.cancel_all_orders(simbolo)
                except:
                    pass

                if side == 'long':
                    nuevo_sl = round(precio_actual * (1 - 0.003), 1)
                    sl_minimo_garantizado = entry_price * 1.002
                    if nuevo_sl < sl_minimo_garantizado:
                        nuevo_sl = round(sl_minimo_garantizado, 1)

                    exchange.create_order(simbolo, 'stop_market', 'sell', amount, None, {
                        'stopPrice': nuevo_sl,
                        'reduceOnly': True
                    })
                    print(f"✅ Trailing Stop en LONG actualizado a: {nuevo_sl}")
                else:
                    nuevo_sl = round(precio_actual * (1 + 0.003), 1)
                    sl_minimo_garantizado = entry_price * 0.998
                    if nuevo_sl > sl_minimo_garantizado:
                        nuevo_sl = round(sl_minimo_garantizado, 1)

                    exchange.create_order(simbolo, 'stop_market', 'buy', amount, None, {
                        'stopPrice': nuevo_sl,
                        'reduceOnly': True
                    })
                    print(f"✅ Trailing Stop en SHORT actualizado a: {nuevo_sl}")
                
                # Registrar actualización de Trailing Stop en CSV
                registrar_operacion("AJUSTE_TRAILING", simbolo, side, entry_price, precio_actual, ganancia_pct, "TRAILING_ACTIVO")
            else:
                print("⏳ Posición abierta con ganancia < 0.5%. Manteniendo Stop Loss estructural de protección.")
            return

        # 4. APERTURA DE NUEVAS ÓRDENES (Si no hay posición activa)
        inversion_usd = 0.10 
        cantidad_btc = round(inversion_usd / precio_actual, 4)
        if cantidad_btc < 0.0001:
            cantidad_btc = 0.0001

        print(f"⚙️ Monto calculado para la orden: {cantidad_btc} BTC (aprox. {inversion_usd} USDT)")

        if precio_actual <= (sr_bot_actual * 1.003) or (ema9_actual > ema21_actual and rsi_actual < 65):
            print("🟢 Señal de COMPRA detectada...")
            if usdt_free >= 0.05:
                orden = exchange.create_market_buy_order(simbolo, cantidad_btc)
                order_id = orden.get('id', '')
                print(f"✅ ¡Orden de COMPRA ejecutada con éxito! ID: {order_id}")
                
                sl_inicial = round(sr_bot_actual * 0.995, 1)
                
                try:
                    exchange.create_order(simbolo, 'stop_market', 'sell', cantidad_btc, None, {
                        'stopPrice': sl_inicial,
                        'reduceOnly': True
                    })
                    print(f"🛡️ Stop Loss inicial colocado debajo del soporte en: {sl_inicial}")
                except Exception as e_sl:
                    print(f"⚠️ Orden abierta, pero detalle al colocar el SL inicial: {e_sl}")
                
                # Registrar apertura LONG en CSV
                registrar_operacion("APERTURA", simbolo, "LONG", precio_actual, 0.0, 0.0, "ABIERTA", order_id)
            else:
                print("⚠️ Balance insuficiente para operar.")

        elif precio_actual >= (sr_top_actual * 0.997) or (ema9_actual < ema21_actual and rsi_actual > 35):
            print("🔴 Señal de VENTA detectada...")
            if usdt_free >= 0.05:
                orden = exchange.create_market_sell_order(simbolo, cantidad_btc)
                order_id = orden.get('id', '')
                print(f"✅ ¡Orden de VENTA ejecutada con éxito! ID: {order_id}")
                
                sl_inicial = round(sr_top_actual * 1.005, 1)
                
                try:
                    exchange.create_order(simbolo, 'stop_market', 'buy', cantidad_btc, None, {
                        'stopPrice': sl_inicial,
                        'reduceOnly': True
                    })
                    print(f"🛡️ Stop Loss inicial colocado encima de la resistencia en: {sl_inicial}")
                except Exception as e_sl:
                    print(f"⚠️ Orden abierta, pero detalle al colocar el SL inicial: {e_sl}")
                
                # Registrar apertura SHORT en CSV
                registrar_operacion("APERTURA", simbolo, "SHORT", precio_actual, 0.0, 0.0, "ABIERTA", order_id)
            else:
                print("⚠️ Balance insuficiente para operar.")
        else:
            print("⏳ Sin señales de ejecución en este ciclo.")

    except Exception as e:
        print(f"⚠️ Error al operar: {e}")

if __name__ == "__main__":
    run_bot()
