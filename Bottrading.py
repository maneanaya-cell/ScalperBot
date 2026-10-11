import os
import ccxt

def run_bot():
    try:
        # Cargamos las credenciales desde las variables de entorno de GitHub Actions
        api_key = os.getenv('BINGX_API_KEY')
        secret_key = os.getenv('BINGX_SECRET_KEY')

        # Verificamos que las claves existan para evitar errores inesperados
        if not api_key or not secret_key:
            print("❌ Error: No se encontraron las credenciales de BingX en las variables de entorno.")
            return

        # Inicializamos el exchange BingX usando ccxt
        exchange = ccxt.bingx({
            'apiKey': api_key,
            'secret': secret_key,
            'enableRateLimit': True,
        })

        # Opcional: Cargar los mercados del exchange
        exchange.load_markets()
        print("✅ Conexión exitosa con BingX cargando mercados correctamente.")

        # Ejemplo de acción: Consultar el balance de la cuenta
        balance = exchange.fetch_balance()
        print("💰 Balance obtenido correctamente.")
        
        # Aquí puedes agregar la lógica principal de tu estrategia de scalping
        # ...

    except Exception as e:
        print(f"⚠️ Ocurrió un error al ejecutar el bot: {e}")

if __name__ == "__main__":
    run_bot()
