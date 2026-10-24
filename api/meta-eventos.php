<?php
/**
 * Relevo de la API de conversiones de Meta (CAPI) · haciendaprimavera.co
 *
 * El navegador manda aquí, por POST y desde el mismo dominio, cada evento importante (ContactoWhatsApp, ClicIntencionPrecio,
 * VioPrecio) con el MISMO event_id que ya envió el píxel. Este archivo lo completa con lo que solo el servidor sabe (IP y agente
 * de usuario reales) y lo reenvía a Meta con el token. Meta junta el evento del navegador y el del servidor en uno solo
 * (deduplicación: mismo nombre + mismo event_id).
 *
 * EL TOKEN NO VA EN ESTE ARCHIVO NI EN EL REPOSITORIO (el repositorio es público). Vive en un archivo PHP que solo existe en el
 * servidor y que este script busca fuera del sitio (ver rutas_secreto()): lo mejor es la raíz de la cuenta, la carpeta que contiene
 * «domains». Contenido (ver docs/capi-meta.md):
 *   <?php return ['pixel_id' => '…', 'access_token' => '…', 'test_event_code' => ''];
 * Si el servidor lo permite también se leen las variables de entorno META_PIXEL_ID, META_ACCESS_TOKEN y META_TEST_EVENT_CODE.
 *
 * Sin configuración responde 204 y no hace nada (así la página no muestra errores). Para comprobar que PHP corre, que el archivo
 * secreto se encontró y cómo salió el último envío: abrir /api/meta-eventos.php?estado en el navegador.
 *
 * QUÉ NO ES: no es autenticación. Cualquier programa puede imitar el origen del sitio, igual que cualquiera puede mandarle eventos
 * falsos al píxel del navegador. Lo que sí hace es acotar el daño: solo el origen del sitio, solo tres eventos, valores dentro de las
 * listas y rangos que usa la página, y topes por IP y en total por minuto.
 */

error_reporting(0);
ini_set('display_errors', '0');
header_remove('X-Powered-By');

const HP_EVENTOS = ['ContactoWhatsApp', 'ClicIntencionPrecio', 'VioPrecio'];
const HP_HOSTS = ['haciendaprimavera.co', 'www.haciendaprimavera.co'];
const HP_VERSION = 'v25.0';
const HP_MAX_IP = 40;      // solicitudes por minuto y por IP
const HP_MAX_TOTAL = 300;  // solicitudes por minuto en total (tope global: acota el daño de un ataque repartido en muchas IP)
const HP_MAX_IPS = 500;    // IP distintas que se recuerdan cada minuto: el archivo del límite nunca crece más

// Valores que la página puede mandar. Si se agrega una opción al formulario, hay que agregarla aquí
// (tools/check_trazabilidad.py avisa si faltan).
const HP_ENUMS = [
    'proyecto' => ['hacienda-primavera'],
    'content_name' => ['Hacienda Primavera'],
    'boton' => ['final'],
    'calidad' => ['alta', 'media', 'baja'],
    'tipologia' => ['tulipan', 'ilan', 'arrayan', 'urapan', 'saman', 'diseno_propio', 'solo_lote', 'no_se', 'sin_dato'],
    'proposito' => ['disfrutar', 'invertir', 'ambos', 'sin_dato'],
    'forma_pago' => ['plan_constructora', 'credito', 'propios', 'nose', 'sin_dato'],
];
const HP_BOOLS = ['vio_precio', 'repetido', 'calificador_completo'];
const HP_RANGOS = ['profundidad' => [0, 100], 'segundos_en_pagina' => [0, 86400], 'clic_n' => [1, 100]];
const HP_TEXTOS = ['texto' => 100, 'utm_source' => 60, 'utm_campaign' => 60, 'utm_content' => 60];

