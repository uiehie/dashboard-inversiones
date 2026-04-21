from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
try:
    from .db import obtener_conexion
    from .analizador import AnalizadorPortafolio
    from .alertas import gestor_alertas
    from .backtesting import BacktestConfig, run_sma_crossover_backtest
except ImportError:
    from db import obtener_conexion
    from analizador import AnalizadorPortafolio
    from alertas import gestor_alertas
    from backtesting import BacktestConfig, run_sma_crossover_backtest
import yfinance as yf
from fastapi.security import OAuth2PasswordRequestForm
from fastapi import Form
import csv
import io
import zipfile

from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, Response
from fastapi.security import OAuth2PasswordBearer
from datetime import datetime, timedelta
from xml.sax.saxutils import escape

import json


# ------- Funciones de seguridad ------

SECRET_KEY = "super_secret_key_cambiala"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

def hash_password(password: str):
    return pwd_context.hash(password)

def verify_password(plain, hashed):
    return pwd_context.verify(plain, hashed)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Token inválido")
        return int(user_id)
    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido")


# ------------------ APP ------------------
app = FastAPI(
    title="Dashboard de Inversiones",
    version="1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------ CONFIG API ------------------
API_KEY = "e518aa45b2da4d35be81328ce8c55fb8"
BASE_URL = "https://api.twelvedata.com"

# ------------------ MODELOS ------------------
class Accion(BaseModel):
    ticker: str
    cantidad: int

class Usuario(BaseModel):
    username: str
    password: str


class BacktestRequest(BaseModel):
    ticker: str
    period: str = "1y"
    initial_capital: float = 10000.0
    fast_window: int = 20
    slow_window: int = 50
    commission_pct: float = 0.1
    slippage_pct: float = 0.05


# ------------------ HELPERS ------------------
def obtener_precio_actual(ticker: str) -> float:
    try:
        accion = yf.Ticker(ticker)
        data = accion.history(period="1d")

        if data.empty:
            return 0.0

        return float(data["Close"].iloc[-1])
    except Exception as e:
        print("Error precio:", e)
        return 0.0


def _excel_col_name(index: int) -> str:
    """Convierte índice 1-based a nombre de columna Excel (A, B, ..., AA)."""
    name = ""
    while index > 0:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def _build_sheet_xml(headers: list, rows: list) -> str:
    def cell_xml(value, row_idx, col_idx):
        cell_ref = f"{_excel_col_name(col_idx)}{row_idx}"
        if isinstance(value, bool):
            value = "TRUE" if value else "FALSE"
        if isinstance(value, (int, float)) and value is not None:
            return f'<c r="{cell_ref}"><v>{value}</v></c>'
        text = "" if value is None else str(value)
        return f'<c r="{cell_ref}" t="inlineStr"><is><t>{escape(text)}</t></is></c>'

    xml_rows = []
    all_rows = [headers] + rows

    for r_idx, row in enumerate(all_rows, start=1):
        row_cells = "".join(cell_xml(v, r_idx, c_idx) for c_idx, v in enumerate(row, start=1))
        xml_rows.append(f'<row r="{r_idx}">{row_cells}</row>')

    max_col = _excel_col_name(len(headers)) if headers else "A"
    max_row = len(all_rows) if all_rows else 1
    dimension = f"A1:{max_col}{max_row}"

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="{dimension}"/>'
        '<sheetViews><sheetView workbookViewId="0"/></sheetViews>'
        '<sheetFormatPr defaultRowHeight="15"/>'
        f'<sheetData>{"".join(xml_rows)}</sheetData>'
        '</worksheet>'
    )


