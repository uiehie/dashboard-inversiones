# 📊 Dashboard de Inversiones - Sistema de Recomendaciones

## 🌐 Enlaces Oficiales

- App en vivo (para entrar al sistema): https://uiehie.github.io/dashboard-inversiones/login.html
- Repositorio del proyecto: https://github.com/uiehie/dashboard-inversiones
- API en producción (Railway): https://dashboard-inversiones-production.up.railway.app/openapi.json

## 🚀 Nuevas Funcionalidades

Tu dashboard ahora incluye un **sistema inteligente de recomendaciones personalizadas** que:

✅ **Analiza tu perfil de riesgo** basado en el portafolio  
✅ **Recomienda acciones** seguras y rentables según tu perfil  
✅ **Sugiere diversificación** del portafolio  
✅ **Analiza la composición sectorial** actual  
✅ **Identifica riesgos** de concentración  

---

## 📋 Requisitos

```
- Python 3.8+
- FastAPI
- MySQL 8.0+
- yfinance
```

---

## 🔧 Instalación

### 1. **Actualizar las tablas de la BD**

Ejecuta el script SQL para crear las nuevas tablas:

```bash
mysql -u root -p < backend/schema.sql
```

Credenciales por defecto:
- Usuario: `root`
- Contraseña: `root1234`
- BD: `dashboard_inversiones`

### 2. **Instalar/actualizar dependencias Python**

```bash
pip install fastapi uvicorn mysql-connector-python pydantic yfinance python-jose passlib[bcrypt]
```

### 3. **Ejecutar el backend**

```bash
cd backend
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

### 4. **Abrir el frontend**

Acceder a:
```
file:///ruta/a/frontend/index.html
```

O servir con un servidor local:

```bash
# Usando Python
cd frontend
python -m http.server 8080

# Luego abrir: http://localhost:8080/index.html
```

---

## 📈 Cómo Funciona el Sistema

### **1. Perfil de Riesgo**

Se calcula automáticamente analizando:

- **Volatilidad promedio** de tus acciones
- **ROI histórico**
- **Diversificación por sector**

**Clasificación:**
- 🛡️ **Conservador**: Volatilidad < 8%
- ⚖️ **Moderado**: Volatilidad 8-15%
- 🚀 **Agresivo**: Volatilidad > 15%

### **2. Recomendaciones Personalizadas**

El sistema recomienda acciones basadas en:

1. **Tu perfil de riesgo** - Solo acciones compatibles con tu tolerancia
2. **Sectores no cubiertos** - Diversificación automática
3. **Puntuación de seguridad** - Prioriza empresas estables
4. **Potencial de crecimiento** - Balanceo riesgo/rendimiento

### **3. Análisis de Diversificación**

Evalúa:
- **Score de diversificación** (0-100)
- **Concentración por sector** - Alerta si >50% en un sector
- **Número de posiciones** - Sugiere agregar más activos si <3
- **Rebalanceo recomendado**

---

## 🔍 Endpoints Disponibles

### **Análisis Completomente Intelligente**

```
GET /analisis/completo
```

Retorna todo: perfil, recomendaciones, diversificación

```json
{
  "perfil_riesgo": {
    "perfil": "Moderado",
    "volatilidad": 12.45,
    "diversificacion": 68,
    "roi_promedio": 5.23
  },
  "recomendaciones": [
    {
      "ticker": "MSFT",
      "nombre": "Microsoft",
      "sector": "Tecnología",
      "seguridad": 96,
      "rentabilidad": 78,
      "riesgo": "Medio",
      "score": 87.0,
      "razon": "Acción segura y estable"
    }
  ],
  "diversificacion": {
    "score_diversificacion": 68,
    "recomendaciones": ["✅ Buen nivel de diversificación"],
    "composicion_sectorial": {"Tecnología": 50000, "Finanzas": 30000}
  }
}
```

### **Perfil de Riesgo**

```
GET /perfil/riesgo
```

### **Recomendaciones**

```
GET /recomendaciones?cantidad=5
```

### **Análisis de Diversificación**

```
GET /analisis/diversificacion
```

### **Listar Acciones Recomendadas**

```
GET /acciones/recomendadas?sector=Tecnología&volatilidad=Medio
```

---

## 🎯 Estrategias de Inversión por Perfil

### 🛡️ Conservador

Acciones con:
- Volatilidad baja
- Seguridad > 85/100
- Sectores: Finanzas, Salud, Consumo

**Ejemplos:** JNJ, PG, KO

### ⚖️ Moderado

Acciones con:
- Volatilidad media
- Seguridad > 75/100
- Mix de sectores

**Ejemplos:** MSFT, GOOGL, BAC

### 🚀 Agresivo

Acciones con:
- Volatilidad alta, alto crecimiento
- Seguridad > 60/100
- Tecnología, Innovación

**Ejemplos:** PLTR, TSLA, NFLX

---

## 💡 Recomendaciones de Uso

1. **Revisa tu perfil regularmente**
   - Se recalcula cada vez que accedes al dashboard
   - Cambia según tus inversiones

2. **Considera las recomendaciones como guías**
   - Siempre haz tu propia investigación
   - No es asesoramiento financiero

3. **Diversifica gradualmente**
   - No inviertas todo de una vez
   - Agrega 1-2 acciones recomendadas por mes

4. **Monitorea la composición**
   - Chequea el análisis de diversificación
   - Rebalancéa si algún sector supera 60%

---

## 🐛 Troubleshooting

### Error: "Cannot connect to MySQL"

```bash
# Verificar que MySQL está corriendo
mysql -u root -p
```

### Error: "Token inválido"

```javascript
// Limpiar localStorage y re-autenticarse
localStorage.clear();
window.location.href = 'login.html';
```

### Recomendaciones no cargan

1. Asegúrate de tener al menos 1 acción en el portafolio
2. Verifica que las tablas existan: `SHOW TABLES;`
3. Revisa la consola del navegador (F12) para errores

---

## 📊 Base de Datos - Acciones Disponibles

Se incluyen 17 acciones recomendadas en categorías:

**Verde (Seguras):**
- AAPL, MSFT, JNJ, PG, KO

**Naranja (Moderadas):**
- NVDA, TSLA, META, GOOGL, AMZN, BAC, XOM

**Rojo (Agresivas):**
- PLTR, ARKK, NFLX, TME, LMT

---

## 🔐 Seguridad

- ✅ Contraseñas hasheadas con bcrypt
- ✅ JWT para autenticación
- ✅ Datos aislados por usuario
- ✅ Análisis en tiempo real

---

## 📝 Licencia

Este proyecto es educativo. No es asesoramiento financiero.

**Ronda de inversión es tu responsabilidad.**

---

## 🤝 Soporte

Para problemas o preguntas:
1. Revisa el schema.sql
2. Verifica los logs del servidor
3. Comprueba la conexión MySQL
