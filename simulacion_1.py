import pvlib
import pandas as pd
import numpy as np
import random
import os
import openpyxl as pxl

def solicitar_inputs_usuario():
    print("\n==============================================")
    print("--- Configuración del Sistema Fotovoltaico ---")
    print("==============================================")
    
    lat = float(input("Ingresa la latitud (ej. 25.65 para Monterrey): "))
    lon = float(input("Ingresa la longitud (ej. -100.31): "))
    alt = float(input("Ingresa la altitud en metros (ej. 540): "))
    tz = input("Ingresa la zona horaria (ej. Etc/GMT+6): ")
    tilt = float(input("Ingresa el ángulo de inclinación de los paneles (tilt): "))
    azimuth = float(input("Ingresa el ángulo azimutal de los paneles (ej. 180 para Sur): "))
    area = float(input("Ingresa el área de un panel en m2 (ej. 2.1): "))
    num_paneles = int(input("Ingresa la cantidad de paneles solares: "))
    efficiency = float(input("Ingresa la eficiencia del panel (ej. 0.20 para 20%): "))
    PR = float(input("Ingresa el Performance Ratio (PR) (ej. 0.8): "))
    
    return lat, lon, alt, tz, tilt, azimuth, area, num_paneles, efficiency, PR

def calculate_interactive():
    # 1. Obtener los inputs del usuario
    lat, lon, alt, tz, tilt, azimuth, area, num_paneles, efficiency, PR = solicitar_inputs_usuario()
    
    print("\nCalculando la posición solar y generación... (Esto puede tomar unos segundos)")
    
    # AJUSTE: Cambiado al año 2026 completo
    tiempos = pd.date_range(start='2026-01-01 00:00', end='2026-12-31 23:59', freq='15min', tz=tz)
    pressure = pvlib.atmosphere.alt2pres(alt)
    turbidity = pvlib.clearsky.lookup_linke_turbidity(tiempos, lat, lon)
    
    # 3. Cálculo de los valores solares
    sol = pvlib.solarposition.get_solarposition(tiempos, lat, lon, alt, pressure=pressure)
    zenith_vals = sol['apparent_zenith'].values
    solar_azimuth_vals = sol['azimuth'].values
    
    # 4. Cálculo de masa de aire e irradiancia
    airmass_rel = pvlib.atmosphere.get_relative_airmass(zenith_vals)
    airmass_abs = pvlib.atmosphere.get_absolute_airmass(airmass_rel, pressure)

    clearsky = pvlib.clearsky.ineichen(zenith_vals, airmass_absolute=airmass_abs, linke_turbidity=turbidity, altitude=alt)

    irradiance_total = pvlib.irradiance.get_total_irradiance(
        surface_tilt=tilt,
        surface_azimuth=azimuth,
        solar_zenith=zenith_vals,
        solar_azimuth=solar_azimuth_vals,
        dni=clearsky['dni'],
        ghi=clearsky['ghi'],
        dhi=clearsky['dhi']
    )

    # 5. Creación del DataFrame y cálculo de energía
    df = pd.DataFrame(irradiance_total, index=tiempos)
    df['ghi'] = clearsky['ghi']
    
    area_total = area * num_paneles
    df['potencia_generada'] = df['poa_global'] * area_total * efficiency * PR
    df['energia_generada_kWh'] = (df['poa_global'] * area_total * efficiency * PR * 0.25) / 1000
    
    return df

def asignar_tarifa_gdmth(fecha):
    """
    Asigna el periodo GDMTH simplificado de CFE (Base, Intermedio, Punta).
    """
    hora = fecha.hour
    dia_semana = fecha.weekday() 
    
    if dia_semana < 5: # Lunes a Viernes
        if 18 <= hora < 22:
            return 'Punta'
        elif 0 <= hora < 6:
            return 'Base'
        else:
            return 'Intermedio'
    else: # Fines de semana
        if 0 <= hora < 7:
            return 'Base'
        else:
            return 'Intermedio'

