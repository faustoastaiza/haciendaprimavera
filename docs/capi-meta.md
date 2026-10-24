# Píxel de Meta + API de conversiones (CAPI) · Hacienda Primavera

**Conjunto de datos:** «PIXEL HACIENDA» · ID `1879621982910759` · negocio PROArquitectura (`803879177346061`).

| Pieza | Estado |
|---|---|
| Píxel en el navegador | Instalado desde el código (`CONFIG.pixelId` en `index.html`). |
| Relevo del servidor | `api/meta-eventos.php` (PHP, mismo dominio). **Solo funciona cuando existe el archivo secreto con el token** (§3). |
| Activación del relevo en la página | `CONFIG.capiUrl: '/api/meta-eventos.php'` en `index.html` (vacío = solo navegador). |

## 1. Cómo funciona

```mermaid
flowchart LR
  N["Navegador<br/>(clic en WhatsApp)"] -->|"fbq trackCustom<br/>eventID = X"| P["Meta · píxel"]
  N -->|"POST /api/meta-eventos.php<br/>event_id = X"| R["Relevo PHP<br/>(tu hosting)"]
  R -->|"Graph API v25.0<br/>+ IP + agente + token"| C["Meta · API de conversiones"]
  P --> D(["Meta junta los dos en uno:<br/>mismo nombre + mismo event_id"])
  C --> D
```

El **token de acceso nunca está en el navegador ni en el repositorio** (el repositorio es público): vive en un archivo que solo existe en el servidor y que solo lee `api/meta-eventos.php`. Si el archivo no existe, el relevo responde `204` y no hace nada.

## 2. Qué se envía

- **Eventos por servidor:** `ContactoWhatsApp` (la conversión), `ClicIntencionPrecio` y `VioPrecio`. `PageView` va **solo por el navegador**: en el primer instante todavía no existe la cookie `_fbp` y el aporte del servidor sería mínimo. Por eso Meta mostrará la «cobertura» de `PageView` solo del navegador; es lo esperado.
- **Parámetros del evento:** los mismos que ve el píxel (`proyecto`, `boton`, `calidad`, `tipologia`, `proposito`, `forma_pago`, `calificador_completo`, UTM…). El relevo solo deja pasar una lista cerrada de campos y descarta cualquier otro.
- **Datos del visitante:** IP y agente de usuario (los pone el servidor), `fbp` y `fbc` (cookies del píxel; si no hay `_fbc` se arma con el `fbclid` del anuncio). **No hay correo, teléfono ni nombre**: la página no los pide. Consecuencia: la *Calidad de coincidencia de eventos* (EMQ) será baja o media; es normal en una landing que termina en WhatsApp. No se mejora enviando datos personales sin consentimiento.
- **Deduplicación:** el navegador crea un `event_id` por evento y lo manda al píxel (`eventID`) y al relevo. Meta cuenta una sola vez los eventos con el mismo nombre y el mismo `event_id`.

## 3. Puesta en marcha (una sola vez, la hace quien administra el hosting)

1. **Token.** Events Manager → *PIXEL HACIENDA* → **Configuración** → *API de conversiones* → **Generar token de acceso**. Se muestra una sola vez. **No lo pegues en chats, correos ni en el repositorio**; si se filtra, reemplázalo (ver §6).
2. **Archivo secreto.** En hPanel → *Administrador de archivos* crea `capi-secret.php` **fuera de `public_html`**: en la carpeta raíz de la cuenta (la que contiene `domains`) o, si no la ves, una carpeta por encima de `public_html`. Contenido:

   ```php
   <?php
   return [
       'pixel_id'        => '1879621982910759',
       'access_token'    => 'PEGA_AQUÍ_EL_TOKEN',
       'test_event_code' => '',   // opcional: el código de «Probar eventos» (TEST…); bórralo al terminar
   ];
   ```

   El relevo busca ese archivo en varias carpetas por encima del sitio y en la raíz de la cuenta. **Importante:** el 24-oct-2026 el primer archivo desapareció tras una publicación automática, así que **no lo pongas dentro de `public_html`**. Si no hay más remedio, el relevo también acepta `public_html/.capi-secret.php` (o `public_html/capi-secret.php`): el `.htaccess` impide verlo desde la web y el `.gitignore` lo protege de una limpieza de archivos sin versionar, pero no está garantizado que sobreviva.

