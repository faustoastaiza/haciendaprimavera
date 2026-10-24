# Botón único de WhatsApp · Hacienda Primavera

Toda la página converge en **un solo punto medible**: el botón «Escribir por WhatsApp» del formulario «Arma tu consulta», en la sección 13 · Contacto (`#contacto`). Es el único elemento de la página que abre WhatsApp. Los demás botones son anclas que llevan hasta él (y, si traen una intención —un modelo, el lote, el diseño propio—, dejan marcada la primera pregunta del formulario).

Usa los mismos nombres de evento y de parámetro que Alto de Yeguas para poder comparar landings, con las diferencias del §9.

```mermaid
flowchart LR
  A["17 anclas repartidas<br/>por la página"] -->|"#contacto"| B["Sección 13 · Contacto"]
  B --> Q["Formulario «Arma tu consulta»<br/>3 preguntas → el mensaje"]
  Q --> C(["Botón WhatsApp<br/>data-wa · data-cta = final"])
  C --> D["Evento ContactoWhatsApp<br/>(la ÚNICA conversión)"]
  D --> E["Conversión personalizada en Meta<br/>→ optimiza la campaña"]
  A -.-> F["ClicIntencionPrecio<br/>(señal, no optimiza)"]
  P["Bloque de precio #precio"] -.-> G["VioPrecio<br/>(señal, no optimiza)"]
```

Reglas:

1. **Un solo evento de conversión** (`ContactoWhatsApp`) y **un solo punto de salida** a WhatsApp.
2. **Todo lo demás son anclas** `<a href="#contacto" data-cta="…">`: nunca abren WhatsApp y cada una lleva un `data-cta` único.
3. Lo previo a la conversión es **señal** (`ClicIntencionPrecio`, `VioPrecio`): sirve para diagnóstico y retargeting, no para optimizar.

## 1. Mapa de botones

Se genera con `python3 tools/check_trazabilidad.py`. Todas las anclas son `href="#contacto"`.

| `data-cta` | Dónde está | Texto |
|---|---|---|
| `nav` | Cabecera | Asesoría |
| `menu-contacto` | Menú móvil (lista) | 13 Contacto |
| `menu` | Menú móvil (botón inferior) | Hablar con un asesor |
| `hero` | Portada | Hablar con un asesor |
| `precio-plan` | 01 · Inversión, tarjeta de precio | Solicitar plan de pagos |
| `precio-visita` | 01 · Inversión, tarjeta de precio | Agendar visita al proyecto |
| `exterior` | 03 · Desde el exterior | Escríbenos desde cualquier país |
| `diseno-propio` | 05 · Viviendas, sexta fila «Tu propio diseño» (dejan marcada «Mi propio diseño») | Cotizar mi diseño |
| `modelo-tulipan` `modelo-ilan` `modelo-arrayan` `modelo-urapan` `modelo-saman` | 05 · Viviendas, uno por modelo (dejan marcado ese modelo) | Cotizar *(modelo)* |
| `preguntas` | 10 · Preguntas frecuentes | Hacer otra pregunta |
| `lotes` | 12 · Lotes (deja marcado «Solo el lote») | Consultar lotes disponibles |
| `footer` | Pie de página | Contacto |
| `flotante` | Botón flotante «¿Hablamos?» (se oculta cuando el contacto o el pie están a la vista) | ¿Hablamos? |
| **`final`** | **13 · Contacto — el único que abre WhatsApp** | **Escribir por WhatsApp** |

Los enlaces de navegación entre secciones (`#inversion`, `#lotes`…) no son botones de contacto y no se miden.

Al saltar a `#contacto`, la sección sube casi todo su relleno superior (`scroll-margin-top` negativo en el CSS) para que el formulario quede a la vista justo debajo del encabezado, también en pantallas bajas. El formulario no usa `data-reveal`: debe verse al instante tras el salto.

## 2. El formulario y el botón único

```html
<div class="calif" data-calif role="group" aria-labelledby="t-calif">
  <fieldset data-label="Me interesa"> … <input type="radio" name="tipologia" value="tulipan" data-msg="casa Tulipán" data-desde="modelo-tulipan"> … </fieldset>
  …
  <a data-wa data-cta="final" href="https://wa.me/573178927252?text=…" target="_blank" rel="noopener">Escribir por WhatsApp</a>
</div>
```