def simular_operacion_industrial_mixta(df_solar, ruta_csv_demanda, cap_respaldo_max_kwh=200, num_apagones=30):
    print(f"\nCargando demanda desde '{ruta_csv_demanda}' y combinando datos...")
    
    # Leer demanda desde CSV
    df_demanda = pd.read_csv(ruta_csv_demanda, index_col=0, parse_dates=True, sep=',')

    # Quitar zona horaria de df_solar para evitar conflictos de pandas
    df_solar_naive = df_solar.tz_localize(None)
    
    # Combinar DataFrames por índice de tiempo común
    df = df_solar_naive.join(df_demanda, how='inner')
    
    if len(df) == 0:
        # AJUSTE: Mensaje de error actualizado a 2026
        raise ValueError("Error: El DataFrame resultante está vacío. Revisa que las fechas del CSV coincidan con el año 2026.")
    
    # Generar apagones aleatorios distribuidos en el año
    df['apagon'] = False
    inicios_apagones = random.sample(range(0, len(df) - 4), num_apagones)
    for inicio in inicios_apagones:
        df.iloc[inicio:inicio+4, df.columns.get_loc('apagon')] = True

    # Asignar periodo tarifario GDMTH
    df['periodo_cfe'] = df.index.map(asignar_tarifa_gdmth)
    
    # Inicialización de almacenamiento lógico
    soc_respaldo = cap_respaldo_max_kwh 
    cap_diaria_virtual_max = 300000 
    soc_diario = 0
    max_soc_diario_registrado = 0
    
    # Parámetros de eficiencia, degradación y potencia de carga
    eficiencia_carga = 0.95
    eficiencia_descarga = 0.95
    degradacion_diaria_porcentaje = 0.0001 
    potencia_carga_red_base_kw = 250 
    
    compra_kwh_red_lista = []
    potencia_kw_red_lista = []
    reactive_kvarh_lista = [] 
    
    print(f"Ejecutando simulación minutal de {len(df)} periodos (Estrategia Mixta)...")
    
    for i in range(len(df)):
        if i > 0 and i % 96 == 0:
            cap_respaldo_max_kwh *= (1 - degradacion_diaria_porcentaje)
        
        row = df.iloc[i]
        solar_kw = row['potencia_generada'] 
        
        # Lectura limpia de tus columnas activas y reactivas
        reactive_kvarh = row['Energia_kVArh'] 
        tarifa = row['periodo_cfe']
        apagon = row['apagon']
        
        solar_kwh = solar_kw * 0.25
        demanda_kwh = row['Energia_kWh']
        compra_red_kwh = 0
        
        if apagon:
            energia_necesaria = demanda_kwh
            if solar_kwh >= energia_necesaria:
                sobrante = solar_kwh - energia_necesaria
                soc_respaldo += min(sobrante * eficiencia_carga, cap_respaldo_max_kwh - soc_respaldo)
            else:
                deficit = energia_necesaria - solar_kwh
                descarga = deficit / eficiencia_descarga
                soc_respaldo = max(0, soc_respaldo - descarga)
            compra_red_kwh = 0
            reactive_kvarh = 0 
            
        else:
            if soc_respaldo < cap_respaldo_max_kwh and solar_kwh > 0:
                solar_a_respaldo = min(solar_kwh, (cap_respaldo_max_kwh - soc_respaldo) / eficiencia_carga)
                soc_respaldo += (solar_a_respaldo * eficiencia_carga)
                solar_kwh -= solar_a_respaldo
                
            energia_faltante_planta = max(0, demanda_kwh - solar_kwh)
            solar_sobrante = max(0, solar_kwh - demanda_kwh)
            
            if solar_sobrante > 0:
                soc_diario += min(solar_sobrante * eficiencia_carga, cap_diaria_virtual_max - soc_diario)
            
            compra_red_kwh = energia_faltante_planta
            
            if tarifa == 'Base':
                carga_desde_red = min(potencia_carga_red_base_kw * 0.25, (cap_diaria_virtual_max - soc_diario) / eficiencia_carga)
                soc_diario += (carga_desde_red * eficiencia_carga)
                compra_red_kwh += carga_desde_red 
                
            elif tarifa == 'Punta':
                if compra_red_kwh > 0:
                    descarga_real = min(compra_red_kwh, soc_diario * eficiencia_descarga)
                    soc_diario -= (descarga_real / eficiencia_descarga)
                    compra_red_kwh -= descarga_real 
        
        if soc_diario > max_soc_diario_registrado:
            max_soc_diario_registrado = soc_diario
            
        compra_kwh_red_lista.append(compra_red_kwh)
        potencia_kw_red_lista.append(compra_red_kwh / 0.25) 
        reactive_kvarh_lista.append(reactive_kvarh)

    df['compra_red_kwh'] = compra_kwh_red_lista
    df['potencia_red_kw'] = potencia_kw_red_lista
    df['reactive_red_kvarh'] = reactive_kvarh_lista
    
    # 6. Estructuración del Recibo CFE Mensual
    precio_base = 1.10
    precio_intermedio = 1.50
    precio_punta = 3.20
    cargo_capacidad = 350.00 
    cargo_distribucion = 100.00 
    
    recibo_mensual = []
    
    for mes, df_mes in df.groupby(df.index.month):
        energia_base = df_mes[df_mes['periodo_cfe'] == 'Base']['compra_red_kwh'].sum()
        energia_int = df_mes[df_mes['periodo_cfe'] == 'Intermedio']['compra_red_kwh'].sum()
        energia_punta = df_mes[df_mes['periodo_cfe'] == 'Punta']['compra_red_kwh'].sum()
        
        demanda_max_mes = df_mes['potencia_red_kw'].max()
        demanda_max_punta = df_mes[df_mes['periodo_cfe'] == 'Punta']['potencia_red_kw'].max()
        
        if pd.isna(demanda_max_punta): demanda_max_punta = 0
        
        costo_energia = (energia_base * precio_base) + (energia_int * precio_intermedio) + (energia_punta * precio_punta)
        costo_capacidad = demanda_max_punta * cargo_capacidad
        costo_distribucion = demanda_max_mes * cargo_distribucion
        subtotal_recibo = costo_energia + costo_capacidad + costo_distribucion   

        # CÁLCULO DEL FACTOR DE POTENCIA MENSUAL
        total_kwh_mes = df_mes['compra_red_kwh'].sum()
        total_kvarh_mes = df_mes['reactive_red_kvarh'].sum()
        
        if total_kwh_mes > 0:
            fp_mes = total_kwh_mes / np.sqrt(total_kwh_mes**2 + total_kvarh_mes**2)
        else:
            fp_mes = 1.0
            
        if fp_mes < 0.90:
            porcentaje_fp = (3/7) * ((0.90 / fp_mes) - 1)
            efecto_fp_mxn = subtotal_recibo * porcentaje_fp  
        else:
            porcentaje_fp = (1/4) * (1 - (0.90 / fp_mes))
            efecto_fp_mxn = subtotal_recibo * porcentaje_fp  
            
        total_factura = subtotal_recibo + efecto_fp_mxn
        
        recibo_mensual.append({
            'Mes': mes,
            'Demanda_Punta_kW': round(demanda_max_punta, 1),
            'Demanda_Max_kW': round(demanda_max_mes, 1),
            'Subtotal_MXN': round(subtotal_recibo, 2),
            'FP_Mensual': round(fp_mes, 3),
            'Efecto_FP_MXN': round(efecto_fp_mxn, 2),
            'Total_CFE_MXN': round(total_factura, 2)
        })

    df_recibo = pd.DataFrame(recibo_mensual)
    print("\n==============================================")
    print("---      RESULTADOS CON FACTOR DE POTENCIA   ---")
    print("==============================================")
    print(df_recibo[['Mes', 'Demanda_Punta_kW', 'Demanda_Max_kW', 'FP_Mensual', 'Efecto_FP_MXN', 'Total_CFE_MXN']].to_string(index=False))
    
    # El return entrega correctamente los 3 elementos para el MAIN
    return df, df_recibo, max_soc_diario_registrado

    


