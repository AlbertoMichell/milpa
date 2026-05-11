-- 0014_crop_profile_seed_pepino.sql
-- IDEMPOTENTE. Esta migración SOLO inserta DATOS de perfil agronómico para el
-- cultivo "pepino" en la tabla `crop_profiles`. NO añade lógica, NO crea
-- columnas exclusivas, NO toca código y NO introduce ninguna excepción
-- por nombre de cultivo.
--
-- La motivación es la misma que con maiz/frijol/calabaza/chile/tomate en la
-- migración 0008 y con cycle_days en la 0013: el sistema lee los umbrales
-- desde `crop_profiles` y reconoce dinámicamente cualquier cultivo presente
-- en esta tabla. Para añadir un cultivo nuevo en el futuro basta replicar
-- este patrón con un INSERT OR IGNORE / UPDATE en runtime — no se requiere
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
  'pepino',
  'Cucumis sativus',
  14, 32,
  55, 80,
  60, 80,
  5.8, 7.0,
  'Cucurbitácea anual de ciclo corto. Sensible a estrés térmico (>33C) e hídrico; alta demanda de agua y potasio en floración y fructificación.'
);

-- Asegura que cycle_days quede consistente aún si la fila ya existía sin él.
UPDATE crop_profiles
   SET cycle_days = 75
 WHERE crop_name = 'pepino'
   AND (cycle_days IS NULL OR cycle_days <= 0);

-- Refresca rangos por si una versión anterior del seed los dejó incompletos.
UPDATE crop_profiles
   SET optimal_temp_min = COALESCE(optimal_temp_min, 14),
       optimal_temp_max = COALESCE(optimal_temp_max, 32),
       optimal_soil_moisture_min = COALESCE(optimal_soil_moisture_min, 55),
       optimal_soil_moisture_max = COALESCE(optimal_soil_moisture_max, 80),
       optimal_air_humidity_min = COALESCE(optimal_air_humidity_min, 60),
       optimal_air_humidity_max = COALESCE(optimal_air_humidity_max, 80),
       optimal_ph_min = COALESCE(optimal_ph_min, 5.8),
       optimal_ph_max = COALESCE(optimal_ph_max, 7.0)
 WHERE crop_name = 'pepino';