def _build_xlsx_bytes(sheets: list) -> bytes:
    """
    Genera un archivo .xlsx minimalista con strings inline.
    sheets: [{'name': str, 'headers': list, 'rows': list[list]}]
    """
    content_types = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    ]

    workbook_sheets = []
    workbook_rels = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    ]

    for i, sheet in enumerate(sheets, start=1):
        content_types.append(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
        safe_name = escape(sheet['name'])
        workbook_sheets.append(
            f'<sheet name="{safe_name}" sheetId="{i}" r:id="rId{i}"/>'
        )
        workbook_rels.append(
            f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
        )

    content_types.append('</Types>')
    workbook_rels.append('</Relationships>')

    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets>{"".join(workbook_sheets)}</sheets>'
        '</workbook>'
    )

    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        '</Relationships>'
    )

    mem = io.BytesIO()
    with zipfile.ZipFile(mem, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "".join(content_types))
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", "".join(workbook_rels))

        for i, sheet in enumerate(sheets, start=1):
            sheet_xml = _build_sheet_xml(sheet['headers'], sheet['rows'])
            zf.writestr(f"xl/worksheets/sheet{i}.xml", sheet_xml)

    return mem.getvalue()


# ------------------ ROOT ------------------
@app.get("/")
def inicio():
    return {"mensaje": "API funcionando 🚀"}


# ------------------ PORTAFOLIO ------------------
@app.post("/portafolio/agregar")
def agregar_accion(accion: Accion, user_id: int = Depends(get_current_user)):
    precio_actual = obtener_precio_actual(accion.ticker)

    if precio_actual <= 0:
        return {"error": "No se pudo obtener el precio actual"}

    conexion = obtener_conexion()
    cursor = conexion.cursor()

    cursor.execute("""
        INSERT INTO portafolio (ticker, cantidad, precio_compra, fecha_compra, user_id)
        VALUES (%s, %s, %s, CURDATE(), %s)
    """, (
        accion.ticker.upper(),
        accion.cantidad,
        precio_actual,
        user_id
    ))

    conexion.commit()
    cursor.close()
    conexion.close()
    
    # Registrar en historial
    gestor_alertas.registrar_transaccion(
        user_id, "compra", accion.ticker.upper(),
        cantidad=accion.cantidad, precio=precio_actual
    )

    return {
        "mensaje": "Acción agregada correctamente",
        "ticker": accion.ticker.upper(),
        "precio_compra": round(precio_actual, 2)
    }


@app.get("/portafolio")
def ver_portafolio(user_id: int = Depends(get_current_user)):
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM portafolio WHERE user_id = %s",
        (user_id,)
    )
    data = cursor.fetchall()

    cursor.close()
    conexion.close()

    return data


@app.delete("/portafolio/eliminar/{id}")
def eliminar_accion(id: int, user_id: int = Depends(get_current_user)):
    conexion = obtener_conexion()
    cursor = conexion.cursor()

    cursor.execute(
        "DELETE FROM portafolio WHERE id = %s AND user_id = %s",
        (id, user_id)
    )
    conexion.commit()

    filas = cursor.rowcount

    cursor.close()
    conexion.close()

    return {"mensaje": "Eliminado"} if filas else {"mensaje": "No encontrado"}


# ------------------ ANALISIS ------------------
@app.get("/portafolio/analisis")
def analisis_portafolio(user_id: int = Depends(get_current_user)):
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM portafolio WHERE user_id = %s",
        (user_id,)
    )
    acciones = cursor.fetchall()

    resultado = []

    for a in acciones:
        cantidad = int(a["cantidad"])
        precio_compra = float(a["precio_compra"])
        precio_actual = float(obtener_precio_actual(a["ticker"]))

        invertido = cantidad * precio_compra
        valor_actual = cantidad * precio_actual
        ganancia = valor_actual - invertido
        roi = (ganancia / invertido * 100) if invertido > 0 else 0

        resultado.append({
            "id": a["id"],
            "ticker": a["ticker"],
            "cantidad": cantidad,
            "precio_compra": round(precio_compra, 2),
            "precio_actual": round(precio_actual, 2),
            "invertido": round(invertido, 2),
            "ganancia": round(ganancia, 2),
            "roi": round(roi, 2)
        })

    cursor.close()
    conexion.close()

    return resultado