**Qué ve la persona.** A la derecha (en móvil, primero) la tarjeta «Arma tu consulta · 3 toques»: tres preguntas con opciones tipo radio, una vista previa del mensaje («Así llegará tu mensaje») y el botón verde grande. A la izquierda, «Así funciona» (3 pasos) y la tarjeta «Un proyecto de PROA» (logo, años construyendo —se calculan desde 2014—, proyectos y unidades entregadas, y los datos de la sala de ventas). Responder es opcional: «También puedes escribir sin responder las preguntas».

| Pregunta | `name` (parámetro del evento) | Valores |
|---|---|---|
| 1. ¿Qué te interesa? | `tipologia` | `tulipan`, `ilan`, `arrayan`, `urapan`, `saman`, `diseno_propio`, `solo_lote`, `no_se` |
| 2. ¿Para qué la quieres? | `proposito` | `disfrutar`, `invertir`, `ambos` |
| 3. ¿Cómo piensas pagarla? | `forma_pago` | `plan_constructora`, `credito`, `propios`, `nose` |

- Cada opción es un `<input type="radio">` real (teclado con flechas, lectores de pantalla y toque funcionan de forma nativa). `value` = valor del evento; `data-msg` = texto que viaja en el mensaje; `data-desde` = el `data-cta` de la ancla que la deja marcada; el `data-label` del `fieldset` es el rótulo de la línea («Me interesa», «Es para», «Forma de pago»).
- **El mensaje** es el de siempre (`Hola, estuve revisando la web de Hacienda Primavera y quiero más información`) + el origen entre paréntesis si hay UTM + **una línea por respuesta**:

```
Hola, estuve revisando la web de Hacienda Primavera y quiero más información (fb · campaña · anuncio)
• Me interesa: casa Tulipán
• Es para: invertir y rentarla
• Forma de pago: plan de pagos con la constructora
```

  Sin respuestas ni UTM el enlace queda idéntico al del HTML. La vista previa muestra exactamente lo que se enviará (incluido el origen). «Borrar respuestas» las quita todas.
- El `href` va **completo en el HTML** y funciona aunque el JavaScript falle (sin JavaScript solo se ve el botón). Los UTM se limpian (sin emojis cortados, caracteres de control ni `< > " ' \``, máx. 60 caracteres) y se guardan en la sesión.
- El botón va **solo** (no hay botón de llamada), grande y en el verde de WhatsApp (`#25D366`, texto oscuro para el contraste). La fila «WhatsApp» de los datos de contacto es solo texto. `tel:` (pie de página) y `mailto:` no son WhatsApp y no se miden.
- Abrir el enlace con clic derecho o pulsación larga («abrir en pestaña nueva») no genera evento.
- **Aviso de tratamiento de datos** (Ley 1581) al pie del formulario, adaptado del de Alegranza: responsable Proarquitectura Constructora S.A.S., canal `comercial@proarquitectura.co` y las herramientas de medición que usa la página. **Si se instala o se quita una herramienta de medición, se actualiza esa frase y la del pie de página.** Conviene que lo revise quien lleve lo legal.

## 3. Eventos

| Evento | Cuándo | Parámetros | ¿Optimiza? |
|---|---|---|---|
| `PageView` | Solo al cargar y solo si el código instala el píxel (§5). Los saltos por ancla **no** suman `PageView` extra | — | No |
| `VioPrecio` | `#precio` entero en pantalla durante 1 s seguido (una vez por sesión). Pasar volando durante un salto no cuenta | `proyecto` | No |
| `ClicIntencionPrecio` | Clic en cualquiera de las 17 anclas | `proyecto`, `seccion` (= `data-cta`), `texto` | No |
| **`ContactoWhatsApp`** | Clic (o clic central) en el botón único. Máximo uno cada 2 s | `proyecto`, `boton`, `content_name`, `vio_precio`, `profundidad`, `segundos_en_pagina`, `calidad`, `clic_n`, `repetido`, las respuestas (`tipologia`, `proposito`, `forma_pago`; «sin_dato» si no respondió esa pregunta), `calificador_completo` (true si respondió las tres) y `utm_source` / `utm_campaign` / `utm_content` si hay | **Sí** |
| `calificador_respuesta` | Cada vez que se marca una opción. **Solo GA4, Clarity y `dataLayer`**: no va a Meta ni es conversión | `proyecto`, `pregunta`, `respuesta` | No |

