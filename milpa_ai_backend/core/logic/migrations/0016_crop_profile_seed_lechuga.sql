-- 0016_crop_profile_seed_lechuga.sql
-- IDEMPOTENTE. Esta migración SOLO inserta DATOS de perfil agronómico para el
-- cultivo "lechuga" en la tabla `crop_profiles`. NO añade lógica, NO crea
-- columnas exclusivas, NO toca código y NO introduce ninguna excepción
-- por nombre de cultivo.
--
-- Sigue exactamente el mismo patrón que las migraciones 0008 (maíz, frijol,
-- calabaza, chile, tomate) y 0014 (pepino). El sistema lee los umbrales desde
-- `crop_profiles` y reconoce dinámicamente cualquier cultivo presente en esta
-- tabla. Para añadir un cultivo nuevo en el futuro basta replicar este
-- patrón con un INSERT OR IGNORE / UPDATE en runtime — no se requiere
-- recompilar ni redeployar.
--
-- Compatibilidad: la tabla `crop_profiles` ya existe desde 0008. La columna
-- `cycle_days` se añade en 0013. Esta migración asume ambas presentes.

INSERT OR IGNORE INTO crop_profiles (
  crop_name, variety, optimal_temp_min, optimal_temp_max,
  optimal_soil_moisture_min, optimal_soil_moisture_max,
  optimal_air_humidity_min, optimal_air_humidity_max,
  optimal_ph_min, optimal_ph_max, notes
) VALUES (
  'lechuga',
  'Lactuca sativa',
  -- Lechuga es un cultivo de clima fresco: óptimo 15-22 °C, máximo 24-26 °C.
  -- Por encima de 27-28 °C aparece bolting (espigado) y amargor.
  10, 24,
  -- Humedad de suelo recomendada: 65-85 % de capacidad de campo.
  65, 85,
  -- Humedad relativa: 60-80 %.
  60, 80,
  -- pH óptimo: 6.0 a 7.0.
  6.0, 7.0,
  'Hortaliza de hoja de ciclo corto (45-70 días). Sensible al estrés térmico (>26 °C induce espigado y amargor) y al estrés hídrico. Requiere humedad de suelo constante, suelos bien drenados con materia orgánica. Demanda media de N, baja-media de P y K.'
);

-- Asegura que cycle_days quede consistente aún si la fila ya existía sin él.
UPDATE crop_profiles
   SET cycle_days = 60
 WHERE crop_name = 'lechuga'
   AND (cycle_days IS NULL OR cycle_days <= 0);

-- Refresca rangos por si una versión anterior del seed los dejó incompletos.
UPDATE crop_profiles
   SET optimal_temp_min = COALESCE(optimal_temp_min, 10),
       optimal_temp_max = COALESCE(optimal_temp_max, 24),
       optimal_soil_moisture_min = COALESCE(optimal_soil_moisture_min, 65),
       optimal_soil_moisture_max = COALESCE(optimal_soil_moisture_max, 85),
       optimal_air_humidity_min = COALESCE(optimal_air_humidity_min, 60),
       optimal_air_humidity_max = COALESCE(optimal_air_humidity_max, 80),
       optimal_ph_min = COALESCE(optimal_ph_min, 6.0),
       optimal_ph_max = COALESCE(optimal_ph_max, 7.0)
 WHERE crop_name = 'lechuga';