function responder($codigo, $cuerpo = null)
{
    http_response_code($codigo);
    header('Cache-Control: no-store');
    header('X-Content-Type-Options: nosniff');
    if ($cuerpo !== null) {
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode($cuerpo);
    }
    exit;
}

// Responde 204 al navegador YA y sigue trabajando por detrás (si el servidor lo permite): el visitante no espera a Meta y el
// proceso de PHP no queda ocupado mientras Meta tarda. Devuelve false si el servidor no lo soporta (entonces se responde al final).
function responder_ya()
{
    ignore_user_abort(true);
    foreach (['litespeed_finish_request', 'fastcgi_finish_request'] as $f) {
        if (function_exists($f)) {
            http_response_code(204);
            header('Cache-Control: no-store');
            header('X-Content-Type-Options: nosniff');
            $f();
            return true;
        }
    }
    return false;
}

// Dónde puede estar el archivo secreto, de la ubicación más segura a la menos. En el diagnóstico solo salen etiquetas, nunca rutas.
function rutas_secreto()
{
    $r = [];
    $agregar = function ($ruta, $etiqueta) use (&$r) {
        if (!isset($r[$ruta])) {   // si dos caminos son la misma ruta, vale la etiqueta del primero
            $r[$ruta] = $etiqueta;
        }
    };
    foreach ([2 => 'una carpeta por encima del sitio', 3 => 'dos carpetas por encima del sitio', 4 => 'tres carpetas por encima del sitio'] as $n => $etiqueta) {
        $agregar(dirname(__DIR__, $n) . '/capi-secret.php', $etiqueta);
    }
    $casa = getenv('HOME');
    if (!$casa && function_exists('posix_getpwuid') && function_exists('posix_geteuid')) {
        $u = @posix_getpwuid(@posix_geteuid());
        $casa = $u['dir'] ?? '';
    }
    if ($casa) {
        $agregar(rtrim($casa, '/') . '/capi-secret.php', 'raíz de la cuenta');
    }
    if (!empty($_SERVER['DOCUMENT_ROOT'])) {
        $raiz = rtrim($_SERVER['DOCUMENT_ROOT'], '/');
        $agregar(dirname($raiz) . '/capi-secret.php', 'una carpeta por encima de la raíz web');
        $agregar($raiz . '/.capi-secret.php', 'archivo oculto dentro del sitio (poco seguro)');
        $agregar($raiz . '/capi-secret.php', 'dentro del sitio (poco seguro)');
    }
    $agregar(dirname(__DIR__) . '/.capi-secret.php', 'archivo oculto dentro del sitio (poco seguro)');
    $agregar(dirname(__DIR__) . '/capi-secret.php', 'dentro del sitio (poco seguro)');
    return $r;
}

// Lee el archivo secreto SIN dejar que escriba nada en la respuesta. Si el archivo no empieza con <?php, PHP lo imprimiría tal cual
// (con el token adentro) en la respuesta pública: por eso toda su salida se descarta.
function leer_secreto($ruta)
{
    $x = null;
    $estado = 'ok';
    ob_start();
    try {
        $x = include $ruta;
    } catch (Throwable $e) {
        $estado = 'error de sintaxis';
    }
    $sobra = ob_get_clean();
    if ($estado === 'ok') {
        if (!is_array($x)) {
            $estado = $sobra !== '' && $sobra !== false ? 'no empieza con <?php' : 'no devuelve una lista (falta «return [ … ];»)';
        } elseif (empty($x['pixel_id']) || empty($x['access_token'])) {
            $estado = 'faltan pixel_id o access_token';
        }
    }
    return [$estado === 'ok' ? $x : null, $estado];
}