3. **Comprobar.** Abre `https://haciendaprimavera.co/api/meta-eventos.php?estado`:
   - `"configurado":true` → el relevo encontró el archivo. Revisa también que `ip_detectada` sea tu IP real (si sale una IP del proveedor, avisa: habría que ajustar la cabecera que se lee).
   - `"secreto_en"` dice en qué carpeta encontró el archivo (solo una descripción, nunca la ruta real). Después de **cualquier** publicación, vuelve a abrir esta dirección: debe seguir diciendo `configurado:true`.
   - `"ultimo_envio"` muestra el resultado del último evento que el relevo mandó a Meta: `"aceptado":true` = Meta lo recibió; `"aceptado":false` trae el `http` y el código de error de Meta (`190` = token inválido o vencido; `100` = parámetro inválido; `200`/`10` = permisos). No incluye el token ni datos del visitante.
   - `"configurado":false` → no encontró el archivo (revisa nombre y carpeta).
   - Si el navegador descarga el archivo o muestra código PHP → el plan de hosting no ejecuta PHP (ver §7).
4. **Probar con «Probar eventos».** Events Manager → *PIXEL HACIENDA* → **Probar eventos** → copia el código (`TEST…`) → ponlo en `test_event_code` del archivo secreto → abre el sitio desde el enlace de esa pestaña, elige respuestas y pulsa el botón de WhatsApp. Deben aparecer dos filas por evento (**Navegador** y **Servidor**) con el mismo ID de evento y la marca de **deduplicado**. Cuando todo esté bien, **deja `test_event_code` vacío** (con el código puesto, Meta no cuenta esos eventos como reales).
5. **Activar.** Con el paso 3 en verde, `CONFIG.capiUrl` debe valer `/api/meta-eventos.php` en `index.html` (ya está así si lees esto después de la publicación).

## 4. Qué revisar en Meta (pestaña «Configuración» del conjunto de datos y alrededores)

Los nombres exactos pueden variar según el idioma y la versión de tu panel; esto es lo que importa (verificado: uso de datos y cookies propias, leídos de la cuenta; el resto, por la documentación y guías de Meta):

| Dónde | Qué dejar |
|---|---|
| Uso de datos | «Publicidad y análisis» (ya está así). |
| Cookies propias (first-party) | **Activadas** (ya lo están): `_fbp` y `_fbc` duran más y mejoran la coincidencia. |
| «Seguimiento automático de eventos sin código» (*Track events automatically without code*) | **Apagado.** La página manda sus propios eventos; la detección automática solo sumaría ruido (por ejemplo, un evento por cada botón). |
| Coincidencia avanzada automática | Puede quedar como esté: la página no tiene campos de correo ni teléfono, así que no tiene nada que leer. |
| Cuentas publicitarias | **Asigna la cuenta «Hacienda Primavera» al conjunto de datos** (Configuración del negocio → Orígenes de datos → Conjuntos de datos → asignar activos). Sin esto la campaña no puede elegirlo. |
| Permisos de tráfico → Sitios web (lista de dominios permitidos), si tu panel la muestra | Opcional: agrega `haciendaprimavera.co` para que ningún otro sitio pueda mandar eventos a este conjunto de datos. Después de activarla, repite la prueba del §3.4 y confirma que los eventos de **Servidor** siguen llegando (si dejaran de llegar, quita la restricción). |
| Verificación de dominio | Ya hecha (etiqueta `facebook-domain-verification` en el `<head>`). |
| Eventos agregados / prioridad de eventos | Meta fue retirando esta configuración para eventos web; solo si tu panel todavía te la pide, pon `ContactoWhatsApp` de primero. |

**Conversión personalizada** (para que la campaña optimice hacia personas y no hacia clics repetidos). Hay que crearla **después** de que haya llegado al menos un `ContactoWhatsApp` (hasta entonces Meta no ofrece sus parámetros):

1. Events Manager → **Conversiones personalizadas** → Crear.
2. Origen de datos: *PIXEL HACIENDA* · Evento: `ContactoWhatsApp` · Regla: parámetro `repetido` **no es igual a** `true`.
3. Nombre: «Contacto WhatsApp (Hacienda)». Categoría: *Contacto* o *Cliente potencial*. Sin valor.
4. En el conjunto de anuncios: ubicación de conversión **Sitio web** y evento de conversión = esa conversión personalizada.
5. Opcional, para campañas de calidad: una segunda conversión con la regla `calificador_completo` **es igual a** `true`.

## 5. Las cuatro métricas de la pestaña «Resumen»

- **Calidad de coincidencia de eventos:** esperable baja/media (§2). No es un error.
- **Tasa de deduplicación:** debe ser **alta** (cerca del 100 % de los eventos que salen por las dos vías). Si es baja, el `event_id` no coincide: revisa que `CONFIG.capiUrl` y el píxel estén en la misma versión de `index.html`.
- **Actualización de datos:** los eventos llegan en segundos (se mandan al instante).
- **Cobertura de la API de conversiones:** debe aparecer para `ContactoWhatsApp`, `ClicIntencionPrecio` y `VioPrecio`; `PageView` no (a propósito).

## 6. Seguridad y privacidad