# ------------------ DASHBOARD ------------------
@app.get("/dashboard/resumen")
def resumen_dashboard(user_id: int = Depends(get_current_user)):
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM portafolio WHERE user_id = %s",
        (user_id,)
    )
    acciones = cursor.fetchall()

    total_invertido = 0.0
    valor_actual = 0.0

    for a in acciones:
        cantidad = int(a["cantidad"])
        precio_compra = float(a["precio_compra"])
        precio_actual = float(obtener_precio_actual(a["ticker"]))

        total_invertido += cantidad * precio_compra
        valor_actual += cantidad * precio_actual

    ganancia = valor_actual - total_invertido
    roi = (ganancia / total_invertido * 100) if total_invertido > 0 else 0

    cursor.close()
    conexion.close()

    return {
        "total_invertido": round(total_invertido, 2),
        "valor_actual": round(valor_actual, 2),
        "ganancia_total": round(ganancia, 2),
        "roi_porcentaje": round(roi, 2),
        "total_acciones": len(acciones)
    }


# ------------------ ROI POR ACCION ------------------
@app.get("/acciones/roi/{ticker}")
def roi_por_accion(ticker: str, user_id: int = Depends(get_current_user)):
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)

    cursor.execute(
        "SELECT cantidad, precio_compra FROM portafolio WHERE ticker = %s AND user_id = %s",
        (ticker.upper(), user_id)
    )

    acciones = cursor.fetchall()

    if not acciones:
        cursor.close()
        conexion.close()
        return {
            "ticker": ticker.upper(),
            "ganancia": 0,
            "roi": 0
        }

    total_invertido = 0
    total_cantidad = 0

    for accion in acciones:
        total_invertido += float(accion["cantidad"]) * float(accion["precio_compra"])
        total_cantidad += float(accion["cantidad"])

    precio_actual = float(obtener_precio_actual(ticker))
    valor_actual = total_cantidad * precio_actual

    ganancia = valor_actual - total_invertido
    roi = (ganancia / total_invertido) * 100 if total_invertido > 0 else 0

    cursor.close()
    conexion.close()

    return {
        "ticker": ticker.upper(),
        "ganancia": round(ganancia, 2),
        "roi": round(roi, 2)
    }



# ------------------ AUTH ------------------
@app.post("/register")
def register(usuario: Usuario):
    conexion = obtener_conexion()
    cursor = conexion.cursor()

    hashed = hash_password(usuario.password)

    try:
        cursor.execute(
            "INSERT INTO usuarios (username, password) VALUES (%s, %s)",
            (usuario.username, hashed)
        )
        conexion.commit()
    except:
        raise HTTPException(status_code=400, detail="Usuario ya existe")

    cursor.close()
    conexion.close()

    return {"mensaje": "Usuario creado"}


@app.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM usuarios WHERE username = %s",
        (form_data.username,)
    )
    user = cursor.fetchone()

    cursor.close()
    conexion.close()

    if not user or not verify_password(form_data.password, user["password"]):
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")

    access_token = create_access_token({"sub": str(user["id"])})

    return {
        "access_token": access_token,
        "token_type": "bearer"
    }
# ------------------ HISTORICO POR ACCION ------------------
@app.get("/acciones/historico/{ticker}")
def historico_accion(ticker: str, user_id: int = Depends(get_current_user)):
    try:
        accion = yf.Ticker(ticker.upper())
        data = accion.history(period="3mo")  # últimos 3 meses

        if data.empty:
            return {"ticker": ticker.upper(), "historico": []}

        historico = []

        for fecha, fila in data.iterrows():
            historico.append({
                "fecha": fecha.strftime("%Y-%m-%d"),
                "cierre": round(float(fila["Close"]), 2)
            })

        return {
            "ticker": ticker.upper(),
            "historico": historico
        }

    except Exception as e:
        print("Error historico:", e)
        return {"ticker": ticker.upper(), "historico": []}


# ========== 🆕 RECOMENDACIONES E INTELIGENCIA ==========

@app.get("/perfil/riesgo")
def obtener_perfil_riesgo(user_id: int = Depends(get_current_user)):
    """
    Retorna el perfil de riesgo del usuario basado en su portafolio
    """
    analizador = AnalizadorPortafolio(user_id)
    perfil = analizador.calcular_perfil_riesgo()
    analizador.guardar_perfil()
    analizador.cerrar()
    
    return perfil


