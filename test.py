import pandas as pd 
import numpy as np
import matplotlib.pyplot as plt
import os 

os.chdir(os.path.dirname(os.path.abspath(__file__)))

df = pd.read_csv('perfil_energia_cfe.csv')


#PV = pd.read_csv()

#Cargos en MXN

cargo_mensual_fijo = 650 
cargo_por_distribución = 140 #Por kW
cargo_por_capacidad = 380 #Por kW
cargo_base = 0.95 #Por kWh
cargo_intermedia = 1.45 #Por kWh
cargo_punta = 2.15 #Por kWh

##Primero, los cargos por uso de energía

df['Fecha_Hora'] = pd.to_datetime(df['Fecha_Hora'])
df.set_index('Fecha_Hora', inplace=True)

df['Mes'] = df.index.month
es_verano = df['Mes'].isin([4, 5, 6, 7, 8, 9, 10])

df['Periodo'] = 'Intermedio'


### Verano
# Base: 00:00 a 06:00
df.loc[es_verano & (df.index.hour >= 0) & (df.index.hour < 6), 'Periodo'] = 'Base'
# Punta: 20:00 a 22:00
df.loc[es_verano & (df.index.hour >= 20) & (df.index.hour < 22), 'Periodo'] = 'Punta'

### Invierno
# Base: 00:00 a 06:00
df.loc[~es_verano & (df.index.hour >= 0) & (df.index.hour < 6), 'Periodo'] = 'Base'
# Punta: 18:00 a 22:00
df.loc[~es_verano & (df.index.hour >= 18) & (df.index.hour < 22), 'Periodo'] = 'Punta'