- **Token solo en el servidor.** El repositorio es público: **nunca** va en `index.html`, `api/` ni `docs/`. `tools/check_trazabilidad.py` falla si encuentra algo con forma de token de Meta, `.gitignore` ignora `capi-secret.php` y `.htaccess` devuelve 403 a cualquier `capi-secret.php` pedido por la web. Las respuestas de error y `?estado` no incluyen el token.
- **Qué acepta el relevo.** Solo `POST` desde `haciendaprimavera.co` (origen y `Sec-Fetch-Site`), hasta 8 KB, solo los tres eventos de la lista, solo campos conocidos con valores de las listas y rangos que usa la página, hasta **40 solicitudes por minuto por IP y 300 en total**. La IP sale de `REMOTE_ADDR` (detrás del CDN de Hostinger es el visitante); `X-Forwarded-For` y `True-Client-IP` los escribe quien quiera, así que solo se miran si `REMOTE_ADDR` fuera de una red interna.
- **Qué NO es: autenticación.** Cualquier programa puede imitar el origen del sitio y mandar eventos «válidos», igual que cualquiera puede mandarle eventos falsos al píxel del navegador (su dirección es pública). Los topes y las listas solo **acotan el daño**; no lo impiden. Si algún día se notan conversiones sospechosas, la salida es revisar `?estado` y los patrones de `repetido`/`calidad` en Meta.
- **Si se agrega una opción al formulario**, hay que agregarla también a `HP_ENUMS` en `api/meta-eventos.php`; si no, el servidor descartaría ese valor en silencio. `tools/check_trazabilidad.py` lo avisa.
- **Respuesta rápida.** Cuando el servidor lo permite (LiteSpeed), el relevo contesta `204` al navegador antes de hablar con Meta, y los tiempos de espera hacia Meta son cortos (2 s para conectar, 4 s en total), para no tener procesos de PHP esperando.
- **Aviso al visitante.** El pie de página y el formulario dicen qué herramientas usa la página: Google Analytics, Clarity (que puede **grabar la sesión de navegación**) y el Píxel de Meta con su API de conversiones (que también recibe la **IP y el tipo de navegador**, para medir y optimizar la publicidad), y que se pueden rechazar desde el navegador o con un bloqueador. **No hay ventana de consentimiento previo ni botón para rechazar**: si se quiere consentimiento previo (recomendable con pauta), falta un banner. Si se agrega o quita una herramienta, hay que actualizar esas dos frases.
- **Si el token se filtró** (por ejemplo, se pegó en un chat), **reemplázalo**: genera uno nuevo en Events Manager, ponlo en el archivo secreto y **revoca el anterior** (Configuración del negocio → Usuarios del sistema, o donde tu panel muestre los tokens del conjunto de datos). Comprueba después en «Probar eventos» que los eventos de Servidor siguen llegando.

## 7. Si algo falla

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| `?estado` descarga un archivo o muestra código | El hosting no ejecuta PHP | Activar PHP en hPanel; si el plan no lo permite, usar el *Conversions API Gateway* de Meta (todo desde Events Manager, con costo de nube) o una función en Vercel con el mismo contrato (`POST` con `event_name`, `event_id`, `event_source_url`, `fbp`, `fbc`, `custom_data`). |
| `?estado` dice `configurado:false` | El archivo secreto no está donde se busca, o una publicación lo borró | Crearlo de nuevo en la raíz de la cuenta (la carpeta que contiene `domains`), fuera de `public_html`. |
| En «Probar eventos» solo sale **Navegador** | Falta `capiUrl`, el token es inválido o el código de prueba no está puesto | Ver `error_log` de PHP en hPanel: el relevo escribe `[meta-capi] … HTTP …` (nunca el token). |
| En «Probar eventos» salen los dos pero **sin deduplicar** | El nombre o el `event_id` no coinciden | No se debe editar `send()`; revisar versiones. |
| EMQ muy bajo | No hay correo/teléfono | Es esperado; ver §2. |

## 8. Cómo se probó (sin tocar Meta real)

Servidor PHP local + un «Meta» de mentira + Chrome sin cabeza: el relevo rechaza lo inválido (origen, JSON, evento, `event_id`, tamaño, topes por IP y totales), filtra campos y valores, ignora IP falsas, reenvía a `/v25.0/<píxel>/events` con el token solo en el servidor, y el `event_id` del servidor coincide con el `eventID` del píxel. Con la librería real del píxel (envío bloqueado): un solo `PageView`, ninguno por saltos de ancla y `eid` en cada evento.

Fuentes: [Mejores prácticas de la API de conversiones](https://developers.facebook.com/docs/marketing-api/conversions-api/best-practices) · [Graph API v25.0](https://developers.facebook.com/docs/graph-api/changelog/version25.0).
