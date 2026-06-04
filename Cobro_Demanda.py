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

df['Demanda_kW'] = df['Energia_kWh'] * 4


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

#print(df.loc[df['Periodo'] == 'Punta'].head(24))

recibo_mensual = []

for (año,mes),grupo in df.groupby([df.index.year, df.index.month]):
    
    total_kwh = grupo['Energia_kWh'].sum()
    total_kvarh = grupo['Energia_kVArh'].sum()
    
    # === Energía ===
    kwh_base = grupo.loc[grupo['Periodo'] == 'Base', 'Energia_kWh'].sum()
    kwh_intermedio = grupo.loc[grupo['Periodo'] == 'Intermedio', 'Energia_kWh'].sum()
    kwh_punta = grupo.loc[grupo['Periodo'] == 'Punta', 'Energia_kWh'].sum()
    
    print(f"{mes}: {grupo.loc[grupo['Periodo'] == 'Punta', 'Demanda_kW'].max()} kW")
    
    # === Capacidad y distribución ===
    
    dias = grupo.index.day.nunique()
    
    pico_dist_1 = grupo['Demanda_kW'].max()
    pico_dist_2 = total_kwh / (24 * 0.57 * dias)
    distribucion_kW = min(pico_dist_1, pico_dist_2)
    
    
    pico_cap_1 = grupo.loc[grupo['Periodo'] == 'Punta', 'Demanda_kW'].max()
    if pd.isna(pico_cap_1):
        pico_cap_1 = 0
    pico_cap_2 = total_kwh / (24 * 0.57 * dias)
    capacidad_kW = min(pico_cap_1, pico_cap_2)
        
    # === Cálculo de los cargos ===
    
    cargo_energia = (kwh_base * cargo_base) + (kwh_intermedio * cargo_intermedia) + (kwh_punta * cargo_punta)    
    cargo_demanda = (cargo_por_distribución * distribucion_kW) + (cargo_por_capacidad * capacidad_kW)
    subtotal = cargo_mensual_fijo + cargo_energia + cargo_demanda
    
    # === Descuentos o Recargas por Factores de potencia ===
    fp = total_kwh / np.sqrt(total_kwh**2 + total_kvarh**2)
    
    if fp < 0.9:
        recarga = (3/5) * (0.9/fp -1)
        total = subtotal * (1+recarga)
        
    else:
        bonificacion = (1/4) * (1- 0.9/fp)
        total = subtotal * (1-bonificacion)
        
    total_iva = total * 1.16
    
    datos = {
        'Año': año,
        'Mes': mes,
        'Total_kWh': total_kwh,
        'Total_kVArh': total_kvarh,
        'Cargo_Energia': cargo_energia,
        'Cargo_Demanda': cargo_demanda,
        'Total_sin_IVA': total,
        'Total_con_IVA': total_iva
    }
    
    recibo_mensual.append(datos)

recibo_df = pd.DataFrame(recibo_mensual)

#recibo_df.to_csv('recibo_riojas.csv', index=False)


    
    
    
    
    
    
    
