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
 * servidor, que este script busca en este orden:
 *   1. <carpeta del dominio>/capi-secret.php   → FUERA de public_html: la ubicación recomendada
 *   2. public_html/.capi-secret.php            → archivo oculto: el .htaccess lo bloquea desde la web
 * Contenido (ver docs/capi-meta.md):
 *   <?php return ['pixel_id' => '…', 'access_token' => '…', 'test_event_code' => ''];
 * Si el servidor lo permite también se leen las variables de entorno META_PIXEL_ID, META_ACCESS_TOKEN y META_TEST_EVENT_CODE.
 *
 * Sin configuración responde 204 y no hace nada (así la página no muestra errores). Para comprobar que PHP corre y que el
 * archivo secreto se encontró: abrir /api/meta-eventos.php?estado en el navegador.
 */

error_reporting(0);
ini_set('display_errors', '0');

const HP_EVENTOS = ['ContactoWhatsApp', 'ClicIntencionPrecio', 'VioPrecio'];
const HP_HOSTS = ['haciendaprimavera.co', 'www.haciendaprimavera.co'];
const HP_CAMPOS = ['proyecto', 'boton', 'content_name', 'vio_precio', 'profundidad', 'segundos_en_pagina', 'calidad', 'clic_n', 'repetido',
    'tipologia', 'proposito', 'forma_pago', 'calificador_completo', 'seccion', 'texto', 'utm_source', 'utm_campaign', 'utm_content'];
const HP_VERSION = 'v25.0';
const HP_MAX_POR_MINUTO = 60;

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

function cargar_config()
{
    $cfg = [];
    foreach ([__DIR__ . '/../../capi-secret.php', __DIR__ . '/../.capi-secret.php'] as $ruta) {
        if (is_file($ruta)) {
            $x = include $ruta;
            if (is_array($x)) {
                $cfg = $x;
                break;
            }
        }
    }
    foreach (['pixel_id' => 'META_PIXEL_ID', 'access_token' => 'META_ACCESS_TOKEN', 'test_event_code' => 'META_TEST_EVENT_CODE',
        'graph_version' => 'META_GRAPH_VERSION', 'graph_base' => 'META_GRAPH_BASE', 'allowed_hosts' => 'META_ALLOWED_HOSTS'] as $k => $e) {
        $v = getenv($e);
        if (!isset($cfg[$k]) && $v !== false && $v !== '') {
            $cfg[$k] = $k === 'allowed_hosts' ? array_map('trim', explode(',', $v)) : $v;
        }
    }
    return $cfg;
}

function ip_cliente()
{
    foreach (['HTTP_CF_CONNECTING_IP', 'HTTP_TRUE_CLIENT_IP', 'HTTP_X_FORWARDED_FOR', 'HTTP_X_REAL_IP', 'REMOTE_ADDR'] as $k) {
        if (empty($_SERVER[$k])) {
            continue;
        }
        foreach (explode(',', $_SERVER[$k]) as $parte) {
            $parte = trim($parte);
            if (filter_var($parte, FILTER_VALIDATE_IP)) {
                return $parte;
            }
        }
    }
    return '';
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

// Tope de solicitudes por IP y minuto (archivo temporal): frena a quien intente llenar de basura el píxel
function dentro_del_limite($ip)
{
    $ruta = sys_get_temp_dir() . '/hp_capi_' . md5($ip) . '.json';
    $fh = @fopen($ruta, 'c+');
    if (!$fh) {
        return true;
    }
    flock($fh, LOCK_EX);
    $ahora = time();
    $d = json_decode((string) stream_get_contents($fh), true);
    if (!is_array($d) || !isset($d['t'], $d['n']) || $ahora - $d['t'] >= 60) {
        $d = ['t' => $ahora, 'n' => 0];
    }
    $d['n']++;
    ftruncate($fh, 0);
    rewind($fh);
    fwrite($fh, json_encode($d));
    flock($fh, LOCK_UN);
    fclose($fh);
    if (mt_rand(1, 100) === 1) {   // limpieza ocasional de contadores viejos
        foreach ((array) glob(sys_get_temp_dir() . '/hp_capi_*.json') as $f) {
            if (@filemtime($f) < $ahora - 3600) {
                @unlink($f);
            }
        }
    }
    return $d['n'] <= HP_MAX_POR_MINUTO;
}

$cfg = cargar_config();
$configurado = !empty($cfg['pixel_id']) && !empty($cfg['access_token']);
$permitidos = !empty($cfg['allowed_hosts']) ? $cfg['allowed_hosts'] : HP_HOSTS;

// GET: solo diagnóstico. Sirve para ver que PHP corre en este hosting y que el archivo secreto se leyó (sin revelar secretos).
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    if (isset($_GET['estado'])) {
        responder(200, ['ok' => true, 'configurado' => $configurado, 'modo_prueba' => !empty($cfg['test_event_code']),
            'version_api' => $cfg['graph_version'] ?? HP_VERSION, 'ip_detectada' => ip_cliente(), 'php' => PHP_VERSION, 'curl' => function_exists('curl_init')]);
    }
    header('Allow: POST');
    responder(405, ['ok' => false, 'error' => 'metodo']);
}