@app.get("/recomendaciones")
def obtener_recomendaciones(cantidad: int = 5, actualizar: bool = False, excluir: str = "", user_id: int = Depends(get_current_user)):
    """
    Retorna acciones recomendadas personalizadas según el perfil del usuario
    """
    analizador = AnalizadorPortafolio(user_id)
    excluir_tickers = [x.strip().upper() for x in excluir.split(',') if x.strip()]
    recomendaciones = analizador.generar_recomendaciones(
        cantidad,
        actualizar=actualizar,
        excluir_tickers=excluir_tickers
    )
    analizador.cerrar()
    
    return {"recomendaciones": recomendaciones}


@app.get("/analisis/diversificacion")
def analizar_diversificacion(user_id: int = Depends(get_current_user)):
    """
    Analiza el nivel de diversificación del portafolio
    """
    analizador = AnalizadorPortafolio(user_id)
    analisis = analizador.analizar_divergencia()
    analizador.cerrar()
    
    return analisis


@app.get("/analisis/completo")
def analisis_portafolio_completo(user_id: int = Depends(get_current_user)):
    """
    Retorna un análisis completo del portafolio incluyendo:
    - Perfil de riesgo
    - Recomendaciones
    - Análisis de diversificación
    """
    analizador = AnalizadorPortafolio(user_id)
    
    perfil = analizador.calcular_perfil_riesgo()
    recomendaciones = analizador.generar_recomendaciones(5)
    diversificacion = analizador.analizar_divergencia()
    
    analizador.guardar_perfil()
    analizador.cerrar()
    
    return {
        "perfil_riesgo": perfil,
        "recomendaciones": recomendaciones,
        "diversificacion": diversificacion,
        "fecha_analisis": datetime.utcnow().isoformat()
    }


@app.get("/acciones/recomendadas")
def listar_acciones_recomendadas(sector: str = None, volatilidad: str = None):
    """
    Lista todas las acciones recomendadas disponibles
    Filtrable por sector y nivel de volatilidad
    """
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)
    
    query = "SELECT * FROM acciones_recomendadas WHERE 1=1"
    params = []
    
    if sector:
        query += " AND sector = %s"
        params.append(sector)
    
    if volatilidad and volatilidad in ['Bajo', 'Medio', 'Alto']:
        query += " AND volatilidad_riesgo = %s"
        params.append(volatilidad)
    
    query += " ORDER BY puntuacion_seguridad DESC"
    
    cursor.execute(query, params)
    acciones = cursor.fetchall()
    
    cursor.close()
    conexion.close()
    
    return {
        "acciones": acciones,
        "total": len(acciones)
    }


# ============== 🆕 ALERTAS DE PRECIO ==============
# Crear tablas al iniciar la app
gestor_alertas.crear_tabla_alertas()

@app.post("/alertas/crear")
def crear_alerta(ticker: str = Form(...), tipo: str = Form(...), precio_objetivo: float = Form(...), 
                user_id: int = Depends(get_current_user)):
    """Crea una alerta de precio para una acción"""
    respuesta = gestor_alertas.crear_alerta(user_id, ticker, tipo, precio_objetivo)
    # Registrar en historial
    gestor_alertas.registrar_transaccion(user_id, "alerta", ticker, 
                                         detalles=f"Alerta {tipo} a ${precio_objetivo}")
    return respuesta


@app.get("/alertas")
def obtener_alertas(user_id: int = Depends(get_current_user)):
    """Obtiene todas las alertas del usuario"""
    alertas = gestor_alertas.obtener_alertas_usuario(user_id)
    return {"alertas": alertas, "total": len(alertas)}


@app.delete("/alertas/{alerta_id}")
def eliminar_alerta(alerta_id: int, user_id: int = Depends(get_current_user)):
    """Elimina una alerta de precio"""
    return gestor_alertas.eliminar_alerta(user_id, alerta_id)


