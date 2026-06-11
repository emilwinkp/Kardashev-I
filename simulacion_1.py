import pvlib
import pandas as pd
import numpy as np
import random
import os

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
    lat, lon, alt, tz, tilt, azimuth, area, num_paneles, efficiency, PR = solicitar_inputs_usuario()
    
    print("\nCalculando la posición solar y generación... (Esto puede tomar unos segundos)")
    
    tiempos = pd.date_range(start='2026-01-01 00:00', end='2026-12-31 23:59', freq='15min', tz=tz)
    pressure = pvlib.atmosphere.alt2pres(alt)
    turbidity = pvlib.clearsky.lookup_linke_turbidity(tiempos, lat, lon)
    
    sol = pvlib.solarposition.get_solarposition(tiempos, lat, lon, alt, pressure=pressure)
    zenith_vals = sol['apparent_zenith'].values
    solar_azimuth_vals = sol['azimuth'].values
    
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

    df = pd.DataFrame(irradiance_total, index=tiempos)
    df['ghi'] = clearsky['ghi']
    
    area_total = area * num_paneles
    df['potencia_generada'] = df['poa_global'] * area_total * efficiency * PR
    df['energia_generada_kWh'] = (df['poa_global'] * area_total * efficiency * PR * 0.25) / 1000
    
    return df, num_paneles, area

def asignar_tarifa_gdmth(fecha):
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

