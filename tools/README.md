# Herramientas de publicación

Scripts de apoyo (no se suben al servidor). Solo necesitan Python 3, sin dependencias.

## Flujo cuando cambies `index.html`

1. **Si cambiaste texto de las preguntas frecuentes, las tipologías, el contacto o el título/descripción**, regenera y valida los datos estructurados (JSON-LD):

   ```bash
   python3 tools/build_jsonld.py index.html          # escribe el bloque
   python3 tools/build_jsonld.py --check index.html  # debe terminar con "CHECK: OK"
   ```

2. Arma el paquete listo para subir:

   ```bash
   python3 tools/build_publicar.py
   ```

   Crea `_publicar/` y `hacienda-primavera-para-subir.zip` (ambos ignorados por git). El HTML del paquete
   va minificado de forma conservadora; el `index.html` de la raíz sigue legible.

3. Sube **el contenido del ZIP** a `public_html` en Hostinger (Administrador de archivos → subir → extraer).
   Incluye el archivo oculto `.htaccess`. No subas la raíz del repositorio.

## Después de subir

- `curl -sI https://haciendaprimavera.co/` → debe traer cabeceras de seguridad y `content-encoding`.
- `curl -sI https://www.haciendaprimavera.co/` → debe responder `301` a `https://haciendaprimavera.co/`.
- Search Console: Inspección de URL → "Probar URL publicada" → solicitar indexación.