# ============== 📝 HISTORIAL ==============
@app.get("/historial/transacciones")
def obtener_historial(limite: int = 50, user_id: int = Depends(get_current_user)):
    """Obtiene el historial de transacciones del usuario"""
    historial = gestor_alertas.obtener_historial_usuario(user_id, limite)
    return {"historial": historial, "total": len(historial)}


# ============== 🧮 CALCULADORA ==============
@app.post("/calculadora/simular")
def simular_inversion(ticker: str = Form(...), cantidad: int = Form(...), 
                     precio_actual: float = Form(...), roi_esperado: float = Form(...),
                     user_id: int = Depends(get_current_user)):
    """Simula ganancias potenciales de una inversión"""
    inversion_inicial = cantidad * precio_actual
    ganancia_esperada = inversion_inicial * (roi_esperado / 100)
    valor_final = inversion_inicial + ganancia_esperada
    precio_futuro = valor_final / cantidad
    
    return {
        "ticker": ticker.upper(),
        "inversion_inicial": round(inversion_inicial, 2),
        "roi_esperado": roi_esperado,
        "ganancia_esperada": round(ganancia_esperada, 2),
        "valor_final": round(valor_final, 2),
        "precio_futuro": round(precio_futuro, 2),
        "precio_actual": precio_actual
    }


# ============== 📈 BACKTESTING ==============
@app.post("/backtesting/estrategia")
def ejecutar_backtesting(config: BacktestRequest, user_id: int = Depends(get_current_user)):
    """
    Ejecuta un backtesting con estrategia de cruce de medias moviles (SMA)
    y compara contra benchmark Buy & Hold.
    """
    if config.fast_window <= 0 or config.slow_window <= 0:
        raise HTTPException(status_code=400, detail="Las ventanas SMA deben ser mayores a 0")

    if config.fast_window >= config.slow_window:
        raise HTTPException(status_code=400, detail="SMA rapida debe ser menor que SMA lenta")

    if config.initial_capital <= 0:
        raise HTTPException(status_code=400, detail="El capital inicial debe ser mayor a 0")

    if config.commission_pct < 0 or config.slippage_pct < 0:
        raise HTTPException(status_code=400, detail="Comision y slippage no pueden ser negativos")

    try:
        resultado = run_sma_crossover_backtest(
            BacktestConfig(
                ticker=config.ticker,
                period=config.period,
                initial_capital=config.initial_capital,
                fast_window=config.fast_window,
                slow_window=config.slow_window,
                commission_pct=config.commission_pct,
                slippage_pct=config.slippage_pct,
            )
        )
        return resultado
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error ejecutando backtesting: {str(e)}")


# ============== 📥 EXPORTAR ==============
@app.get("/exportar/json")
def exportar_portafolio_json(user_id: int = Depends(get_current_user)):
    """Exporta portafolio, historial y analisis inteligente en formato JSON"""
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)
    
    # Portafolio
    cursor.execute("SELECT * FROM portafolio WHERE user_id = %s", (user_id,))
    portafolio = cursor.fetchall()
    
    # Historial
    cursor.execute(
        "SELECT * FROM historial_transacciones WHERE user_id = %s ORDER BY fecha DESC",
        (user_id,)
    )
    historial = cursor.fetchall()
    
    cursor.close()
    conexion.close()
    
    # Convertir Decimales a float
    for p in portafolio:
        if 'precio_compra' in p and p['precio_compra']:
            p['precio_compra'] = float(p['precio_compra'])
        if 'cantidad' in p:
            p['cantidad'] = int(p['cantidad'])
    
    for h in historial:
        if 'precio' in h and h['precio']:
            h['precio'] = float(h['precio'])
        if 'monto' in h and h['monto']:
            h['monto'] = float(h['monto'])
        if 'cantidad' in h and h['cantidad']:
            h['cantidad'] = int(h['cantidad'])

    total_invertido = sum(float(p.get('cantidad', 0)) * float(p.get('precio_compra', 0)) for p in portafolio)

    analizador = AnalizadorPortafolio(user_id)
    perfil = analizador.calcular_perfil_riesgo()
    diversificacion = analizador.analizar_divergencia()
    recomendaciones = analizador.generar_recomendaciones(6)
    analizador.cerrar()
    
    return {
        "fecha_exportacion": datetime.utcnow().isoformat(),
        "formato": "json",
        "portafolio": portafolio,
        "historial": historial,
        "analisis_inteligente": {
            "perfil_riesgo": perfil,
            "diversificacion": diversificacion,
            "recomendaciones": recomendaciones
        },
        "resumen": {
            "total_acciones": len(portafolio),
            "total_transacciones": len(historial),
            "total_invertido_estimado": round(total_invertido, 2)
        }
    }


