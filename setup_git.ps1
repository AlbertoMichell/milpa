# Script de inicialización y subida a GitHub
# Ejecutar desde: c:\milpa

Write-Host "=== Configuración inicial de Git ===" -ForegroundColor Cyan

# Verificar si Git está instalado
try {
    git --version | Out-Null
} catch {
    Write-Host "Git no está instalado. Instalando..." -ForegroundColor Yellow
    winget install Git.Git
    Write-Host "Reinicia PowerShell y ejecuta este script de nuevo." -ForegroundColor Red
    exit 1
}

# Configurar usuario (cambia estos valores)
Write-Host "`nConfigura tu información de GitHub:" -ForegroundColor Yellow
$userName = Read-Host "Tu nombre completo"
$userEmail = Read-Host "Tu email de GitHub"

git config --global user.name "$userName"
git config --global user.email "$userEmail"

Write-Host "`n=== Inicializando repositorio Git ===" -ForegroundColor Cyan
git init

Write-Host "`n=== Agregando archivos ===" -ForegroundColor Cyan
git add .

Write-Host "`n=== Creando commit inicial ===" -ForegroundColor Cyan
git commit -m "Sistema RAG completo con extracción de entidades"

Write-Host "`n=== Siguiente paso ===" -ForegroundColor Green
Write-Host @"

1. Ve a https://github.com/new
2. Nombre del repositorio: milpa (o el que prefieras)
3. Privacidad: Privado (recomendado)
4. NO marques "Initialize with README"
5. Clic en "Create repository"
6. Copia la URL que aparece (ejemplo: https://github.com/tuusuario/milpa.git)
7. Ejecuta:

   git remote add origin https://github.com/TUUSUARIO/milpa.git
   git branch -M main
   git push -u origin main

8. GitHub te pedirá usuario/contraseña (o configurar token)

"@ -ForegroundColor White