function cargar_config()
{
    $cfg = [];
    $donde = '';
    $buscado = [];
    foreach (rutas_secreto() as $ruta => $etiqueta) {
        $estado = 'no existe';
        if (is_file($ruta)) {
            if (!is_readable($ruta)) {
                $estado = 'existe, pero PHP no puede leerlo (permisos)';
            } else {
                list($x, $estado) = leer_secreto($ruta);
                if ($x !== null && $donde === '') {
                    $cfg = $x;
                    $donde = $etiqueta;
                }
            }
        }
        $buscado[] = ['donde' => $etiqueta, 'estado' => $estado];
    }
    $cfg['__ubicacion'] = $donde;
    $cfg['__buscado'] = $buscado;
    foreach (['pixel_id' => 'META_PIXEL_ID', 'access_token' => 'META_ACCESS_TOKEN', 'test_event_code' => 'META_TEST_EVENT_CODE',
        'graph_version' => 'META_GRAPH_VERSION', 'graph_base' => 'META_GRAPH_BASE', 'allowed_hosts' => 'META_ALLOWED_HOSTS'] as $k => $e) {
        $v = getenv($e);
        if (!isset($cfg[$k]) && $v !== false && $v !== '') {
            $cfg[$k] = $k === 'allowed_hosts' ? array_map('trim', explode(',', $v)) : $v;
        }
    }
    return $cfg;
}

// Archivos de las carpetas donde se busca cuyo nombre se parece a «capi…» (por ejemplo «capi-secret.php.txt» o «capi-secret (1).php»):
// ayuda a encontrar un archivo mal nombrado. Solo nombres, nunca contenido.
function nombres_parecidos()
{
    $out = [];
    $vistas = [];
    foreach (rutas_secreto() as $ruta => $etiqueta) {
        $carpeta = dirname($ruta);
        if (isset($vistas[$carpeta])) {
            continue;
        }
        $vistas[$carpeta] = true;
        foreach ((array) @scandir($carpeta) as $nombre) {
            if (is_string($nombre) && preg_match('/^\.?capi/i', $nombre) && basename($ruta) !== $nombre && count($out) < 12) {
                $out[] = ['nombre' => cortar($nombre, 60), 'en' => $etiqueta];
            }
        }
    }
    return $out;
}

// El token solo viaja a Meta. La dirección de pruebas (un «Meta» falso en la misma máquina) solo se acepta si es de esta máquina.
function base_graph($cfg)
{
    $base = rtrim((string) ($cfg['graph_base'] ?? ''), '/');
    if ($base !== '' && in_array(host_de($base), ['graph.facebook.com', '127.0.0.1', 'localhost'], true)) {
        return $base;
    }
    return 'https://graph.facebook.com';
}

// ¿Es una dirección de internet (no de una red interna, ni de esta máquina)?
function ip_publica($ip)
{
    if (!is_string($ip) || !filter_var($ip, FILTER_VALIDATE_IP, FILTER_FLAG_NO_PRIV_RANGE)) {
        return false;
    }
    return !preg_match('/^(127\.|0\.|169\.254\.|::1$|fe80:)/i', $ip);
}

// IP del visitante. Detrás del CDN de Hostinger, REMOTE_ADDR YA es el visitante; X-Forwarded-For y True-Client-IP los puede escribir
// cualquiera, así que solo se miran si REMOTE_ADDR es de una red interna (proxy propio o pruebas locales), de derecha a izquierda.
function ip_cliente()
{
    $remota = $_SERVER['REMOTE_ADDR'] ?? '';
    if (ip_publica($remota)) {
        return $remota;
    }
    $real = trim((string) ($_SERVER['HTTP_X_REAL_IP'] ?? ''));
    if (ip_publica($real)) {
        return $real;
    }
    foreach (array_reverse(explode(',', (string) ($_SERVER['HTTP_X_FORWARDED_FOR'] ?? ''))) as $parte) {
        if (ip_publica(trim($parte))) {
            return trim($parte);
        }
    }
    return filter_var($remota, FILTER_VALIDATE_IP) ? $remota : '';
}

function cortar($texto, $max)
{
    return function_exists('mb_substr') ? mb_substr($texto, 0, $max) : substr($texto, 0, $max);
}

