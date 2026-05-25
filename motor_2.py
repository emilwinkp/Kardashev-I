import pvlib
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import sys

#1. Inputs espacio-temporales

#1.1 Ubicación planetaria
lat, lon = float(input("Inserta Latitud")), float(input("Inserta Longitud"))

#1.2 Zona de tiempo
tz = str(input("Inseerta zona de horario: Etc/GMT(+-#)"))

#1.3 Cantidad de tiempo (Todo un año)
tiempos = pd.date_range(start= '2026-01-01 00:00', end='2026-12-31 23:59', freq='15min', tz=tz)

#1.4 Inclinación solar
st = float(input("Inserta ángulo de inclinación"))
if st > 90:
    print('No se considera un panel solar con esa inclinación')
    sys.exit()

#1.5 Azimut del panel
azimuth_panel = float(input("Inserta azimut del panel"))
if azimuth_panel < 0 or azimuth_panel > 360:
    print('El azimut del panel debe estar entre 0 y 360 grados')
    sys.exit()

#2. Posición solar
sol = pvlib.solarposition.get_solarposition(tiempos, lat, lon)
zenith_vals = sol['apparent_zenith'].values
azimuth_vals = sol['azimuth'].values

#3. Modelo de cielo despejado (Jensen/Ineichen)
# Aquí clearsky sale como diccionario de arrays de numpy
clearsky = pvlib.clearsky.ineichen(zenith_vals, airmass_absolute=1.5, linke_turbidity=3, altitude=500)

#4. Transportación (Cálculo del panel)
#Quitar values porque ya son numeros puros
irradiance_total = pvlib.irradiance.get_total_irradiance(
    surface_tilt=st,
    surface_azimuth=azimuth_panel,
    solar_zenith=zenith_vals,
    solar_azimuth=azimuth_vals,
    dni=clearsky['dni'],
    ghi=clearsky['ghi'],
    dhi=clearsky['dhi']
)

print(irradiance_total)

df_irradiacion = pd.DataFrame(irradiance_total)

#5. Información de sistema PV
area = 2
efficiency = float(input("Inserta eficiencia del panel (en decimal)"))
if efficiency < 0 or efficiency > 1:
    print('La eficiencia debe ser un valor entre 0 y 1')
    sys.exit() 

PR = float(input("Inserta Performance Ratio (en decimal)"))
if PR < 0 or PR > 1:
    print('El Performance Ratio debe ser un valor entre 0 y 1')
    sys.exit()  

cant_paneles = int(input("Inserta cantidad de paneles"))

#6. Cálculo de potencia generada
df_irradiacion['potencia_generada'] = df_irradiacion['poa_global'] * area * efficiency * PR * cant_paneles
print(df_irradiacion['potencia_generada'])
potencia_gen_ano = df_irradiacion['potencia_generada'].sum()
print(potencia_gen_ano)
