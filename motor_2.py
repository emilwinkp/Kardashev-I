import pvlib
import pandas as pd
import numpy as np


def calculate(lat, lon, alt, tz, tilt, azimuth, area, efficiency, PR):
    tiempos = pd.date_range(start='2026-01-01 00:00', end='2026-12-31 23:59', freq='15min', tz=tz)
    pressure = pvlib.atmosphere.alt2pres(alt)
    turbidity = pvlib.clearsky.lookup_linke_turbidity(tiempos, lat, lon)
    
    sol = pvlib.solarposition.get_solarposition(tiempos, lat, lon, alt, pressure = pressure)
    zenith_vals = sol['apparent_zenith'].values
    azimuth_vals = sol['azimuth'].values
    airmass_rel = pvlib.atmosphere.get_relative_airmass(zenith_vals)
    airmass_abs = pvlib.atmosphere.get_absolute_airmass(airmass_rel, pressure)

    clearsky = pvlib.clearsky.ineichen(zenith_vals, airmass_absolute=airmass_abs, linke_turbidity= turbidity, altitude=alt)

    irradiance_total = pvlib.irradiance.get_total_irradiance(
        surface_tilt=tilt,
        surface_azimuth=azimuth,
        solar_zenith=zenith_vals,
        solar_azimuth=azimuth_vals,
        dni=clearsky['dni'],
        ghi=clearsky['ghi'],
        dhi=clearsky['dhi']
    )

    df = pd.DataFrame(irradiance_total, index=tiempos)
    df['ghi'] = clearsky['ghi']
    df['potencia_generada'] = df['poa_global'] * area * efficiency * PR
    # Energia generada quinceminutalmente en kWh (dividimos por 1000 para convertir de W a kW y multiplicamos por 0.25 para convertir de horas a quinceminas)
    df['energia_generada_kWh'] = (df['poa_global'] * area * efficiency * PR * 0.25) / 1000

    return df
