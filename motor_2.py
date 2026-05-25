import pvlib
import pandas as pd
import numpy as np


def calculate(lat, lon, tz, tilt, azimuth, area, efficiency, PR):
    tiempos = pd.date_range(start='2026-01-01 00:00', end='2026-12-31 23:59', freq='15min', tz=tz)

    sol = pvlib.solarposition.get_solarposition(tiempos, lat, lon)
    zenith_vals = sol['apparent_zenith'].values
    azimuth_vals = sol['azimuth'].values

    clearsky = pvlib.clearsky.ineichen(zenith_vals, airmass_absolute=1.5, linke_turbidity=3, altitude=500)

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

    return df
