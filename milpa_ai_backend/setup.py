from setuptools import setup

# Definir explícitamente el paquete milpa_ai_backend que está en la raíz
# donde se ejecuta setup.py (que será /app en Docker)
setup(
    name="milpa_ai_backend",
    version="1.0.0",
    packages=["milpa_ai_backend"],
    package_dir={"milpa_ai_backend": "."},
    install_requires=[],
)