function host_de($url)
{
    $h = parse_url((string) $url, PHP_URL_HOST);
    return $h ? strtolower($h) : '';
}

function limpiar_texto($texto, $max)
{
    return trim(cortar(preg_replace('/[\x00-\x1f\x7f<>"\'`]/u', '', (string) $texto), $max));
}

// Resultado del último envío a Meta, para el diagnóstico (?estado). Solo guarda hora, evento y códigos: nunca el token ni datos del visitante
function registrar_ultimo($datos)
{
    @file_put_contents(sys_get_temp_dir() . '/hp_capi-ultimo.json', json_encode($datos), LOCK_EX);
}

function leer_ultimo()
{
    $d = json_decode((string) @file_get_contents(sys_get_temp_dir() . '/hp_capi-ultimo.json'), true);
    return is_array($d) ? $d : null;
}

// Topes por minuto, por IP y en total, en UN archivo de tamaño acotado (nunca crece: máximo HP_MAX_IPS direcciones por minuto)
function dentro_del_limite($ip)
{
    $fh = @fopen(sys_get_temp_dir() . '/hp_capi-limite.json', 'c+');
    if (!$fh) {
        return true;   // sin disco: no se bloquea a nadie
    }
    flock($fh, LOCK_EX);
    $minuto = (int) floor(time() / 60);
    $d = json_decode((string) stream_get_contents($fh), true);
    if (!is_array($d) || ($d['m'] ?? null) !== $minuto || !isset($d['t'], $d['ip']) || !is_array($d['ip'])) {
        $d = ['m' => $minuto, 't' => 0, 'ip' => []];
    }
    $d['t']++;
    $k = substr(md5($ip), 0, 12);
    if (isset($d['ip'][$k]) || count($d['ip']) < HP_MAX_IPS) {
        $d['ip'][$k] = ($d['ip'][$k] ?? 0) + 1;
    }   // con el cupo de direcciones lleno, las nuevas cuentan solo contra el total
    $bien = $d['t'] <= HP_MAX_TOTAL && ($d['ip'][$k] ?? 0) <= HP_MAX_IP;
    ftruncate($fh, 0);
    rewind($fh);
    fwrite($fh, json_encode($d));
    flock($fh, LOCK_UN);
    fclose($fh);
    return $bien;
}

// Datos del evento: solo campos conocidos con valores de las listas y rangos de la página (lo demás se descarta).
// Los booleanos salen como texto, igual que los manda el píxel del navegador.
function datos_del_evento($cd)
{
    $out = [];
    if (!is_array($cd)) {
        return $out;
    }
    foreach ($cd as $k => $v) {
        if (!is_string($k)) {
            continue;
        }
        if (isset(HP_ENUMS[$k])) {
            if (is_string($v) && in_array($v, HP_ENUMS[$k], true)) {
                $out[$k] = $v;
            }
        } elseif (in_array($k, HP_BOOLS, true)) {
            if (is_bool($v)) {
                $out[$k] = $v ? 'true' : 'false';
            }
        } elseif (isset(HP_RANGOS[$k])) {
            if ((is_int($v) || is_float($v)) && $v >= HP_RANGOS[$k][0] && $v <= HP_RANGOS[$k][1]) {
                $out[$k] = (int) round($v);
            }
        } elseif ($k === 'seccion') {
            if (is_string($v) && preg_match('/^[a-z0-9-]{1,30}$/D', $v)) {
                $out[$k] = $v;
            }
        } elseif (isset(HP_TEXTOS[$k])) {
            if (is_string($v) && ($t = limpiar_texto($v, HP_TEXTOS[$k])) !== '') {
                $out[$k] = $t;
            }
        }
    }
    return $out;
}