- **Clics repetidos:** cada clic cuenta. `clic_n` es el número de clic en WhatsApp de la sesión y `repetido` es `true` desde el segundo. Para contar personas y no clics, crea la conversión personalizada con la regla `Evento = ContactoWhatsApp` **y** `repetido` distinto de `true` (a Meta los valores llegan como texto: «true» / «false»).
- Cada evento también viaja a **Google Analytics 4** (`G-0CBJ8NRH0J`, instalado con `gtag.js` en el `<head>`) como evento con el mismo nombre y los mismos parámetros (`vio_precio`, `cta_precio_click`, `contacto_whatsapp`), a **Microsoft Clarity** (`z2vmt8wkvr`: el evento queda como filtro de grabaciones y `calidad` como etiqueta de la sesión) y al `dataLayer` (objetos planos, por si algún día se instala GTM). Con `gtag.js` directo los objetos del `dataLayer` no llegan solos a GA4; por eso el script los reenvía con `gtag('event', …)`.
- **Ajustes en Google Analytics (los hace una persona con acceso, no el código):** (1) Admin → Flujos de datos → Medición mejorada → ⚙ → desactivar «Cambios de página basados en eventos del historial del navegador»: la página tiene decenas de enlaces con ancla (`#contacto`, `#renta`…) y sin eso GA4 puede contar una visita extra por cada salto. (2) Admin → Eventos → marcar `contacto_whatsapp` como **evento clave** (es la conversión). (3) Admin → Definiciones personalizadas → registrar como dimensiones de evento los parámetros que se quieran analizar (`boton`, `calidad`, `repetido`, `profundidad`, `utm_source`, `utm_campaign`, `utm_content`). (4) Si el equipo navega la página, filtrar su tráfico interno.

## 4. Calidad del lead

- `vio_precio`: se vio el precio (arriba).
- `profundidad`: **% de las 12 secciones de contenido que estuvieron al menos 1,5 s seguidos en la franja central de la pantalla** (no cuentan la portada ni el contacto). Un salto por ancla pasa volando y no suma, así que no se infla porque el contacto esté al final de la página. Mide ritmo de lectura, no comprensión: un scroll pausado cuenta; una pasada rápida no.
- `segundos_en_pagina`: tiempo con la pestaña visible.
- `calificador_completo`: respondió las tres preguntas. Se cruza con `calidad` para crear audiencias o conversiones más finas (ej. `calidad` = alta **o** `calificador_completo` = true).
- `calidad`: **alta** = vio el precio, ≥ 40 % y ≥ 60 s · **media** = (vio el precio o ≥ 20 %) y ≥ 20 s · **baja** = el resto. Son umbrales iniciales (`CONFIG.alta` y `CONFIG.media` en el script): ajústalos con datos reales.

## 5. Instalación del píxel (pendiente: el ID)

Falta el ID del píxel de Hacienda Primavera. Hasta que se ponga, **nada llega a Meta**: los eventos solo van al `dataLayer`.

- **Opción A, desde el código:** pega el ID (solo dígitos) en `CONFIG.pixelId` del bloque `TRAZABILIDAD WHATSAPP` de `index.html`. El script instala el píxel, envía `PageView` y desactiva el `PageView` automático por cambio de hash (`disablePushState`). Sin eso, el píxel suma un `PageView` por cada salto por ancla o enlace de menú (comprobado con la librería real de Meta).
- **Opción B, desde GTM:** deja `pixelId` vacío. Los eventos usan el `fbq` que ya exista. La etiqueta del píxel debe incluir `fbq.disablePushState = true;` **antes** del `init` (puesto después no hace efecto).
- **Un mismo ID nunca va en los dos sitios**: provoca «Duplicate Pixel ID» y `PageView` de más. Si ya hay un `fbq` en la página, el código no instala otro.
- Para el paquete de producción: `python3 tools/build_publicar.py --require-pixel` se detiene si `pixelId` está vacío. Sin el flag solo avisa al final.

Después de publicar: dispara `ContactoWhatsApp` una vez en producción y crea en Events Manager la conversión personalizada (ver la regla en §3). Esa es la que optimiza la campaña. La **verificación de dominio de Meta** ya está instalada: la etiqueta `facebook-domain-verification` está en el `<head>` de `index.html` (no la borres). Se verifica en Business Manager → Configuración del negocio → Seguridad de la marca → Dominios → `haciendaprimavera.co` → Verificar.

## 6. Verificación en 5 minutos

Abre la página con `?utm_source=fb&utm_medium=paid&utm_campaign=prueba&utm_content=anuncio1`.

