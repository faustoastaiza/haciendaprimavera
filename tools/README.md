# Herramientas de publicación

Scripts de apoyo (no se suben al servidor). Solo necesitan Python 3, sin dependencias.

## Flujo cuando cambies `index.html`

1. **Si cambiaste texto de las preguntas frecuentes, las tipologías, el contacto o el título/descripción**, regenera y valida los datos estructurados (JSON-LD):

   ```bash
   python3 tools/build_jsonld.py index.html          # escribe el bloque
   python3 tools/build_jsonld.py --check index.html  # debe terminar con "CHECK: OK"
   ```

2. **Si tocaste botones, el formulario, enlaces de contacto, las herramientas de medición o el bloque `TRAZABILIDAD WHATSAPP`**, comprueba el contrato del botón único de WhatsApp
   (un solo `wa.me` en `#contacto`; todo lo demás, anclas `href="#contacto"` con `data-cta` único; detalle en `docs/trazabilidad-whatsapp.md`):

   ```bash
   python3 tools/check_trazabilidad.py   # debe terminar con "CONTRATO OK"
   ```

   También comprueba que Google Analytics y Clarity estén una sola vez, que `CONFIG.capiUrl` apunte a un archivo que existe y que **ningún archivo del repositorio
   (que es público) tenga forma de token de Meta**. El empaquetado lo ejecuta solo y se detiene si el contrato se rompe.

3. **Publicar = `git push` a `main`.** El repositorio tiene el «Hostinger Auto Deploy»: en unos segundos el sitio queda igual que el repositorio
   (se publica el `index.html` legible, no el paquete). Prueba antes de subir y, después, compara producción con el repo:

   ```bash
   curl -s -H 'Accept: */*' -H 'Accept-Language: es' https://haciendaprimavera.co/ | shasum -a 256; shasum -a 256 index.html
   ```

4. *(Opcional)* Para una subida manual o como validación, arma el paquete:

   ```bash
   python3 tools/build_publicar.py
   ```

   Crea `_publicar/` y `hacienda-primavera-para-subir.zip` (ambos ignorados por git). El HTML del paquete va minificado de forma conservadora.
   Con `--require-pixel` se detiene si `CONFIG.pixelId` está vacío.

## La carpeta `api/`

`api/meta-eventos.php` es el relevo de la API de conversiones de Meta. **No lleva secretos**: el token vive en un archivo que solo existe en el servidor
(ver `docs/capi-meta.md`). Se publica con el resto del sitio.

## Después de publicar

- `curl -sI https://haciendaprimavera.co/` → debe traer cabeceras de seguridad y `content-encoding`.
- `curl -sI https://www.haciendaprimavera.co/` → debe responder `301` a `https://haciendaprimavera.co/`.
- `curl -s https://haciendaprimavera.co/api/meta-eventos.php?estado` → JSON con `"configurado":true` cuando el archivo secreto ya está en el servidor.
- Search Console: Inspección de URL → "Probar URL publicada" → solicitar indexación.