# --- BLOQUE PRINCIPAL DE EJECUCIÓN (MAIN) ---
if __name__ == "__main__":
    # AJUSTE: Cambiado el nombre del archivo de búsqueda a 2026
    archivo_demanda = "demanda_2026.csv"
    
    bateria_respaldo_inicial = 0  
    cantidad_apagones_ano = 30       
    
    if not os.path.exists(archivo_demanda):
        print(f"\n[ERROR] No se encontró el archivo '{archivo_demanda}' en el directorio actual.")
        print("Por favor, asegúrate de colocar tu archivo CSV de demanda de 15 minutos en la misma carpeta que este script.")
        print("El CSV debe tener las fechas completas del 2026 en la primera columna y las columnas 'Energia_kWh' y 'Energia_kVArh'.\n")
    else:
        df_solar_calculado = calculate_interactive()
        
        df_final, df_recibo_mensual, sizing_diario = simular_operacion_industrial_mixta(
            df_solar=df_solar_calculado,
            ruta_csv_demanda=archivo_demanda,
            cap_respaldo_max_kwh=bateria_respaldo_inicial,
            num_apagones=cantidad_apagones_ano
        )
        
        # AJUSTE: Nombre del Excel de salida guardado con el año 2026
        df_recibo_mensual.to_excel("Recibo_CFE_Proyectado_Baterias_2026.xlsx", index=False)
        print("\n[ÉXITO] Se ha generado el archivo 'Recibo_CFE_Proyectado_Baterias_2026.xlsx' con los resultados mensuales.")
