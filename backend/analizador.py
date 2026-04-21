"""
Módulo de análisis inteligente para recomendaciones de inversión
"""
try:
    from .db import obtener_conexion
except ImportError:
    from db import obtener_conexion
import yfinance as yf
from collections import defaultdict
from datetime import datetime, timedelta
from typing import List, Optional

class AnalizadorPortafolio:
    """Analiza el portafolio del usuario y genera recomendaciones"""
    
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.conexion = obtener_conexion()
        
    def obtener_acciones_usuario(self):
        """Obtiene todas las acciones del usuario"""
        cursor = self.conexion.cursor(dictionary=True)
        cursor.execute(
            "SELECT ticker, cantidad, precio_compra FROM portafolio WHERE user_id = %s",
            (self.user_id,)
        )
        acciones = cursor.fetchall()
        cursor.close()
        return acciones
    
    def obtener_info_acciones(self):
        """Obtiene información de las acciones del usuario y sus métricas"""
        cursor = self.conexion.cursor(dictionary=True)
        
        acciones = self.obtener_acciones_usuario()
        activos_info = []
        
        for accion in acciones:
            try:
                ticker = yf.Ticker(accion['ticker'])
                hist = ticker.history(period="1mo")

                if not hist.empty:
                    # Calcular volatilidad
                    volatilidad = hist['Close'].pct_change().std() * 100

                    # Precio actual
                    precio_actual = float(hist['Close'].iloc[-1])

                    # Asegurar tipos numéricos provenientes de la BD (Decimal -> float)
                    precio_compra_db = accion.get('precio_compra')
                    cantidad_db = accion.get('cantidad', 0)
                    try:
                        precio_compra = float(precio_compra_db) if precio_compra_db is not None else 0.0
                    except Exception:
                        precio_compra = 0.0

                    try:
                        cantidad = int(cantidad_db)
                    except Exception:
                        cantidad = 0

                    # ROI individual (proteger división por cero)
                    roi = ((precio_actual - precio_compra) / precio_compra * 100) if precio_compra > 0 else 0.0

                    # Obtener sector
                    cursor.execute(
                        "SELECT sector, diversidad_sectorial FROM acciones_recomendadas WHERE ticker = %s",
                        (accion['ticker'],)
                    )
                    info_sector = cursor.fetchone()

                    activos_info.append({
                        'ticker': accion['ticker'],
                        'volatilidad': float(volatilidad) if volatilidad is not None else 0.0,
                        'roi': round(float(roi), 2),
                        'sector': info_sector['sector'] if info_sector else 'Desconocido',
                        'diversidad': info_sector['diversidad_sectorial'] if info_sector else 'Otro',
                        'valor': round(cantidad * precio_actual, 2),
                        'precio_actual': precio_actual
                    })
            except Exception as e:
                print(f"Error obteniendo info de {accion.get('ticker')}: {e}")
                continue
        
        cursor.close()
        return activos_info
    
    def calcular_perfil_riesgo(self) -> dict:
        """
        Calcula el perfil de riesgo del usuario basado en su portafolio
        Retorna: {'perfil': 'Conservador'|'Moderado'|'Agresivo', 'volatilidad': float, 'diversificacion': int}
        """
        activos = self.obtener_info_acciones()
        
        if not activos:
            return {'perfil': 'Conservador', 'volatilidad': 0, 'diversificacion': 0, 'roi_promedio': 0, 'sectores': {}}
        
        # Volatilidad promedio del portafolio
        volatilidad_promedio = sum(a['volatilidad'] for a in activos) / len(activos)
        
        # ROI promedio
        roi_promedio = sum(a['roi'] for a in activos) / len(activos)
        
        # Calcular diversificación por sector
        sectores = defaultdict(int)
        valor_total = sum(a['valor'] for a in activos)
        
        for activo in activos:
            sectores[activo['sector']] += activo['valor']
        
        # Score de diversificación (0-100) usando índice de concentración (HHI normalizado)
        # 0 = concentración total en un sector, 100 = distribución uniforme entre sectores.
        num_sectores = len(sectores)
        distribucion_actual = {s: (v / valor_total) for s, v in sectores.items()} if valor_total > 0 else {}
        hhi = sum((peso ** 2) for peso in distribucion_actual.values())
        if num_sectores <= 1:
            diversificacion_score = 0.0
        else:
            diversificacion_score = ((1 - hhi) / (1 - (1 / num_sectores))) * 100
            diversificacion_score = max(0.0, min(100.0, diversificacion_score))
        
        # Determinar perfil de riesgo
        if volatilidad_promedio < 8:
            perfil = 'Conservador'
        elif volatilidad_promedio < 15:
            perfil = 'Moderado'
        else:
            perfil = 'Agresivo'
        
        return {
            'perfil': perfil,
            'volatilidad': round(volatilidad_promedio, 2),
            'diversificacion': int(diversificacion_score),
            'roi_promedio': round(roi_promedio, 2),
            'sectores': dict(sectores)
        }
    
    def generar_recomendaciones(self, cantidad: int = 5, actualizar: bool = False, excluir_tickers: Optional[List[str]] = None) -> list:
        """
        Genera recomendaciones personalizadas basadas en el perfil del usuario
        """
        perfil = self.calcular_perfil_riesgo()
        activos_usuario = [str(a['ticker']).upper() for a in self.obtener_acciones_usuario()]
        excluir_tickers = [str(t).upper() for t in (excluir_tickers or []) if str(t).strip()]
        tickers_excluidos = sorted(set(activos_usuario + excluir_tickers))
        sectores_usuario = {str(s).strip().lower() for s in (perfil.get('sectores') or {}).keys() if str(s).strip()}
        
        cursor = self.conexion.cursor(dictionary=True)
        
        # Mapeo de perfil a volatilidad
        if perfil['perfil'] == 'Conservador':
            volatilidad_filtro = 'Bajo'
            score_minimo = 85
        elif perfil['perfil'] == 'Moderado':
            volatilidad_filtro = 'Medio'
            score_minimo = 75
        else:  # Agresivo
            volatilidad_filtro = ['Alto', 'Medio']
            score_minimo = 60
        
        order_clause = "ORDER BY RAND()" if actualizar else "ORDER BY (puntuacion_seguridad + puntuacion_rentabilidad) / 2 DESC"

        def consultar_recomendaciones(
            min_seguridad: int,
            usar_filtro_volatilidad: bool = True,
            usar_exclusion_tickers: bool = True
        ):
            where_parts = ["puntuacion_seguridad >= %s"]
            params = [min_seguridad]

            if usar_filtro_volatilidad:
                if isinstance(volatilidad_filtro, list):
                    vol_placeholders = ', '.join(['%s'] * len(volatilidad_filtro))
                    where_parts.append(f"volatilidad_riesgo IN ({vol_placeholders})")
                    params.extend(volatilidad_filtro)
                else:
                    where_parts.append("volatilidad_riesgo = %s")
                    params.append(volatilidad_filtro)

            if usar_exclusion_tickers and tickers_excluidos:
                activos_placeholders = ', '.join(['%s'] * len(tickers_excluidos))
                where_parts.append(f"ticker NOT IN ({activos_placeholders})")
                params.extend(tickers_excluidos)

            query = f"""
                SELECT ticker, nombre, sector, puntuacion_seguridad, puntuacion_rentabilidad,
                       volatilidad_riesgo, diversidad_sectorial
                FROM acciones_recomendadas
                WHERE {' AND '.join(where_parts)}
                {order_clause}
                LIMIT %s
            """
            params.append(cantidad)
            cursor.execute(query, tuple(params))
            return cursor.fetchall()

        recomendaciones = consultar_recomendaciones(score_minimo, usar_filtro_volatilidad=True, usar_exclusion_tickers=True)

        if not recomendaciones:
            recomendaciones = consultar_recomendaciones(max(score_minimo - 15, 50), usar_filtro_volatilidad=True, usar_exclusion_tickers=True)

        if not recomendaciones:
            recomendaciones = consultar_recomendaciones(50, usar_filtro_volatilidad=True, usar_exclusion_tickers=False)

        if not recomendaciones:
            recomendaciones = consultar_recomendaciones(0, usar_filtro_volatilidad=False, usar_exclusion_tickers=False)
        
        resultado = []
        for rec in recomendaciones:
            score_combinado = (rec['puntuacion_seguridad'] + rec['puntuacion_rentabilidad']) / 2
            score_seguridad = int(rec['puntuacion_seguridad'])
            score_rentabilidad = int(rec['puntuacion_rentabilidad'])
            es_sector_nuevo = str(rec['sector']).strip().lower() not in sectores_usuario

            if perfil['perfil'] == 'Conservador':
                enfoque = f"encaja con tu perfil conservador ({rec['volatilidad_riesgo']})"
            elif perfil['perfil'] == 'Moderado':
                enfoque = f"equilibra riesgo-rendimiento para perfil moderado ({rec['volatilidad_riesgo']})"
            else:
                enfoque = f"aprovecha oportunidad de crecimiento para perfil agresivo ({rec['volatilidad_riesgo']})"

            diversificacion = "y abre exposición a un sector nuevo" if es_sector_nuevo else "y fortalece un sector que ya dominas"
            razon = f"{enfoque}; seguridad {score_seguridad}/100, rentabilidad {score_rentabilidad}/100 {diversificacion}."
            
            resultado.append({
                'ticker': rec['ticker'],
                'nombre': rec['nombre'],
                'sector': rec['sector'],
                'seguridad': rec['puntuacion_seguridad'],
                'rentabilidad': rec['puntuacion_rentabilidad'],
                'riesgo': rec['volatilidad_riesgo'],
                'score': round(score_combinado, 1),
                'razon': razon
            })
        
        cursor.close()
        return resultado
    
    def analizar_divergencia(self) -> dict:
        """Analiza qué tan diversificado está el portafolio"""
        perfil = self.calcular_perfil_riesgo()
        activos = self.obtener_info_acciones()
        
        sectores = defaultdict(int)
        for a in activos:
            sectores[a['sector']] += 1
        
        recomendaciones_diversidad = []
        
        # Si tiene más del 50% en un sector, recomendar diversificar
        valor_total = sum(a['valor'] for a in activos)
        for sector, valor in perfil['sectores'].items():
            porcentaje = (valor / valor_total * 100) if valor_total > 0 else 0
            if porcentaje > 50:
                recomendaciones_diversidad.append(
                    f"⚠️ {porcentaje:.0f}% del portafolio está en {sector}. Considera diversificar."
                )
        
        # Si tiene muy pocas acciones
        if len(activos) < 3:
            recomendaciones_diversidad.append(
                "📊 Considera agregar más acciones de diferentes sectores para reducir riesgo."
            )
        
        # Si la diversificación es baja
        if perfil['diversificacion'] < 40:
            recomendaciones_diversidad.append(
                f"🎯 Diversificación baja ({perfil['diversificacion']}%). Agrega sectores diferentes."
            )
        
        return {
            'score_diversificacion': perfil['diversificacion'],
            'recomendaciones': recomendaciones_diversidad if recomendaciones_diversidad else ["✅ Buen nivel de diversificación"],
            'composicion_sectorial': dict(perfil['sectores'])
        }
    
    def guardar_perfil(self):
        """Guarda el perfil calculado en la BD"""
        perfil = self.calcular_perfil_riesgo()
        cursor = self.conexion.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO perfil_usuario (user_id, perfil_riesgo, volatilidad_promedio, diversificacion_score, roi_promedio)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                perfil_riesgo = VALUES(perfil_riesgo),
                volatilidad_promedio = VALUES(volatilidad_promedio),
                diversificacion_score = VALUES(diversificacion_score),
                roi_promedio = VALUES(roi_promedio),
                fecha_calculo = CURRENT_TIMESTAMP
            """, (
                self.user_id,
                perfil['perfil'],
                perfil['volatilidad'],
                perfil['diversificacion'],
                perfil['roi_promedio']
            ))
            
            self.conexion.commit()
        except Exception as e:
            print(f"Error guardando perfil: {e}")
        finally:
            cursor.close()
    
    def cerrar(self):
        """Cierra la conexión a la BD"""
        self.conexion.close()