@app.get("/exportar/csv")
def exportar_portafolio_csv(user_id: int = Depends(get_current_user)):
    """Exporta una hoja CSV compatible con Excel"""
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)

    cursor.execute(
        "SELECT ticker, cantidad, precio_compra, fecha_compra FROM portafolio WHERE user_id = %s",
        (user_id,)
    )
    portafolio = cursor.fetchall()

    cursor.close()
    conexion.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Ticker",
        "Cantidad",
        "Precio Compra",
        "Precio Actual",
        "Invertido",
        "Valor Actual",
        "Ganancia",
        "ROI %",
        "Fecha Compra"
    ])

    for row in portafolio:
        ticker = str(row.get("ticker", "")).upper()
        cantidad = int(row.get("cantidad") or 0)
        precio_compra = float(row.get("precio_compra") or 0)
        precio_actual = float(obtener_precio_actual(ticker))

        invertido = cantidad * precio_compra
        valor_actual = cantidad * precio_actual
        ganancia = valor_actual - invertido
        roi = ((ganancia / invertido) * 100) if invertido > 0 else 0

        fecha = row.get("fecha_compra")
        fecha_str = fecha.isoformat() if hasattr(fecha, "isoformat") else str(fecha or "")

        writer.writerow([
            ticker,
            cantidad,
            round(precio_compra, 2),
            round(precio_actual, 2),
            round(invertido, 2),
            round(valor_actual, 2),
            round(ganancia, 2),
            round(roi, 2),
            fecha_str
        ])

    csv_content = "\ufeff" + output.getvalue()
    output.close()

    fecha_archivo = datetime.utcnow().strftime("%Y-%m-%d")
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=portafolio_{fecha_archivo}.csv"}
    )


