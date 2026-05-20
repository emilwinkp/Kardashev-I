import pvlib
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

#1. Configuración básica
lat, lon = 25.6, -100.3
tz = 'Etc/GMT+6'
tiempos = pd.date_range(start= '2026-05-18 00:00', end='2026-05-18 23:59', freq='15min', tz=tz)

#2. Posición solar
sol = pvlib.solarposition.get_solarposition(tiempos, lat, lon)
zenith_vals = sol['apparent_zenith'].values
azimuth_vals = sol['azimuth'].values

#3. Modelo de cielo despejado (Jensen/Ineichen)
# Aquí clearsky sale como diccionario de arrays de numpy
clearsky = pvlib.clearsky.ineichen(zenith_vals, airmass_absolute=1.5, linke_turbidity=3, altitude=500)

#4. Transportación (Cákculo del panel)
#Quitar values porque ya son numeros puros
irradiance_total = pvlib.irradiance.get_total_irradiance(
    surface_tilt=25,
    surface_azimuth=180,
    solar_zenith=zenith_vals,
    solar_azimuth=azimuth_vals,
    dni=clearsky['dni'],
    ghi=clearsky['ghi'],
    dhi=clearsky['dhi']

)

#5. Graficar usando datos limpios
plt.figure(figsize=(10, 5))
plt.plot(tiempos, clearsky['ghi'], label='Radiación suelo (GHI)', color='blue')
plt.plot(tiempos, irradiance_total['poa_global'], label='Radiación Panel (POA)', color='orange', linewidth=2)

plt.title(f"Simulación de Radiación - Monterret (Lat {lat})")
plt.xlabel("hora del día")
plt.ylabel("Irrandiancia W/m^2")
plt.legend()
plt.grid(True, linestyles='--')
plt.xticks(rotation=45)
plt.show()

# Gráfica de componentes atmosféricos (GHI, DNI, DHI)