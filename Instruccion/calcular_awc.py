"""
Script para calcular Agua Disponible (AWC) y preparar datos para Diseño Factorial
AWC = (Capacidad de Campo - Punto de Marchitez) × Profundidad Efectiva
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from scipy import stats

# Cargar dataset
df = pd.read_excel('dataset_edafologico_sintetico.xlsx')

print("="*80)
print("CÁLCULO DE AGUA DISPONIBLE (AWC)")
print("="*80)

# PASO 1: Calcular Capacidad de Campo (CC) y Punto de Marchitez (PM)
# Fórmulas pedotransfer simplificadas (Saxton & Rawls, 2006)

def calcular_cc(arcilla, arena, materia_organica):
    """Capacidad de Campo a -33 kPa (θ_33)"""
    # Modelo simplificado (valores en %)
    theta_33 = (
        0.299 - 0.251 * (arena/100) + 0.195 * (arcilla/100) + 
        0.011 * (materia_organica) + 0.006 * (arena/100) * (materia_organica) - 
        0.027 * (arcilla/100) * (materia_organica) + 
        0.452 * (arcilla/100)**2 + 0.299
    )
    return theta_33 * 100  # Convertir a %

def calcular_pm(arcilla, arena, materia_organica):
    """Punto de Marchitez a -1500 kPa (θ_1500)"""
    theta_1500 = (
        0.031 - 0.024 * (arena/100) + 0.487 * (arcilla/100) + 
        0.006 * (materia_organica) + 0.005 * (arena/100) * (materia_organica) - 
        0.013 * (arcilla/100) * (materia_organica) + 
        0.068 * (arcilla/100)**2 + 0.031
    )
    return theta_1500 * 100  # Convertir a %

# Aplicar cálculos
df['cc_pct'] = df.apply(lambda row: calcular_cc(
    row['arcilla_pct'], 
    row['arena_pct'], 
    row['materia_organica_pct']
), axis=1)

df['pm_pct'] = df.apply(lambda row: calcular_pm(
    row['arcilla_pct'], 
    row['arena_pct'], 
    row['materia_organica_pct']
), axis=1)

# PASO 2: Calcular profundidad efectiva del horizonte
df['profundidad_efectiva_cm'] = df['depth_cm_to'] - df['depth_cm_from']

# PASO 3: Calcular AWC (mm/m de profundidad)
# AWC = (CC - PM) × Densidad Aparente × Profundidad / 10
# Factor 10 para convertir cm × g/cm³ × % → mm
df['awc_mm_m'] = (
    (df['cc_pct'] - df['pm_pct']) * 
    df['densidad_aparente_g_cm3'] * 
    df['profundidad_efectiva_cm'] / 10
)

print("\nEstadísticas de AWC calculado:")
print(df['awc_mm_m'].describe())
print(f"\nRango AWC: {df['awc_mm_m'].min():.2f} - {df['awc_mm_m'].max():.2f} mm/m")
print(f"Media AWC: {df['awc_mm_m'].mean():.2f} ± {df['awc_mm_m'].std():.2f} mm/m")

# PASO 4: Identificar correlaciones con factores
print("\n" + "="*80)
print("CORRELACIONES CON FACTORES (X)")
print("="*80)

factores = ['arcilla_pct', 'materia_organica_pct', 'densidad_aparente_g_cm3', 'profundidad_efectiva_cm']
correlaciones = df[factores + ['awc_mm_m']].corr()['awc_mm_m'].drop('awc_mm_m').sort_values(ascending=False)

print("\nCorrelaciones de Pearson con AWC:")
for factor, corr in correlaciones.items():
    print(f"  {factor:40s}: r = {corr:6.3f}")

# PASO 5: Clasificar niveles para diseño factorial (cuartiles)
print("\n" + "="*80)
print("NIVELES DE FACTORES (Bajo = Q1, Alto = Q3)")
print("="*80)

niveles = {}
for factor in factores:
    q1 = df[factor].quantile(0.25)
    q3 = df[factor].quantile(0.75)
    niveles[factor] = {'bajo': q1, 'alto': q3}
    print(f"\n{factor}:")
    print(f"  Nivel Bajo  (-1): {q1:.2f}")
    print(f"  Nivel Alto  (+1): {q3:.2f}")
    print(f"  Rango:            {q3 - q1:.2f}")

# PASO 6: Crear dataset codificado para diseño factorial 2^4
print("\n" + "="*80)
print("CODIFICACIÓN FACTORIAL")
print("="*80)

# Codificar factores a -1 (bajo) y +1 (alto)
df_factorial = df[factores + ['awc_mm_m']].copy()

for factor in factores:
    mediana = df[factor].median()
    df_factorial[f'{factor}_coded'] = df_factorial[factor].apply(
        lambda x: -1 if x < mediana else 1
    )

# Guardar resultados
df.to_excel('dataset_con_awc.xlsx', index=False)
df_factorial.to_excel('dataset_factorial_codificado.xlsx', index=False)

print(f"\n✓ Dataset con AWC guardado: dataset_con_awc.xlsx")
print(f"✓ Dataset factorial codificado: dataset_factorial_codificado.xlsx")

# PASO 7: Visualizaciones exploratorias
print("\n" + "="*80)
print("GENERANDO VISUALIZACIONES")
print("="*80)

fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('Relación entre Factores y Agua Disponible (AWC)', fontsize=16, fontweight='bold')

for idx, factor in enumerate(factores):
    ax = axes[idx // 2, idx % 2]
    ax.scatter(df[factor], df['awc_mm_m'], alpha=0.6, s=30, edgecolors='k', linewidth=0.5)
    
    # Línea de tendencia
    z = np.polyfit(df[factor], df['awc_mm_m'], 1)
    p = np.poly1d(z)
    x_line = np.linspace(df[factor].min(), df[factor].max(), 100)
    ax.plot(x_line, p(x_line), "r--", alpha=0.8, linewidth=2)
    
    ax.set_xlabel(factor.replace('_', ' ').title(), fontsize=11)
    ax.set_ylabel('AWC (mm/m)', fontsize=11)
    ax.grid(True, alpha=0.3)
    ax.text(0.05, 0.95, f'r = {correlaciones[factor]:.3f}', 
            transform=ax.transAxes, fontsize=10, verticalalignment='top',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

plt.tight_layout()
plt.savefig('awc_factores_correlacion.png', dpi=300, bbox_inches='tight')
print("✓ Gráfico guardado: awc_factores_correlacion.png")

# Histograma de AWC
plt.figure(figsize=(10, 6))
plt.hist(df['awc_mm_m'], bins=30, edgecolor='black', alpha=0.7, color='steelblue')
plt.axvline(df['awc_mm_m'].mean(), color='red', linestyle='--', linewidth=2, label=f'Media = {df["awc_mm_m"].mean():.2f}')
plt.axvline(df['awc_mm_m'].median(), color='green', linestyle='--', linewidth=2, label=f'Mediana = {df["awc_mm_m"].median():.2f}')
plt.xlabel('Agua Disponible AWC (mm/m)', fontsize=12)
plt.ylabel('Frecuencia', fontsize=12)
plt.title('Distribución de Agua Disponible en el Dataset', fontsize=14, fontweight='bold')
plt.legend()
plt.grid(axis='y', alpha=0.3)
plt.tight_layout()
plt.savefig('awc_distribucion.png', dpi=300, bbox_inches='tight')
print("✓ Gráfico guardado: awc_distribucion.png")

# Mapa de correlaciones
plt.figure(figsize=(8, 6))
corr_matrix = df[factores + ['awc_mm_m']].corr()
sns.heatmap(corr_matrix, annot=True, fmt='.3f', cmap='coolwarm', center=0, 
            square=True, linewidths=1, cbar_kws={"shrink": 0.8})
plt.title('Matriz de Correlaciones: Factores vs AWC', fontsize=14, fontweight='bold')
plt.tight_layout()
plt.savefig('awc_matriz_correlacion.png', dpi=300, bbox_inches='tight')
print("✓ Gráfico guardado: awc_matriz_correlacion.png")

print("\n" + "="*80)
print("PROCESO COMPLETADO")
print("="*80)
print("\nArchivos generados:")
print("  1. dataset_con_awc.xlsx")
print("  2. dataset_factorial_codificado.xlsx")
print("  3. awc_factores_correlacion.png")
print("  4. awc_distribucion.png")
print("  5. awc_matriz_correlacion.png")
