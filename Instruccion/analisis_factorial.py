"""
Análisis Factorial Completo 2^4: Optimización de Agua Disponible (AWC)
Diseño: Factorial Completo con 4 factores a 2 niveles
Análisis: ANOVA, efectos principales, interacciones, modelo de regresión
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from scipy import stats
from itertools import combinations
import warnings
warnings.filterwarnings('ignore')

# Cargar dataset con AWC calculado
df = pd.read_excel('dataset_con_awc.xlsx')

print("="*80)
print("ANÁLISIS FACTORIAL 2^4: OPTIMIZACIÓN DE AGUA DISPONIBLE (AWC)")
print("="*80)

# Factores
factores = ['arcilla_pct', 'materia_organica_pct', 'densidad_aparente_g_cm3', 'profundidad_efectiva_cm']
factores_short = ['Arcilla', 'MO', 'DA', 'Prof']

# PASO 1: Codificar factores a niveles -1 y +1
print("\n[PASO 1] Codificación de Factores")
print("-" * 80)

df_factorial = df[factores + ['awc_mm_m']].copy()

for factor in factores:
    mediana = df[factor].median()
    df_factorial[f'{factor}_coded'] = np.where(df_factorial[factor] < mediana, -1, 1)

# Crear matriz de diseño
X = df_factorial[[f'{f}_coded' for f in factores]].values
y = df_factorial['awc_mm_m'].values

print(f"Matriz de diseño X: {X.shape}")
print(f"Vector de respuestas y: {y.shape}")
print(f"Número total de observaciones: {len(y)}")

# PASO 2: Calcular efectos principales
print("\n[PASO 2] Efectos Principales")
print("-" * 80)

efectos_principales = {}
for idx, factor in enumerate(factores):
    nivel_alto = y[X[:, idx] == 1]
    nivel_bajo = y[X[:, idx] == -1]
    
    efecto = nivel_alto.mean() - nivel_bajo.mean()
    efectos_principales[factor] = {
        'efecto': efecto,
        'mean_alto': nivel_alto.mean(),
        'mean_bajo': nivel_bajo.mean(),
        'std_alto': nivel_alto.std(),
        'std_bajo': nivel_bajo.std(),
        'n_alto': len(nivel_alto),
        'n_bajo': len(nivel_bajo)
    }
    
    print(f"\n{factores_short[idx]:10s} ({factor}):")
    print(f"  Nivel Bajo (-1): {nivel_bajo.mean():7.2f} ± {nivel_bajo.std():.2f} mm/m  (n={len(nivel_bajo)})")
    print(f"  Nivel Alto (+1): {nivel_alto.mean():7.2f} ± {nivel_alto.std():.2f} mm/m  (n={len(nivel_alto)})")
    print(f"  Efecto:          {efecto:7.2f} mm/m")

# PASO 3: Calcular interacciones de 2do orden
print("\n[PASO 3] Interacciones de 2° Orden (Dobles)")
print("-" * 80)

interacciones_2 = {}
for i, j in combinations(range(len(factores)), 2):
    # Interacción AB = (media(A+,B+) + media(A-,B-)) - (media(A+,B-) + media(A-,B+))
    mask_pp = (X[:, i] == 1) & (X[:, j] == 1)
    mask_pn = (X[:, i] == 1) & (X[:, j] == -1)
    mask_np = (X[:, i] == -1) & (X[:, j] == 1)
    mask_nn = (X[:, i] == -1) & (X[:, j] == -1)
    
    media_pp = y[mask_pp].mean() if mask_pp.sum() > 0 else 0
    media_pn = y[mask_pn].mean() if mask_pn.sum() > 0 else 0
    media_np = y[mask_np].mean() if mask_np.sum() > 0 else 0
    media_nn = y[mask_nn].mean() if mask_nn.sum() > 0 else 0
    
    interaccion = ((media_pp + media_nn) - (media_pn + media_np)) / 2
    
    nombre = f"{factores_short[i]}×{factores_short[j]}"
    interacciones_2[nombre] = {
        'efecto': interaccion,
        'factores': (factores[i], factores[j])
    }
    
    print(f"{nombre:15s}: Efecto = {interaccion:7.2f} mm/m")

# PASO 4: ANOVA para cada factor
print("\n[PASO 4] ANOVA: Significancia de Efectos Principales")
print("-" * 80)
print(f"{'Factor':<15s} {'F-statistic':>12s} {'p-value':>12s} {'Significativo':>15s}")
print("-" * 80)

resultados_anova = {}
for idx, factor in enumerate(factores):
    grupo_alto = y[X[:, idx] == 1]
    grupo_bajo = y[X[:, idx] == -1]
    
    f_stat, p_value = stats.f_oneway(grupo_alto, grupo_bajo)
    significativo = "***" if p_value < 0.001 else ("**" if p_value < 0.01 else ("*" if p_value < 0.05 else "NS"))
    
    resultados_anova[factor] = {
        'f_stat': f_stat,
        'p_value': p_value,
        'significativo': significativo
    }
    
    print(f"{factores_short[idx]:<15s} {f_stat:12.2f} {p_value:12.6f} {significativo:>15s}")

print("\nLeyenda: *** p<0.001,  ** p<0.01,  * p<0.05,  NS = No significativo")

# PASO 5: Modelo de Regresión Lineal
print("\n[PASO 5] Modelo de Regresión Empírico")
print("-" * 80)

from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score, mean_squared_error, mean_absolute_error

# Modelo solo con efectos principales
X_model = X.copy()
modelo = LinearRegression()
modelo.fit(X_model, y)

y_pred = modelo.predict(X_model)
r2 = r2_score(y, y_pred)
rmse = np.sqrt(mean_squared_error(y, y_pred))
mae = mean_absolute_error(y, y_pred)

print("\nModelo: AWC = β₀ + β₁·Arcilla + β₂·MO + β₃·DA + β₄·Prof")
print(f"\nIntercepto (β₀): {modelo.intercept_:.4f} mm/m")
print("\nCoeficientes:")
for idx, factor in enumerate(factores):
    print(f"  β{idx+1} ({factores_short[idx]:8s}): {modelo.coef_[idx]:8.4f}")

print(f"\nBondad de Ajuste:")
print(f"  R² =          {r2:.4f}")
print(f"  RMSE =        {rmse:.4f} mm/m")
print(f"  MAE =         {mae:.4f} mm/m")

# PASO 6: Verificación de supuestos del ANOVA
print("\n[PASO 6] Verificación de Supuestos del ANOVA")
print("-" * 80)

residuos = y - y_pred

# a) Normalidad (Shapiro-Wilk)
stat_shapiro, p_shapiro = stats.shapiro(residuos)
print(f"\na) Normalidad de Residuos (Shapiro-Wilk):")
print(f"   Estadístico W: {stat_shapiro:.4f}")
print(f"   p-value:       {p_shapiro:.6f}")
print(f"   Conclusión:    {'✓ Residuos normales' if p_shapiro > 0.05 else '✗ Residuos NO normales'}")

# b) Homocedasticidad (Levene)
grupos_residuos = [residuos[X[:, 3] == -1], residuos[X[:, 3] == 1]]  # Agrupado por Prof
stat_levene, p_levene = stats.levene(*grupos_residuos)
print(f"\nb) Homocedasticidad (Levene):")
print(f"   Estadístico:   {stat_levene:.4f}")
print(f"   p-value:       {p_levene:.6f}")
print(f"   Conclusión:    {'✓ Varianzas homogéneas' if p_levene > 0.05 else '✗ Varianzas NO homogéneas'}")

# c) Independencia (Durbin-Watson)
from statsmodels.stats.stattools import durbin_watson
dw_stat = durbin_watson(residuos)
print(f"\nc) Independencia (Durbin-Watson):")
print(f"   Estadístico DW: {dw_stat:.4f}")
print(f"   Conclusión:     {'✓ Residuos independientes' if 1.5 < dw_stat < 2.5 else '⚠ Posible autocorrelación'}")

# PASO 7: Condiciones Óptimas
print("\n[PASO 7] Condiciones Óptimas para Maximizar AWC")
print("-" * 80)

# Identificar qué niveles maximizan AWC
optimo = {}
for idx, factor in enumerate(factores):
    if modelo.coef_[idx] > 0:
        optimo[factor] = "Alto (+1)"
        valor_recomendado = df[factor].quantile(0.75)
    else:
        optimo[factor] = "Bajo (-1)"
        valor_recomendado = df[factor].quantile(0.25)
    
    print(f"\n{factores_short[idx]:10s} ({factor}):")
    print(f"  Nivel óptimo:       {optimo[factor]}")
    print(f"  Valor recomendado:  {valor_recomendado:.2f}")

# Predicción con condiciones óptimas
X_optimo = np.array([[1 if modelo.coef_[i] > 0 else -1 for i in range(len(factores))]])
y_optimo_pred = modelo.predict(X_optimo)[0]

print(f"\nAWC predicho en condiciones óptimas: {y_optimo_pred:.2f} mm/m")
print(f"Mejora respecto a la media actual:   {y_optimo_pred - y.mean():.2f} mm/m ({((y_optimo_pred/y.mean())-1)*100:.1f}%)")

# PASO 8: Visualizaciones
print("\n[PASO 8] Generando Visualizaciones")
print("-" * 80)

# Gráfico de efectos principales
fig, ax = plt.subplots(figsize=(12, 6))
efectos_valores = [efectos_principales[f]['efecto'] for f in factores]
colores = ['green' if e > 0 else 'red' for e in efectos_valores]
bars = ax.barh(factores_short, efectos_valores, color=colores, alpha=0.7, edgecolor='black')
ax.axvline(0, color='black', linestyle='--', linewidth=1)
ax.set_xlabel('Efecto sobre AWC (mm/m)', fontsize=12, fontweight='bold')
ax.set_title('Efectos Principales de los Factores sobre Agua Disponible (AWC)', fontsize=14, fontweight='bold')
ax.grid(axis='x', alpha=0.3)
for idx, (bar, valor) in enumerate(zip(bars, efectos_valores)):
    ax.text(valor + 0.5 if valor > 0 else valor - 0.5, idx, f'{valor:.2f}', 
            ha='left' if valor > 0 else 'right', va='center', fontweight='bold')
plt.tight_layout()
plt.savefig('efectos_principales.png', dpi=300, bbox_inches='tight')
print("✓ Gráfico guardado: efectos_principales.png")

# Gráfico de interacciones
fig, ax = plt.subplots(figsize=(12, 6))
nombres_inter = list(interacciones_2.keys())
valores_inter = [interacciones_2[n]['efecto'] for n in nombres_inter]
colores_inter = ['blue' if abs(v) > 1 else 'gray' for v in valores_inter]
bars = ax.barh(nombres_inter, valores_inter, color=colores_inter, alpha=0.6, edgecolor='black')
ax.axvline(0, color='black', linestyle='--', linewidth=1)
ax.set_xlabel('Efecto de Interacción sobre AWC (mm/m)', fontsize=12, fontweight='bold')
ax.set_title('Interacciones de 2° Orden', fontsize=14, fontweight='bold')
ax.grid(axis='x', alpha=0.3)
plt.tight_layout()
plt.savefig('interacciones_2orden.png', dpi=300, bbox_inches='tight')
print("✓ Gráfico guardado: interacciones_2orden.png")

# Gráfico de residuos
fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('Diagnóstico de Residuos del Modelo', fontsize=16, fontweight='bold')

# a) Residuos vs Predichos
axes[0, 0].scatter(y_pred, residuos, alpha=0.5, s=20, edgecolors='k', linewidth=0.3)
axes[0, 0].axhline(0, color='red', linestyle='--', linewidth=2)
axes[0, 0].set_xlabel('Valores Predichos (mm/m)')
axes[0, 0].set_ylabel('Residuos (mm/m)')
axes[0, 0].set_title('Residuos vs Predichos')
axes[0, 0].grid(alpha=0.3)

# b) Q-Q Plot
stats.probplot(residuos, dist="norm", plot=axes[0, 1])
axes[0, 1].set_title('Q-Q Plot (Normalidad)')
axes[0, 1].grid(alpha=0.3)

# c) Histograma de residuos
axes[1, 0].hist(residuos, bins=30, edgecolor='black', alpha=0.7, color='steelblue')
axes[1, 0].axvline(0, color='red', linestyle='--', linewidth=2)
axes[1, 0].set_xlabel('Residuos (mm/m)')
axes[1, 0].set_ylabel('Frecuencia')
axes[1, 0].set_title('Distribución de Residuos')
axes[1, 0].grid(axis='y', alpha=0.3)

# d) Residuos vs Orden
axes[1, 1].plot(range(len(residuos)), residuos, 'o', alpha=0.5, markersize=3)
axes[1, 1].axhline(0, color='red', linestyle='--', linewidth=2)
axes[1, 1].set_xlabel('Orden de Observación')
axes[1, 1].set_ylabel('Residuos (mm/m)')
axes[1, 1].set_title('Residuos vs Orden (Independencia)')
axes[1, 1].grid(alpha=0.3)

plt.tight_layout()
plt.savefig('diagnostico_residuos.png', dpi=300, bbox_inches='tight')
print("✓ Gráfico guardado: diagnostico_residuos.png")

# Gráfico de valores reales vs predichos
plt.figure(figsize=(10, 8))
plt.scatter(y, y_pred, alpha=0.5, s=30, edgecolors='k', linewidth=0.5)
plt.plot([y.min(), y.max()], [y.min(), y.max()], 'r--', linewidth=2, label='Línea perfecta (y=ŷ)')
plt.xlabel('AWC Observado (mm/m)', fontsize=12)
plt.ylabel('AWC Predicho (mm/m)', fontsize=12)
plt.title(f'Valores Reales vs Predichos (R² = {r2:.4f})', fontsize=14, fontweight='bold')
plt.legend()
plt.grid(alpha=0.3)
plt.text(0.05, 0.95, f'RMSE = {rmse:.2f} mm/m\nMAE = {mae:.2f} mm/m', 
         transform=plt.gca().transAxes, fontsize=11, verticalalignment='top',
         bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.7))
plt.tight_layout()
plt.savefig('real_vs_predicho.png', dpi=300, bbox_inches='tight')
print("✓ Gráfico guardado: real_vs_predicho.png")

# PASO 9: Guardar resultados
print("\n[PASO 9] Guardando Resultados")
print("-" * 80)

# Crear dataframe con resultados
resultados_df = pd.DataFrame({
    'Factor': factores_short,
    'Nombre_Completo': factores,
    'Efecto_Principal': [efectos_principales[f]['efecto'] for f in factores],
    'Coeficiente_Regresion': modelo.coef_,
    'F_statistic': [resultados_anova[f]['f_stat'] for f in factores],
    'p_value': [resultados_anova[f]['p_value'] for f in factores],
    'Significativo': [resultados_anova[f]['significativo'] for f in factores],
    'Nivel_Optimo': [optimo[f] for f in factores]
})

resultados_df.to_excel('resultados_analisis_factorial.xlsx', index=False)
print("✓ Resultados guardados: resultados_analisis_factorial.xlsx")

# Guardar resumen de modelo
with open('resumen_modelo.txt', 'w', encoding='utf-8') as f:
    f.write("="*80 + "\n")
    f.write("RESUMEN DEL ANÁLISIS FACTORIAL 2^4\n")
    f.write("Optimización de Agua Disponible (AWC)\n")
    f.write("="*80 + "\n\n")
    
    f.write("MODELO DE REGRESIÓN:\n")
    f.write(f"AWC = {modelo.intercept_:.4f} + {modelo.coef_[0]:.4f}·Arcilla + {modelo.coef_[1]:.4f}·MO + {modelo.coef_[2]:.4f}·DA + {modelo.coef_[3]:.4f}·Prof\n\n")
    
    f.write("BONDAD DE AJUSTE:\n")
    f.write(f"R² = {r2:.4f}\n")
    f.write(f"RMSE = {rmse:.4f} mm/m\n")
    f.write(f"MAE = {mae:.4f} mm/m\n\n")
    
    f.write("EFECTOS PRINCIPALES:\n")
    for idx, factor in enumerate(factores):
        f.write(f"{factores_short[idx]:10s}: {efectos_principales[factor]['efecto']:7.2f} mm/m  ({resultados_anova[factor]['significativo']})\n")
    
    f.write("\nCONDICIONES ÓPTIMAS:\n")
    for idx, factor in enumerate(factores):
        f.write(f"{factores_short[idx]:10s}: {optimo[factor]}\n")
    
    f.write(f"\nAWC PREDICHO EN ÓPTIMO: {y_optimo_pred:.2f} mm/m\n")
    f.write(f"MEJORA VS MEDIA ACTUAL: {y_optimo_pred - y.mean():.2f} mm/m ({((y_optimo_pred/y.mean())-1)*100:.1f}%)\n")

print("✓ Resumen guardado: resumen_modelo.txt")

print("\n" + "="*80)
print("ANÁLISIS COMPLETADO")
print("="*80)
print("\nArchivos generados:")
print("  1. efectos_principales.png")
print("  2. interacciones_2orden.png")
print("  3. diagnostico_residuos.png")
print("  4. real_vs_predicho.png")
print("  5. resultados_analisis_factorial.xlsx")
print("  6. resumen_modelo.txt")