function manejar()
{
    $cfg = cargar_config();
    $configurado = !empty($cfg['pixel_id']) && !empty($cfg['access_token']);
    $permitidos = !empty($cfg['allowed_hosts']) ? $cfg['allowed_hosts'] : HP_HOSTS;

    // GET: solo diagnóstico. Sirve para ver que PHP corre en este hosting, que el archivo secreto se leyó y cómo salió el último envío
    // (sin revelar secretos).
    if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
        if (isset($_GET['estado'])) {
            responder(200, ['ok' => true, 'configurado' => $configurado, 'modo_prueba' => !empty($cfg['test_event_code']),
                'version_api' => $cfg['graph_version'] ?? HP_VERSION, 'ip_detectada' => ip_cliente(), 'curl' => function_exists('curl_init'),
                'secreto_en' => $cfg['__ubicacion'] ?: null, 'buscado' => $cfg['__buscado'], 'parecidos' => $configurado ? [] : nombres_parecidos(),
                'ultimo_envio' => leer_ultimo()]);
        }
        header('Allow: POST');
        responder(405, ['ok' => false, 'error' => 'metodo']);
    }

    if (!$configurado) {
        responder(204);
    }

    // Solo el propio sitio puede mandar eventos (esto frena el uso desde otras páginas; no es autenticación, ver el encabezado)
    $sitio = $_SERVER['HTTP_SEC_FETCH_SITE'] ?? '';
    if ($sitio !== '' && $sitio !== 'same-origin') {
        responder(403, ['ok' => false, 'error' => 'origen']);
    }
    $origen = host_de($_SERVER['HTTP_ORIGIN'] ?? '') ?: host_de($_SERVER['HTTP_REFERER'] ?? '');
    if (!in_array($origen, $permitidos, true)) {
        responder(403, ['ok' => false, 'error' => 'origen']);
    }

    $ip = ip_cliente();
    if (!dentro_del_limite($ip !== '' ? $ip : 'sin-ip')) {
        responder(429, ['ok' => false, 'error' => 'limite']);
    }

    $crudo = file_get_contents('php://input', false, null, 0, 8193);
    if ($crudo === false || strlen($crudo) > 8192) {
        responder(413, ['ok' => false, 'error' => 'tamano']);
    }
    $in = json_decode($crudo, true);
    if (!is_array($in)) {
        responder(400, ['ok' => false, 'error' => 'json']);
    }

    $nombre = $in['event_name'] ?? '';
    $id = $in['event_id'] ?? '';
    if (!is_string($nombre) || !in_array($nombre, HP_EVENTOS, true) || !is_string($id) || !preg_match('/^[A-Za-z0-9_-]{8,64}$/D', $id)) {
        responder(400, ['ok' => false, 'error' => 'evento']);
    }

    // URL de la página: del propio sitio y sin fragmento (#…); si algo no cuadra, la portada
    $url = (string) ($in['event_source_url'] ?? '');
    $url = strlen($url) <= 500 && in_array(host_de($url), $permitidos, true) ? explode('#', $url)[0] : 'https://' . $permitidos[0] . '/';

    $user = [];
    if ($ip !== '') {
        $user['client_ip_address'] = $ip;
    }
    $ua = substr((string) ($_SERVER['HTTP_USER_AGENT'] ?? ''), 0, 512);
    if ($ua !== '') {
        $user['client_user_agent'] = $ua;
    }
    $fbp = $in['fbp'] ?? '';
    if (is_string($fbp) && preg_match('/^fb\.[0-2]\.\d{10,13}\.\d{4,20}$/D', $fbp)) {
        $user['fbp'] = $fbp;
    }
    $fbc = $in['fbc'] ?? '';
    if (is_string($fbc) && preg_match('/^fb\.[0-2]\.\d{10,13}\.[A-Za-z0-9_-]{8,200}$/D', $fbc)) {
        $user['fbc'] = $fbc;
    }
    if (empty($user['client_user_agent'])) {
        responder(400, ['ok' => false, 'error' => 'usuario']);   // Meta exige agente de usuario en eventos web
    }

    $datos = datos_del_evento($in['custom_data'] ?? null);

    $evento = ['event_name' => $nombre, 'event_time' => time(), 'event_id' => $id, 'event_source_url' => $url, 'action_source' => 'website', 'user_data' => $user];
    if ($datos) {
        $evento['custom_data'] = $datos;
    }
    $cuerpo = ['data' => [$evento], 'access_token' => $cfg['access_token']];
    if (!empty($cfg['test_event_code'])) {
        $cuerpo['test_event_code'] = $cfg['test_event_code'];
    }

    $destino = base_graph($cfg) . '/' . ($cfg['graph_version'] ?? HP_VERSION) . '/' . rawurlencode((string) $cfg['pixel_id']) . '/events';
    // El agente de usuario viene del visitante y puede traer bytes inválidos (o quedar cortado a media letra): se sustituyen, no se pierde el evento
    $json = json_encode($cuerpo, JSON_UNESCAPED_UNICODE | JSON_INVALID_UTF8_SUBSTITUTE);
    if ($json === false) {
        error_log('[meta-capi] no se pudo codificar el evento ' . $nombre);
        responder(204);
    }

    // Todo lo válido ya está comprobado: se contesta al navegador y se habla con Meta por detrás (si el servidor lo permite)
    $pronto = responder_ya();

    $estado = 0;
    $respuesta = '';
    if (function_exists('curl_init')) {
        $ch = curl_init($destino);
        curl_setopt_array($ch, [CURLOPT_POST => true, CURLOPT_HTTPHEADER => ['Content-Type: application/json'], CURLOPT_POSTFIELDS => $json,
            CURLOPT_RETURNTRANSFER => true, CURLOPT_CONNECTTIMEOUT => 2, CURLOPT_TIMEOUT => 4]);
        $respuesta = (string) curl_exec($ch);
        $estado = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
    } else {
        $ctx = stream_context_create(['http' => ['method' => 'POST', 'header' => "Content-Type: application/json\r\n", 'content' => $json, 'timeout' => 4, 'ignore_errors' => true]]);
        $respuesta = (string) @file_get_contents($destino, false, $ctx);
        foreach ((array) ($http_response_header ?? []) as $h) {
            if (preg_match('#^HTTP/\S+\s+(\d{3})#', $h, $m)) {
                $estado = (int) $m[1];
            }
        }
    }

    $resp = json_decode($respuesta, true);
    $aceptado = $estado === 200 && is_array($resp) && !empty($resp['events_received']);
    registrar_ultimo(['t' => time(), 'evento' => $nombre, 'http' => $estado, 'aceptado' => $aceptado,
        'meta_codigo' => is_array($resp) && isset($resp['error']['code']) ? (int) $resp['error']['code'] : null,
        'meta_subcodigo' => is_array($resp) && isset($resp['error']['error_subcode']) ? (int) $resp['error']['error_subcode'] : null]);
    if (!$aceptado) {
        error_log('[meta-capi] ' . $nombre . ' → HTTP ' . $estado . ' ' . substr($respuesta, 0, 300));   // nunca incluye el token
    }
    if ($pronto) {
        return;   // el navegador ya recibió su 204
    }
    if ($aceptado) {
        responder(204);
    }
    responder(502, ['ok' => false, 'error' => 'meta']);
}

if (!defined('HP_PRUEBAS')) {   // las pruebas cargan el archivo para llamar a las funciones sueltas
    try {
        manejar();
    } catch (Throwable $e) {
        error_log('[meta-capi] excepción ' . get_class($e) . ': ' . $e->getMessage());   // nunca incluye el token
        registrar_ultimo(['t' => time(), 'aceptado' => false, 'excepcion' => get_class($e)]);
        responder(204);   // el visitante nunca debe ver un error por culpa del relevo
    }
}