@app.get("/exportar/xlsx")
def exportar_portafolio_xlsx(user_id: int = Depends(get_current_user)):
    """Exporta un archivo Excel .xlsx con varias hojas."""
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)

    cursor.execute(
        "SELECT ticker, cantidad, precio_compra, fecha_compra FROM portafolio WHERE user_id = %s",
        (user_id,)
    )
    portafolio = cursor.fetchall()

    cursor.execute(
        "SELECT fecha, tipo, ticker, cantidad, precio, monto, detalles FROM historial_transacciones WHERE user_id = %s ORDER BY fecha DESC",
        (user_id,)
    )
    historial = cursor.fetchall()

    cursor.close()
    conexion.close()

    analizador = AnalizadorPortafolio(user_id)
    perfil = analizador.calcular_perfil_riesgo()
    diversificacion = analizador.analizar_divergencia()
    recomendaciones = analizador.generar_recomendaciones(6)
    analizador.cerrar()

    rows_portafolio = []
    for row in portafolio:
        ticker = str(row.get("ticker", "")).upper()
        cantidad = int(row.get("cantidad") or 0)
        precio_compra = float(row.get("precio_compra") or 0)
        precio_actual = float(obtener_precio_actual(ticker))

        invertido = cantidad * precio_compra
        valor_actual = cantidad * precio_actual
        ganancia = valor_actual - invertido
        roi = ((ganancia / invertido) * 100) if invertido > 0 else 0

        fecha = row.get("fecha_compra")
        fecha_str = fecha.isoformat() if hasattr(fecha, "isoformat") else str(fecha or "")

        rows_portafolio.append([
            ticker,
            cantidad,
            round(precio_compra, 2),
            round(precio_actual, 2),
            round(invertido, 2),
            round(valor_actual, 2),
            round(ganancia, 2),
            round(roi, 2),
            fecha_str
        ])

    rows_historial = []
    for h in historial:
        fecha = h.get("fecha")
        fecha_str = fecha.isoformat() if hasattr(fecha, "isoformat") else str(fecha or "")
        rows_historial.append([
            fecha_str,
            h.get("tipo", ""),
            h.get("ticker", ""),
            int(h.get("cantidad") or 0),
            float(h.get("precio") or 0),
            float(h.get("monto") or 0),
            h.get("detalles", "") or ""
        ])

    rows_analisis = [
        ["Perfil", perfil.get("perfil", "—")],
        ["Volatilidad %", perfil.get("volatilidad", 0)],
        ["ROI Promedio %", perfil.get("roi_promedio", 0)],
        ["Diversificacion %", diversificacion.get("score_diversificacion", 0)],
        ["", ""],
        ["Recomendaciones", ""],
    ]
    for rec in recomendaciones:
        rows_analisis.append([
            rec.get("ticker", ""),
            f"{rec.get('nombre', '')} | {rec.get('razon', '')}"
        ])

    sheets = [
        {
            "name": "Portafolio",
            "headers": ["Ticker", "Cantidad", "Precio Compra", "Precio Actual", "Invertido", "Valor Actual", "Ganancia", "ROI %", "Fecha Compra"],
            "rows": rows_portafolio
        },
        {
            "name": "Historial",
            "headers": ["Fecha", "Tipo", "Ticker", "Cantidad", "Precio", "Monto", "Detalles"],
            "rows": rows_historial
        },
        {
            "name": "Analisis",
            "headers": ["Campo", "Valor"],
            "rows": rows_analisis
        }
    ]

    xlsx_bytes = _build_xlsx_bytes(sheets)
    fecha_archivo = datetime.utcnow().strftime("%Y-%m-%d")
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=portafolio_{fecha_archivo}.xlsx"}
    )


# ============== 🏆 BADGES/LOGROS ==============
@app.get("/logros")
def obtener_logros(user_id: int = Depends(get_current_user)):
    """Obtiene los logros desbloqueados del usuario"""
    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)
    
    # Obtener datos del portafolio
    cursor.execute("SELECT * FROM portafolio WHERE user_id = %s", (user_id,))
    portafolio = cursor.fetchall()
    
    cursor.execute("SELECT * FROM historial_transacciones WHERE user_id = %s", (user_id,))
    historial = cursor.fetchall()
    
    cursor.close()
    conexion.close()
    
    logros = []
    
    # Calcula ROI total
    total_invertido = sum(float(p.get('cantidad', 0)) * float(p.get('precio_compra', 0)) 
                         for p in portafolio)
    
    # Lógica de logros
    if len(portafolio) >= 1:
        logros.append({"id": 1, "nombre": "Primer paso", "descripcion": "Agrega tu primera acción", 
                      "emoji": "🎯", "desbloqueado": True})
    
    if len(portafolio) >= 5:
        logros.append({"id": 2, "nombre": "Diversificado", "descripcion": "Tienes 5 o más acciones", 
                      "emoji": "📊", "desbloqueado": True})
    
    if len(portafolio) >= 10:
        logros.append({"id": 3, "nombre": "Coleccionista", "descripcion": "Tienes 10 o más acciones", 
                      "emoji": "🏆", "desbloqueado": True})
    
    if len(historial) >= 10:
        logros.append({"id": 4, "nombre": "Operador activo", "descripcion": "10+ transacciones", 
                      "emoji": "⚡", "desbloqueado": True})
    
    if total_invertido >= 10000:
        logros.append({"id": 5, "nombre": "Inversor serio", "descripcion": "$10,000+ invertidos", 
                      "emoji": "💰", "desbloqueado": True})
    
    return {"logros": logros, "total_desbloqueados": len(logros)}

