"""
Sistema de alertas de precio para acciones del portafolio
"""
if __package__:
    from .db import obtener_conexion
else:
    from db import obtener_conexion
from datetime import datetime, timedelta
import yfinance as yf
from fastapi import HTTPException

class GestorAlertas:
    """Gestiona alertas de precio para cada acción"""
    
    def crear_tabla_alertas(self):
        """Crea la tabla de alertas si no existe"""
        conexion = obtener_conexion()
        cursor = conexion.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alertas_precio (
                id INT PRIMARY KEY AUTO_INCREMENT,
                user_id INT NOT NULL,
                ticker VARCHAR(10) NOT NULL,
                tipo ENUM('sube_a', 'baja_a') NOT NULL,
                precio_objetivo DECIMAL(10, 2) NOT NULL,
                activa BOOLEAN DEFAULT TRUE,
                fecha_creacion DATETIME DEFAULT CURRENT_TIMESTAMP,
                fecha_activacion DATETIME,
                FOREIGN KEY (user_id) REFERENCES usuarios(id) ON DELETE CASCADE
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS historial_transacciones (
                id INT PRIMARY KEY AUTO_INCREMENT,
                user_id INT NOT NULL,
                tipo ENUM('compra', 'venta', 'alerta') NOT NULL,
                ticker VARCHAR(10) NOT NULL,
                cantidad INT,
                precio DECIMAL(10, 2),
                monto DECIMAL(15, 2),
                fecha DATETIME DEFAULT CURRENT_TIMESTAMP,
                detalles TEXT,
                FOREIGN KEY (user_id) REFERENCES usuarios(id) ON DELETE CASCADE
            )
        """)
        
        conexion.commit()
        cursor.close()
        conexion.close()
    
    def crear_alerta(self, user_id: int, ticker: str, tipo: str, precio_objetivo: float):
        """Crea una nueva alerta para el usuario"""
        conexion = obtener_conexion()
        cursor = conexion.cursor()
        
        if tipo not in ['sube_a', 'baja_a']:
            raise HTTPException(status_code=400, detail="Tipo de alerta inválido")
        
        cursor.execute("""
            INSERT INTO alertas_precio (user_id, ticker, tipo, precio_objetivo)
            VALUES (%s, %s, %s, %s)
        """, (user_id, ticker.upper(), tipo, precio_objetivo))
        
        conexion.commit()
        alerta_id = cursor.lastrowid
        cursor.close()
        conexion.close()
        
        return {"id": alerta_id, "mensaje": "Alerta creada exitosamente"}
    
    def obtener_alertas_usuario(self, user_id: int):
        """Obtiene todas las alertas activas del usuario"""
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT id, ticker, tipo, precio_objetivo, fecha_creacion 
            FROM alertas_precio 
            WHERE user_id = %s AND activa = TRUE
        """, (user_id,))
        
        alertas = cursor.fetchall()
        cursor.close()
        conexion.close()
        
        # Agregar precio actual a cada alerta
        for alerta in alertas:
            try:
                precio_actual = float(yf.Ticker(alerta['ticker']).history(period="1d")["Close"].iloc[-1])
                alerta['precio_actual'] = round(precio_actual, 2)
                
                if alerta['tipo'] == 'sube_a':
                    alerta['activada'] = precio_actual >= float(alerta['precio_objetivo'])
                else:
                    alerta['activada'] = precio_actual <= float(alerta['precio_objetivo'])
            except:
                alerta['precio_actual'] = None
                alerta['activada'] = False
        
        return alertas
    
    def eliminar_alerta(self, user_id: int, alerta_id: int):
        """Desactiva una alerta"""
        conexion = obtener_conexion()
        cursor = conexion.cursor()
        
        cursor.execute("""
            UPDATE alertas_precio SET activa = FALSE 
            WHERE id = %s AND user_id = %s
        """, (alerta_id, user_id))
        
        conexion.commit()
        modificadas = cursor.rowcount
        cursor.close()
        conexion.close()
        
        return {"eliminada": modificadas > 0}
    
    def registrar_transaccion(self, user_id: int, tipo: str, ticker: str, 
                            cantidad: int = None, precio: float = None, detalles: str = None):
        """Registra una transacción en el historial"""
        conexion = obtener_conexion()
        cursor = conexion.cursor()
        
        monto = None
        if cantidad and precio:
            monto = cantidad * precio
        
        cursor.execute("""
            INSERT INTO historial_transacciones 
            (user_id, tipo, ticker, cantidad, precio, monto, detalles)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (user_id, tipo, ticker.upper(), cantidad, precio, monto, detalles))
        
        conexion.commit()
        cursor.close()
        conexion.close()
    
    def obtener_historial_usuario(self, user_id: int, limite: int = 50):
        """Obtiene el historial de transacciones del usuario"""
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT * FROM historial_transacciones 
            WHERE user_id = %s 
            ORDER BY fecha DESC 
            LIMIT %s
        """, (user_id, limite))
        
        historial = cursor.fetchall()
        cursor.close()
        conexion.close()
        
        return historial

# Instancia global
gestor_alertas = GestorAlertas()