if (!$configurado) {
    responder(204);
}

// Solo el propio sitio puede mandar eventos
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
if (!is_string($nombre) || !in_array($nombre, HP_EVENTOS, true) || !is_string($id) || !preg_match('/^[A-Za-z0-9_-]{8,64}$/', $id)) {
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
if (is_string($fbp) && preg_match('/^fb\.[0-2]\.\d{10,13}\.\d{4,20}$/', $fbp)) {
    $user['fbp'] = $fbp;
}
$fbc = $in['fbc'] ?? '';
if (is_string($fbc) && preg_match('/^fb\.[0-2]\.\d{10,13}\.[A-Za-z0-9_-]{8,200}$/', $fbc)) {
    $user['fbc'] = $fbc;
}
if (empty($user['client_user_agent'])) {
    responder(400, ['ok' => false, 'error' => 'usuario']);   // Meta exige agente de usuario en eventos web
}

// Datos del evento: solo los campos conocidos y valores simples (los booleanos como texto, igual que los manda el píxel)
$datos = [];
if (isset($in['custom_data']) && is_array($in['custom_data'])) {
    foreach ($in['custom_data'] as $k => $v) {
        if (!in_array($k, HP_CAMPOS, true)) {
            continue;
        }
        if (is_bool($v)) {
            $datos[$k] = $v ? 'true' : 'false';
        } elseif (is_int($v) || is_float($v)) {
            $datos[$k] = $v;
        } elseif (is_string($v)) {
            $datos[$k] = cortar($v, 100);
        }
    }
}

$evento = ['event_name' => $nombre, 'event_time' => time(), 'event_id' => $id, 'event_source_url' => $url, 'action_source' => 'website', 'user_data' => $user];
if ($datos) {
    $evento['custom_data'] = $datos;
}
$cuerpo = ['data' => [$evento], 'access_token' => $cfg['access_token']];
if (!empty($cfg['test_event_code'])) {
    $cuerpo['test_event_code'] = $cfg['test_event_code'];
}

$base = rtrim($cfg['graph_base'] ?? 'https://graph.facebook.com', '/');
$destino = $base . '/' . ($cfg['graph_version'] ?? HP_VERSION) . '/' . rawurlencode((string) $cfg['pixel_id']) . '/events';
$json = json_encode($cuerpo, JSON_UNESCAPED_UNICODE);
$estado = 0;
$respuesta = '';
if (function_exists('curl_init')) {
    $ch = curl_init($destino);
    curl_setopt_array($ch, [CURLOPT_POST => true, CURLOPT_HTTPHEADER => ['Content-Type: application/json'], CURLOPT_POSTFIELDS => $json,
        CURLOPT_RETURNTRANSFER => true, CURLOPT_CONNECTTIMEOUT => 4, CURLOPT_TIMEOUT => 8]);
    $respuesta = (string) curl_exec($ch);
    $estado = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
} else {
    $ctx = stream_context_create(['http' => ['method' => 'POST', 'header' => "Content-Type: application/json\r\n", 'content' => $json, 'timeout' => 8, 'ignore_errors' => true]]);
    $respuesta = (string) @file_get_contents($destino, false, $ctx);
    foreach ((array) ($http_response_header ?? []) as $h) {
        if (preg_match('#^HTTP/\S+\s+(\d{3})#', $h, $m)) {
            $estado = (int) $m[1];
        }
    }
}

$resp = json_decode($respuesta, true);
if ($estado === 200 && is_array($resp) && !empty($resp['events_received'])) {
    responder(204);
}
error_log('[meta-capi] ' . $nombre . ' → HTTP ' . $estado . ' ' . substr($respuesta, 0, 300));   // nunca incluye el token
responder(502, ['ok' => false, 'error' => 'meta']);