- [ ] `python3 tools/check_trazabilidad.py` termina en `CONTRATO OK` (también se ejecuta al armar el paquete y lo detiene si falla).
- [ ] *Meta Pixel Helper* muestra `PageView` y **un solo** píxel por ID. Al pulsar anclas y enlaces del menú **no** aparecen `PageView` nuevos.
- [ ] Al quedarte con el precio entero en pantalla 1 s, `VioPrecio` aparece **una sola vez**.
- [ ] Un clic en cualquier ancla dispara `ClicIntencionPrecio` y **no** abre WhatsApp.
- [ ] El botón «Escribir por WhatsApp» abre WhatsApp en pestaña nueva y dispara **un solo** `ContactoWhatsApp` con `boton = final`.
- [ ] El mensaje empieza igual que siempre y lleva `(fb · prueba · anuncio1)` en la primera línea; la vista previa («Así llegará tu mensaje») muestra exactamente lo mismo.
- [ ] Marca una opción de cada pregunta: aparece una línea «• …» por respuesta, «Borrar respuestas» las quita y, al pulsar el botón, `ContactoWhatsApp` lleva `tipologia`, `proposito`, `forma_pago` y `calificador_completo = true`.
- [ ] «Cotizar Ilán», «Consultar lotes disponibles» y «Cotizar mi diseño» llevan al formulario con esa opción ya marcada.
- [ ] Consola: `document.querySelectorAll('[data-wa]').length === 1` y `dataLayer.filter(e => e.event)` muestra los eventos.

> No hagas clic en el botón de WhatsApp en producción para probar: cada clic cuenta como una conversión real. Usa un navegador con el píxel bloqueado o resta esas pruebas del reporte.

## 7. Cómo agregar un botón nuevo

- Si lleva a contactar: `<a class="btn …" href="#contacto" data-cta="nombre-unico">`.
- Si el botón trae una intención que el formulario conoce (un modelo, el lote, el diseño propio), pon su `data-cta` en el `data-desde` de la opción de la pregunta 1 (`<input … data-desde="nombre-unico">`): al pulsarlo, el formulario queda con esa opción marcada.
- Para cambiar una pregunta u opción, edita el HTML del formulario: `name` es el parámetro del evento, `value` el valor y `data-msg` el texto del mensaje. Si se agrega una pregunta nueva, súmala a `GRUPOS` en el script de trazabilidad.
- **Nunca** un `wa.me` suelto. El verificador detecta cualquier salida a WhatsApp (`href`, `onclick`, `whatsapp://`, `intent://`, scripts que abran WhatsApp) y las anclas con `target`; el empaquetado se detiene si el contrato se rompe.
- La página de error (`404.html`) también manda a `/#contacto` en vez de a WhatsApp.

## 8. Pendientes y decisiones abiertas

- **ID del píxel** (y GTM, GA4 o Clarity, si se quieren).
- **Aviso de cookies:** el pie de página y el formulario informan del uso de cookies y herramientas de medición (aviso informativo, sin ventana de consentimiento). Si se quiere consentimiento previo, falta un banner.
- **Aviso legal del formulario:** adaptado del de Alegranza; que lo revise quien lleve lo legal.
- **Llamadas y correos** no se miden.
- `llms.txt` conserva el enlace `wa.me` como dato de contacto para asistentes de IA (no es parte de la página y no pasa por el botón medido).

## 9. Diferencias con Alto de Yeguas

- Las anclas van **directo a `#contacto`**: aquí no hay sección intermedia de proceso ni botón puente.
- **No hay un segundo botón de WhatsApp**: el flotante «¿Hablamos?» es una ancla más.
- `profundidad` mide secciones leídas a ritmo pausado y no scroll máximo (con anclas el scroll siempre llega al final).
- `seccion` de `ClicIntencionPrecio` es el `data-cta` único y no el texto visible; el texto va aparte en `texto`.
- El bloque de precio (`#precio`) está en la sección 01 y no en el destino de las anclas, por eso `VioPrecio` exige que el precio se quede 1 s en pantalla.
- Se añaden `clic_n` y `repetido` a `ContactoWhatsApp`, y el píxel se instala con `disablePushState` para que los saltos por ancla no inflen los `PageView`.
- El formulario de preguntas está en la propia sección de contacto (no hay sección intermedia de proceso), con las preguntas propias de esta landing: modelo / diseño propio / solo el lote, para qué y cómo piensa pagar. Los parámetros se llaman igual que en Alegranza (`tipologia`, `proposito`, `forma_pago`, `calificador_completo`); aquí `calificador_completo` es booleano y `sin_dato` marca la pregunta sin responder.