def simular_operacion_industrial_mixta(df_solar, ruta_csv_demanda, cap_respaldo_max_kwh=100, num_apagones=30, duracion_horas_apagon=1.0):
    print(f"\nCargando demanda desde '{ruta_csv_demanda}' y combinando datos...")
    
    df_demanda = pd.read_csv(ruta_csv_demanda, index_col=0, parse_dates=True, sep=',')
    df_solar_naive = df_solar.tz_localize(None)
    df = df_solar_naive.join(df_demanda, how='inner')
    
    if len(df) == 0:
        raise ValueError("Error: El DataFrame resultante está vacío. Revisa que las fechas del CSV coincidan con el año 2026.")
    
    periodos_por_apagon = max(1, int(duracion_horas_apagon * 4))
    
    df['apagon'] = False
    random.seed(42)
    inicios_apagones = random.sample(range(0, len(df) - periodos_por_apagon), num_apagones)
    for inicio in inicios_apagones:
        df.iloc[inicio:inicio+periodos_por_apagon, df.columns.get_loc('apagon')] = True

    df['periodo_cfe'] = df.index.map(asignar_tarifa_gdmth)
    
    # --- ANÁLISIS PREVIO: DETERMINAR EL CONSUMO MÁXIMO ACUMULADO EN HORAS PUNTA ---
    # Filtramos solo los registros en periodo punta y sumamos por día para hallar el peor escenario de consumo de la planta
    df_punta_solo = df[df['periodo_cfe'] == 'Punta']
    consumo_punta_por_dia = df_punta_solo.groupby(df_punta_solo.index.date)['Energia_kWh'].sum()
    
    if len(consumo_punta_por_dia) > 0:
        sizing_diario_requerido = consumo_punta_por_dia.max()
    else:
        sizing_diario_requerido = 1000 # Valor de respaldo por si no hay datos punta
        
    cap_diaria_virtual_max = sizing_diario_requerido
    
    soc_respaldo = cap_respaldo_max_kwh 
    soc_diario = 0
    
    eficiencia_carga = 0.95
    eficiencia_descarga = 0.95
    degradacion_diaria_porcentaje = 0.0001 
    
    compra_kwh_red_lista = []
    potencia_kw_red_lista = []
    reactive_kvarh_lista = [] 
    energia_desperdiciada_lista = []
    
    print(f"Ejecutando simulación minutal de {len(df)} periodos (Estrategia Autoconsumo Puro)...")
    print(f"-> Capacidad máxima de la batería diaria fijada por consumo Punta Crítico: {cap_diaria_virtual_max:,.2f} kWh")
    
    for i in range(len(df)):
        if i > 0 and i % 96 == 0:
            cap_respaldo_max_kwh *= (1 - degradacion_diaria_porcentaje)
            soc_diario = 0  # Reinicio de medianoche asegurado
        
        row = df.iloc[i]
        solar_kw = row['potencia_generada'] / 1000 
        reactive_kvarh = row['Energia_kVArh'] 
        tarifa = row['periodo_cfe']
        apagon = row['apagon']
        
        solar_kwh = solar_kw * 0.25
        demanda_kwh = row['Energia_kWh']
        compra_red_kwh = 0
        desperdicio_bloque_kwh = 0 
        
        if apagon:
            # En apagón, toda la energía solar va primero a la planta
            if solar_kwh >= demanda_kwh:
                sobrante = solar_kwh - demanda_kwh
                # El sobrante intenta rescatar la batería de respaldo de apagones
                espacio_respaldo = max(0, cap_respaldo_max_kwh - soc_respaldo)
                carga_real = min(sobrante * eficiencia_carga, espacio_respaldo)
                soc_respaldo += carga_real
                
                
                sobrante_neto = sobrante - (carga_real / eficiencia_carga)
                desperdicio_bloque_kwh = max(0, sobrante_neto)
            else:
                deficit = demanda_kwh - solar_kwh
                descarga = deficit / eficiencia_descarga
                soc_respaldo = max(0, soc_respaldo - descarga)
            compra_red_kwh = 0
            reactive_kvarh = 0 
        else:
            
            # PRIORIDAD 1: Ir directo a mitigar la demanda instantánea de la planta (Consumo Inmediato)
            energia_faltante_planta = max(0, demanda_kwh - solar_kwh)
            solar_sobrante = max(0, solar_kwh - demanda_kwh)
            
            # Si hay sobrante solar después de abastecer a la planta
            if solar_sobrante > 0:
                # PRIORIDAD 2: Rellenar la batería de respaldo para apagones (si es que necesita carga)
                if soc_respaldo < cap_respaldo_max_kwh:
                    espacio_respaldo = cap_respaldo_max_kwh - soc_respaldo
                    carga_respaldo = min(solar_sobrante * eficiencia_carga, espacio_respaldo)
                    soc_respaldo += carga_respaldo
                    solar_sobrante -= (carga_respaldo / eficiencia_carga)
                
                # PRIORIDAD 3: Rellenar la batería de almacenamiento diario
                if solar_sobrante > 0:
                    espacio_diario = max(0, cap_diaria_virtual_max - soc_diario)
                    carga_diaria_real = min(solar_sobrante * eficiencia_carga, espacio_diario)
                    soc_diario += carga_diaria_real
                    solar_sobrante -= (carga_diaria_real / eficiencia_carga)
                
                # PRIORIDAD 4: Lo que no cupo en ningún lado es energía desperdiciada (Curtailment)
                desperdicio_bloque_kwh = max(0, solar_sobrante)
            
            # La compra inicial a la red es lo que los paneles no pudieron cubrir directamente
            compra_red_kwh = energia_faltante_planta
            
            # --- MANEJO DE DESCARGA EN TARIFA PUNTA ---
            if tarifa == 'Punta':
                if compra_red_kwh > 0:
                    # La batería diaria apoya a la planta usando solo lo que acumuló del sol
                    descarga_real = min(compra_red_kwh, soc_diario * eficiencia_descarga)
                    soc_diario -= (descarga_real / eficiencia_descarga)
                    compra_red_kwh -= descarga_real 
            
        compra_kwh_red_lista.append(compra_red_kwh)
        potencia_kw_red_lista.append(compra_red_kwh / 0.25) 
        reactive_kvarh_lista.append(reactive_kvarh)
        energia_desperdiciada_lista.append(desperdicio_bloque_kwh)

    df['compra_red_kwh'] = compra_kwh_red_lista
    df['potencia_red_kw'] = potencia_kw_red_lista
    df['reactive_red_kvarh'] = reactive_kvarh_lista
    df['energia_desperdiciada_kwh'] = energia_desperdiciada_lista 
    
    df['potencia_original_kw'] = df['Energia_kWh'] / 0.25
    
    precio_base, precio_intermedio, precio_punta = 1.10, 1.50, 3.20
    cargo_capacidad, cargo_distribucion = 350.00, 100.00 
    
    recibo_mensual_sistema = []
    recibo_mensual_base = []
    
    for mes, df_mes in df.groupby(df.index.month):
        e_base_sis = df_mes[df_mes['periodo_cfe'] == 'Base']['compra_red_kwh'].sum()
        e_int_sis = df_mes[df_mes['periodo_cfe'] == 'Intermedio']['compra_red_kwh'].sum()
        e_punta_sis = df_mes[df_mes['periodo_cfe'] == 'Punta']['compra_red_kwh'].sum()
        
        dem_max_mes_sis = df_mes['potencia_red_kw'].max()
        dem_max_punta_sis = df_mes[df_mes['periodo_cfe'] == 'Punta']['potencia_red_kw'].max()
        if pd.isna(dem_max_punta_sis): dem_max_punta_sis = 0
        
        costo_energia_sis = (e_base_sis * precio_base) + (e_int_sis * precio_intermedio) + (e_punta_sis * precio_punta)
        subtotal_sis = costo_energia_sis + (dem_max_punta_sis * cargo_capacidad) + (dem_max_mes_sis * cargo_distribucion)
        
        total_kwh_mes_sis = df_mes['compra_red_kwh'].sum()
        total_kvarh_mes_sis = df_mes['reactive_red_kvarh'].sum()
        fp_mes_sis = total_kwh_mes_sis / np.sqrt(total_kwh_mes_sis**2 + total_kvarh_mes_sis**2) if total_kwh_mes_sis > 0 else 1.0
        
        porcentaje_fp_sis = (3/7)*((0.90/fp_mes_sis)-1) if fp_mes_sis < 0.90 else -(1/4)*(1-(0.90/fp_mes_sis))
        efecto_fp_mxn_sis = subtotal_sis * porcentaje_fp_sis
        
        desperdicio_mes = df_mes['energia_desperdiciada_kwh'].sum()
        
        recibo_mensual_sistema.append({
            'Mes': mes, 'Demanda_Punta_kW': round(dem_max_punta_sis, 1), 'Demanda_Max_kW': round(dem_max_mes_sis, 1),
            'FP_Mensual': round(fp_mes_sis, 3), 'Efecto_FP_MXN': round(efecto_fp_mxn_sis, 2), 
            'Total_CFE_MXN': round(subtotal_sis + efecto_fp_mxn_sis, 2), 'Solar_Desechada_kWh': round(desperdicio_mes, 1)
        })

        e_base_base = df_mes[df_mes['periodo_cfe'] == 'Base']['Energia_kWh'].sum()
        e_int_base = df_mes[df_mes['periodo_cfe'] == 'Intermedio']['Energia_kWh'].sum()
        e_punta_base = df_mes[df_mes['periodo_cfe'] == 'Punta']['Energia_kWh'].sum()
        
        dem_max_mes_base = df_mes['potencia_original_kw'].max()
        dem_max_punta_base = df_mes[df_mes['periodo_cfe'] == 'Punta']['potencia_original_kw'].max()
        if pd.isna(dem_max_punta_base): dem_max_punta_base = 0
        
        costo_energia_base = (e_base_base * precio_base) + (e_int_base * precio_intermedio) + (e_punta_base * precio_punta)
        subtotal_base = costo_energia_base + (dem_max_punta_base * cargo_capacidad) + (dem_max_mes_base * cargo_distribucion)
        
        total_kwh_mes_base = df_mes['Energia_kWh'].sum()
        total_kvarh_mes_base = df_mes['Energia_kVArh'].sum()
        fp_mes_base = total_kwh_mes_base / np.sqrt(total_kwh_mes_base**2 + total_kvarh_mes_base**2) if total_kwh_mes_base > 0 else 1.0
        
        porcentaje_fp_base = (3/7)*((0.90/fp_mes_base)-1) if fp_mes_base < 0.90 else -(1/4)*(1-(0.90/fp_mes_base))
        efecto_fp_mxn_base = subtotal_base * porcentaje_fp_base
        
        recibo_mensual_base.append({
            'Mes': mes, 'Demanda_Punta_kW': round(dem_max_punta_base, 1), 'Demanda_Max_kW': round(dem_max_mes_base, 1),
            'FP_Mensual': round(fp_mes_base, 3), 'Efecto_FP_MXN': round(efecto_fp_mxn_base, 2), 
            'Total_CFE_MXN': round(subtotal_base + efecto_fp_mxn_base, 2)
        })

    df_recibo_sis = pd.DataFrame(recibo_mensual_sistema)
    df_recibo_base = pd.DataFrame(recibo_mensual_base)
    
    pd.set_option('display.max_rows', None)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)
    
    print("\n==========================================================================================")
    print("--- 1. RECIBO SIMULADO MENSUAL (CON PANELES, BATERÍAS Y REGISTRO DE DESPERDICIO SOLAR) ---")
    print("==========================================================================================")
    print(df_recibo_sis.to_string(index=False))
    
    print("\n==========================================================")
    print("--- 2. RECIBO BASE ORIGINAL MENSUAL (SIN CAMBIOS)      ---")
    print("==========================================================")
    print(df_recibo_base.to_string(index=False))
    
    return df, df_recibo_sis, df_recibo_base, sizing_diario_requerido


