#!/usr/bin/env python3
"""Verifica el contrato del sistema de botón único de WhatsApp en index.html.

Uso: python3 tools/check_trazabilidad.py [ruta/a/index.html] [--require-pixel]
     (por defecto, el index.html de la raíz; --require-pixel convierte en error que CONFIG.pixelId esté vacío: úsalo en producción)

Contrato (ver docs/trazabilidad-whatsapp.md):
  - Exactamente UN enlace con data-wa: el botón de WhatsApp de #contacto (href completo, target _blank, data-cta="final").
  - Ningún otro punto de salida a WhatsApp en la página: ni href (wa.me, whatsapp.com, whatsapp://, intent://), ni onclick,
    ni data-*, ni window.open/location en scripts (el JSON-LD no cuenta; mayúsculas y minúsculas da igual).
  - Todo botón que lleva al contacto es <a href="#contacto"> con un data-cta único y sin target (nunca abre pestañas).
  - Existen #contacto y #precio (una vez cada uno) y el script de trazabilidad apunta a ellos.
Sale con código 1 si se rompe el contrato. El aviso del ID del píxel no es un error.
"""
import os, re, sys
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARGS = [a for a in sys.argv[1:] if not a.startswith('--')]
REQUIRE_PIXEL = '--require-pixel' in sys.argv
PATH = ARGS[0] if ARGS else os.path.join(ROOT, 'index.html')
# Cualquier forma de salir a WhatsApp, sin importar mayúsculas: enlaces web, esquemas de app e intents de Android
WA_RX = re.compile(r'wa\.me|whatsapp\.com|whatsapp://|intent://|wa\.link', re.I)
VOID = {'meta', 'link', 'img', 'br', 'hr', 'input', 'source', 'use', 'path', 'circle', 'line', 'rect', 'polyline', 'polygon', 'stop'}


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []          # dicts: attrs, text, where
        self.tags = []           # (tag, attrs, where) de TODAS las etiquetas, para revisar cualquier atributo
        self.ids = {}
        self.scripts = []        # (attrs, text) de scripts que no son JSON-LD
        self._open = []          # pila de (tag, attrs)
        self._cur = None         # enlace abierto
        self._script = None

    def where(self):
        for tag, at in reversed(self._open):
            if tag == 'section' and at.get('id'):
                return '#' + at['id']
            if tag == 'footer':
                return 'pie de página'
            if tag == 'div' and at.get('id') == 'menu':
                return 'menú móvil'
            if tag == 'header' and at.get('id') == 'nav':
                return 'cabecera'
        return 'página'

    def handle_starttag(self, tag, attrs):
        at = dict((k, v or '') for k, v in attrs)
        self.tags.append((tag, at, self.where()))
        if at.get('id'):
            self.ids[at['id']] = self.ids.get(at['id'], 0) + 1
        if tag == 'script':
            self._script = (at, [])
        if tag == 'a':
            self._cur = {'attrs': at, 'text': [], 'where': self.where()}
            self.links.append(self._cur)
        if tag not in VOID:
            self._open.append((tag, at))

    def handle_endtag(self, tag):
        if tag == 'script' and self._script is not None:
            at, parts = self._script
            if 'ld+json' not in (at.get('type') or ''):
                self.scripts.append((at, ''.join(parts)))
            self._script = None
        if tag == 'a':
            self._cur = None
        for i in range(len(self._open) - 1, -1, -1):
            if self._open[i][0] == tag:
                del self._open[i:]
                break

    def handle_data(self, data):
        if self._script is not None:
            self._script[1].append(data)
        elif self._cur is not None:
            self._cur['text'].append(data)


