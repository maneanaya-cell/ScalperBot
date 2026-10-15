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

        # 2. Consultar balance y posiciones activas
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

        # Análisis de mercado
        print(f"📊 Analizando el mercado para {simbolo} en temporalidad {timeframe}...")
        ohlcv = exchange.fetch_ohlcv(simbolo, timeframe=timeframe, limit=250)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Indicadores Técnicos
        df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
        df['EMA_200'] = df['close'].ewm(span=200, adjust=False).mean()  # Filtro de tendencia principal
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
        
        # Centro del canal S&R para toma de ganancias parciales y reubicación de SL
        sr_centro = (sr_top_actual + sr_bot_actual) / 2

        print(f"📈 Precio Actual: {precio_actual}")
        print(f"📈 EMA 200 (Tendencia): {ema200_actual:.2f}")
        print(f"📊 Canal S&R -> Soporte: {sr_bot_actual:.2f} | Centro: {sr_centro:.2f} | Resistencia: {sr_top_actual:.2f}")
        print(f"📊 RSI Actual: {rsi_actual:.2f}")

        # 3. GESTIÓN DE POSICIÓN ACTIVA
        if posicion_activa:
            side = posicion_activa['side'] # 'long' o 'short'
            entry_price = float(posicion_activa['entryPrice'])
            amount = float(posicion_activa['contracts'])
            print(f"ℹ️ Posición activa detectada: {side.upper()} | Entrada: {entry_price} | Cantidad: {amount}")

            if side == 'long':
                ganancia_pct = ((precio_actual - entry_price) / entry_price) * 100
                
                # Toma de ganancia parcial en el centro si hay ganancia real
                if precio_actual >= sr_centro and ganancia_pct > 0:
                    print(f"🎯 Precio en el centro del canal con ganancia real ({ganancia_pct:.2f}%). Tomando ganancia parcial...")
                    try:
                        mitad_contratos = round(amount / 2, 4)
                        if mitad_contratos >= 0.0001:
                            exchange.create_market_sell_order(simbolo, mitad_contratos, {'reduceOnly': True})
                            print(f"✅ Venta parcial ejecutada. Ganancia asegurada: {ganancia_pct:.2f}%")
                            
                            # Mover Stop Loss a Break-Even (precio de entrada) para proteger el resto
                            try:
                                ordenes_abiertas = exchange.fetch_open_orders(simbolo)
                                for o in ordenes_abiertas:
                                    if o['type'] == 'stop_market' or o.get('info', {}).get('stopPrice'):
                                        exchange.cancel_order(o['id'], simbolo)
                                        print("🛡️ Stop Loss anterior cancelado.")
                                
                                sl_seguro = round(entry_price, 1) # Break-even exacto
                                exchange.create_order(simbolo, 'stop_market', 'sell', round(amount - mitad_contratos, 4), None, {
                                    'stopPrice': sl_seguro,
                                    'reduceOnly': True
                                })
                                print(f"🛡️ Nuevo Stop Loss protegido en Break-Even: {sl_seguro}")
                            except Exception as e_sl_up:
                                print(f"⚠️ No se pudo actualizar el Stop Loss automáticamente: {e_sl_up}")

                            registrar_operacion("TP_PARCIAL_CENTRO", simbolo, "LONG", entry_price, precio_actual, ganancia_pct, "PARCIAL_CERRADA")
                    except Exception as e_tp:
                        print(f"⚠️ Error al ejecutar toma parcial: {e_tp}")
                        
                elif precio_actual >= sr_top_actual and ganancia_pct > 0:
                    print("🚀 ¡Precio tocó la RESISTENCIA FINAL con ganancias! Cerrando posición completa...")
                    exchange.close_position(simbolo)
                    registrar_operacion("TP_FINAL", simbolo, "LONG", entry_price, precio_actual, ganancia_pct, "CERRADA_EXITO")
                else:
                    print(f"⏳ Posición LONG activa. Ganancia actual: {ganancia_pct:.2f}%")
            
            else: # SHORT
                ganancia_pct = ((entry_price - precio_actual) / entry_price) * 100
                
                if precio_actual <= sr_centro and ganancia_pct > 0:
                    print(f"🎯 Precio en el centro del canal bajista con ganancia real ({ganancia_pct:.2f}%). Tomando ganancia parcial...")
                    try:
                        mitad_contratos = round(amount / 2, 4)
                        if mitad_contratos >= 0.0001:
                            exchange.create_market_buy_order(simbolo, mitad_contratos, {'reduceOnly': True})
                            print(f"✅ Compra parcial ejecutada. Ganancia asegurada: {ganancia_pct:.2f}%")
                            
                            # Mover Stop Loss a Break-Even para proteger el short restante
                            try:
                                ordenes_abiertas = exchange.fetch_open_orders(simbolo)
                                for o in ordenes_abiertas:
                                    if o['type'] == 'stop_market' or o.get('info', {}).get('stopPrice'):
                                        exchange.cancel_order(o['id'], simbolo)
                                        print("🛡️ Stop Loss anterior cancelado.")
                                
                                sl_seguro = round(entry_price, 1)
                                exchange.create_order(simbolo, 'stop_market', 'buy', round(amount - mitad_contratos, 4), None, {
                                    'stopPrice': sl_seguro,
                                    'reduceOnly': True
                                })
                                print(f"🛡️ Nuevo Stop Loss protegido en Break-Even: {sl_seguro}")
                            except Exception as e_sl_up:
                                print(f"⚠️ No se pudo actualizar el Stop Loss automáticamente: {e_sl_up}")

                            registrar_operacion("TP_PARCIAL_CENTRO", simbolo, "SHORT", entry_price, precio_actual, ganancia_pct, "PARCIAL_CERRADA")
                    except Exception as e_tp:
                        print(f"⚠️ Error al ejecutar toma parcial: {e_tp}")
                        
                elif precio_actual <= sr_bot_actual and ganancia_pct > 0:
                    print("🚀 ¡Precio tocó el SOPORTE FINAL con ganancias! Cerrando posición completa...")
                    exchange.close_position(simbolo)
                    registrar_operacion("TP_FINAL", simbolo, "SHORT", entry_price, precio_actual, ganancia_pct, "CERRADA_EXITO")
                else:
                    print(f"⏳ Posición SHORT activa. Ganancia actual: {ganancia_pct:.2f}%")
            return

        # 4. APERTURA DE NUEVAS ÓRDENES (Con filtro de tendencia EMA 200 y rangos de RSI de Momentum)
        inversion_usd = 0.10 
        cantidad_btc = round(inversion_usd / precio_actual, 4)
        if cantidad_btc < 0.0001:
            cantidad_btc = 0.0001

        print(f"⚙️ Monto calculado para la orden: {cantidad_btc} BTC")

        # SOLO COMPRAS (LONG) si Precio > EMA 200 y el RSI está en zona de impulso alcista (60 a 70)
        if precio_actual > ema200_actual and (precio_actual <= (sr_bot_actual * 1.003) or (ema9_actual > ema21_actual and (60 <= rsi_actual < 70))):
            print("🟢 Señal de COMPRA por Momentum (Precio > EMA 200 y RSI en rango 60-70)...")
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

        # SOLO VENTAS (SHORT) si Precio < EMA 200 y el RSI está en zona de impulso bajista (30 a 40)
        elif precio_actual < ema200_actual and (precio_actual >= (sr_top_actual * 0.997) or (ema9_actual < ema21_actual and (30 < rsi_actual <= 40))):
            print("🔴 Señal de VENTA por Momentum (Precio < EMA 200 y RSI en rango 30-40)...")
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
            print("⏳ Sin señales válidas (filtrado por tendencia EMA 200 o RSI fuera de rangos de momentum).")

    except Exception as e:
        print(f"⚠️ Error al operar: {e}")

if __name__ == "__main__":
    run_bot()