if __name__ == "__main__":
    archivo_demanda = "demanda_2026.csv"
    
    bateria_respaldo_inicial = 500  
    cantidad_apagones_ano = 30
    duracion_apagones_horas = 1.5 
    
    if not os.path.exists(archivo_demanda):
        print(f"\n[ERROR] No se encontró el archivo '{archivo_demanda}' en el directorio actual.")
    else:
        df_solar_calculado, num_paneles, area = calculate_interactive()
        
        df_final, df_recibo_proyectado, df_recibo_base_real, sizing_di = simular_operacion_industrial_mixta(
            df_solar=df_solar_calculado,
            ruta_csv_demanda=archivo_demanda,
            cap_respaldo_max_kwh=bateria_respaldo_inicial,
            num_apagones=cantidad_apagones_ano,
            duracion_horas_apagon=duracion_apagones_horas
        )

        cant_pilas = int(np.ceil(sizing_di / 100))
        if cant_pilas == 0: 
            cant_pilas = 1  
        
        ahorro_anual = df_recibo_base_real['Total_CFE_MXN'].sum() - df_recibo_proyectado['Total_CFE_MXN'].sum()
        
        total_solar_desperdiciada_ano = df_final['energia_desperdiciada_kwh'].sum()
        total_solar_generada_ano = df_final['energia_generada_kWh'].sum()
        porcentaje_desperdicio = (total_solar_desperdiciada_ano / total_solar_generada_ano * 100) if total_solar_generada_ano > 0 else 0
        dinero_tirado_mxn = total_solar_desperdiciada_ano * 1.50
        
        costo_pila = 500000
        costo_panel_m2 = 1000
        cant_total_area = num_paneles * area
        costo_total_paneles = cant_total_area * costo_panel_m2
        costo_total_pilas = cant_pilas * costo_pila
        
        def funcion_objetiva_costo():
            J = costo_total_paneles + costo_total_pilas - ((ahorro_anual * 7*((1+0.0426)**6/(1+0.007)**6))/(1+0.0411)**7)
            return J
            
        print("\n=======================================================")
        print("---     EVALUACIÓN ECONÓMICA Y FINANCIERA FINAL     ---")
        print("=======================================================")
        print(f"Capacidad del Banco Diario Requerido (Punta Máx): {sizing_di:,.2f} kWh")
        print(f"Cantidad de Pilas Calculada automáticamente:     {cant_pilas} unidad(es)")
        print(f"Costo Total de Paneles Instalados:              ${costo_total_paneles:,.2f} MXN")
        print(f"Costo Total de Pilas Adquiridas:                ${costo_total_pilas:,.2f} MXN")
        print(f"Inversión de Capital Inicial (Capex Est.):       ${(costo_total_paneles + costo_total_pilas):,.2f} MXN")
        print(f"Ahorro Total de CFE logrado al año:              ${ahorro_anual:,.2f} MXN")
        print(f"Valor de la Función Objetiva (J):               ${funcion_objetiva_costo():,.2f} MXN")
        print("-------------------------------------------------------")
        print("---         MÉTRICAS DE SOBREDIMENSIONAMIENTO       ---")
        print("-------------------------------------------------------")
        print(f"Energía Solar TOTAL Generada por Paneles:       {total_solar_generada_ano:,.1f} kWh")
        print(f"Energía Solar DESPERDICIADA (Curtailment):      {total_solar_desperdiciada_ano:,.1f} kWh")
        print(f"Porcentaje de Energía Desperdiciada:            {porcentaje_desperdicio:.2f}%")
        print(f"Pérdida por Costo de Oportunidad (Est.):        ${dinero_tirado_mxn:,.2f} MXN")
        print("=======================================================\n")

        with pd.ExcelWriter("Comparativa_Recibos_CFE_2026.xlsx") as writer:
            df_recibo_proyectado.to_excel(writer, sheet_name="Con_Sistema_Fotovoltaico", index=False)
            df_recibo_base_real.to_excel(writer, sheet_name="Recibo_Base_Sin_Cambios", index=False)
            df_final.to_excel(writer, sheet_name="Datos_Minutales_Completos", index=False)
            
        print("[ÉXITO] Archivo 'Comparativa_Recibos_CFE_2026.xlsx' generado correctamente con sus 3 pestañas.")