def main():
    html = open(PATH, encoding='utf-8').read()
    p = Page()
    p.feed(html)
    errors, warns = [], []

    def err(m): errors.append(m)

    wa = [l for l in p.links if 'data-wa' in l['attrs']]
    if len(wa) != 1:
        err(f'debe haber exactamente 1 enlace con data-wa y hay {len(wa)}')
    else:
        a = wa[0]['attrs']
        href = a.get('href') or ''
        if not re.match(r'https://wa\.me/\d{10,15}\?text=\S+', href):
            err(f'el href del botón único debe ser completo (https://wa.me/<número>?text=...): {href!r}')
        if a.get('target') != '_blank' or 'noopener' not in (a.get('rel') or ''):
            err('el botón único debe llevar target="_blank" y rel="noopener"')
        if a.get('data-cta') != 'final':
            err('el botón único debe llevar data-cta="final"')
        if wa[0]['where'] != '#contacto':
            err(f'el botón único debe estar dentro de #contacto (está en {wa[0]["where"]})')

    for tag, at, where in p.tags:
        if 'data-wa' in at and tag == 'a':
            continue
        for k, v in at.items():
            if v and WA_RX.search(v):
                err(f'salida a WhatsApp que no es el botón único (<{tag} {k}=…> en {where}): {v[:70]}… → conviértelo en <a href="#contacto" data-cta="...">')
    for at, t in p.scripts:
        for m in WA_RX.finditer(t):
            err(f'un script en línea menciona una salida a WhatsApp ({m.group(0)!r}): {t[max(0, m.start() - 30):m.end() + 40].strip()!r}')

    anchors = [l for l in p.links if l['attrs'].get('href') == '#contacto']
    seen = {}
    for l in anchors:
        if l['attrs'].get('target'):
            err(f'ancla a #contacto con target={l["attrs"]["target"]!r} ({l["where"]}): una ancla nunca debe abrir pestañas')
        c = (l['attrs'].get('data-cta') or '').strip()
        if not c:
            err(f'ancla a #contacto sin data-cta ({l["where"]}): {" ".join("".join(l["text"]).split())[:40]!r}')
        elif c in seen:
            err(f'data-cta repetido: {c!r}')
        seen[c] = True

    for i in ('contacto', 'precio'):
        if p.ids.get(i, 0) != 1:
            err(f'debe existir un único id="{i}" y hay {p.ids.get(i, 0)}')
    for i, n in p.ids.items():
        if n > 1:
            err(f'id duplicado: {i!r} ({n} veces)')

    js = [t for at, t in p.scripts if 'ContactoWhatsApp' in t]
    if len(js) != 1:
        err('no se encontró (o hay más de uno) el script de trazabilidad con ContactoWhatsApp')
    else:
        t = js[0]
        for ev in ('ContactoWhatsApp', 'ClicIntencionPrecio', 'VioPrecio'):
            if ev not in t:
                err(f'el script de trazabilidad no emite {ev}')
        for k, want in (('destino', '#contacto'), ('precio', '#precio')):
            m = re.search(k + r":\s*'([^']*)'", t)
            if not m or m.group(1) != want:
                err(f'CONFIG.{k} debe ser {want!r} (es {m.group(1) if m else None!r})')
        m = re.search(r"pixelId:\s*'([^']*)'", t)
        if m is None:
            err('CONFIG.pixelId no encontrado')
        elif not m.group(1):
            msg = 'CONFIG.pixelId está vacío: el código NO instala el píxel de Meta. Está bien si lo instala GTM; si no, nada llega a Meta (hoy la página no tiene GTM ni GA: el dataLayer no lo lee nadie).'
            if REQUIRE_PIXEL:
                err(msg)
            else:
                warns.append(msg)
        elif not re.fullmatch(r'\d{10,20}', m.group(1)):
            err(f'CONFIG.pixelId debe ser solo dígitos (es {m.group(1)!r})')

    print(f'Archivo: {PATH}\n')
    print(f'Botón único de WhatsApp: {len(wa)}  ·  Anclas a #contacto: {len(anchors)}')
    print(f'{"data-cta":<16} {"dónde":<16} texto')
    print('-' * 64)
    for l in anchors:
        txt = ' '.join(''.join(l['text']).split())
        print(f'{(l["attrs"].get("data-cta") or "—"):<16} {l["where"]:<16} {txt}')
    if wa:
        print(f'{"final (WhatsApp)":<16} {wa[0]["where"]:<16} {" ".join("".join(wa[0]["text"]).split())}')
    other = [l for l in p.links if (l['attrs'].get('href') or '').startswith(('tel:', 'mailto:'))]
    print(f'\ntel:/mailto: (no son WhatsApp, no se miden): {len(other)}')
    for w in warns:
        print('AVISO:', w)
    if errors:
        print('\nCONTRATO ROTO:')
        for e in errors:
            print('  ✗', e)
        sys.exit(1)
    print('\nCONTRATO OK' + (f' ({len(warns)} aviso)' if warns else ''))


if __name__ == '__main__':
    main()
