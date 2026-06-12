---
title: Kardashev-I Simulador Solar
emoji: ☀️
colorFrom: yellow
colorTo: orange
sdk: docker
app_port: 7860
pinned: false
---

# Kardashev-I — Simulador Solar Fotovoltaico

Simulador de generación solar FV basado en datos geoespaciales reales, geometría solar e irradiancia POA (modelo Jensen + clear-sky Ineichen).

---

## Requisitos previos

- Python 3.10 o superior
- `pip` actualizado
- [ngrok](https://ngrok.com/download) (solo si necesitas exponer la app fuera de tu red local)

---

## Instalación

```powershell
# 1. Clona el repositorio
git clone https://github.com/emilwinkp/Kardashev-I.git
cd Kardashev-I

# 2. Crea y activa un entorno virtual
python -m venv .venv
.venv\Scripts\Activate.ps1

# 3. Instala las dependencias
pip install -r requirements.txt
```

> Si PowerShell bloquea la ejecución de scripts, abre una terminal como administrador y ejecuta:
> `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

---

## Correr la app localmente

```powershell
python app.py
```

Abre tu navegador en `http://localhost:8050`.

El puerto puede sobreescribirse con la variable de entorno `PORT`:

```powershell
$env:PORT = "8080"; python app.py
```

---

## Exponer la app con ngrok

Usa ngrok cuando necesites compartir la app con alguien fuera de tu red (cliente, compañero, demo remota).

### 1. Instalar ngrok

Descarga el ejecutable desde [ngrok.com/download](https://ngrok.com/download), descomprímelo y agrégalo al PATH, **o** instálalo con winget:

```powershell
winget install ngrok.ngrok
```

### 2. Autenticar ngrok (solo la primera vez)

Crea una cuenta gratuita en [ngrok.com](https://ngrok.com) y copia tu authtoken desde el dashboard. Luego:

```powershell
ngrok config add-authtoken <TU_AUTHTOKEN>
```

### 3. Iniciar la app y el túnel

Abre **dos terminales**:

**Terminal 1 — App:**
```powershell
.venv\Scripts\Activate.ps1
python app.py
```

**Terminal 2 — ngrok:**
```powershell
ngrok http 8050
```

ngrok mostrará una URL pública del estilo `https://xxxx-xx-xx-xxx-xx.ngrok-free.app`. Comparte esa URL; cualquier persona con acceso a internet podrá abrir la app.

> Si cambiaste el puerto con `$env:PORT`, usa ese mismo número en el comando `ngrok http <puerto>`.

### Notas sobre ngrok gratuito

| Limitación | Valor |
|---|---|
| Sesiones simultáneas | 1 |
| Ancho de banda | Sin límite declarado (fair-use) |
| URL fija | No (cambia cada sesión); necesitas plan pago para dominio fijo |
| Tiempo de sesión | Sin límite en plan gratuito actual |

---

## Estructura del proyecto

```
Kardashev-I/
├── app.py            # Entrada principal — UI Dash + callbacks
├── motor_2.py        # Motor de física FV (no modificar)
├── motor.py          # Versión anterior del motor (referencia)
├── prueba_motor.py   # Script de pruebas del motor
├── requirements.txt  # Dependencias Python
└── assets/           # CSS, JS e imágenes estáticas (Dash los sirve automáticamente)
```

---

## Dependencias principales

| Paquete | Uso |
|---|---|
| `dash` | Framework web reactivo |
| `dash-leaflet` | Mapa interactivo de ubicación |
| `dash-bootstrap-components` | Componentes UI adicionales |
| `pvlib` | Cálculos de geometría solar e irradiancia |
| `plotly` | Gráficas interactivas |
| `pandas` / `numpy` | Procesamiento de series de tiempo |

---

## Autores

- Emil Winkler
- Andres Riojas
- Carlos Ramirez
- David Bueno
- Marco Reyes
- Elsa Lazcano
