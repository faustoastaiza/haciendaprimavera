#!/usr/bin/env python3
"""Arma la carpeta _publicar/ (lista para subir a public_html) y el ZIP.
Uso (desde la carpeta del proyecto): python3 tools/build_publicar.py [--no-minify]
- Copia solo lo que el sitio necesita (sin .git, .claude, .command, .DS_Store...).
- Minifica index.html de forma conservadora SOLO en la copia de _publicar (el fuente no se toca).
- Verifica que cada referencia local exista; excluye del paquete lo que nadie referencia.
"""
import os, re, sys, shutil, zipfile, json
from urllib.parse import unquote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.environ.get('DIST_OUT') or os.path.join(ROOT, '_publicar')
ZIP = os.environ.get('DIST_ZIP') or os.path.join(ROOT, 'hacienda-primavera-para-subir.zip')
MINIFY = '--no-minify' not in sys.argv

ROOT_FILES = ['index.html', '.htaccess', 'robots.txt', 'sitemap.xml', 'llms.txt', '404.html',
              'favicon.ico', 'favicon.svg', 'favicon-48x48.png', 'icon-192.png', 'icon-512.png',
              'apple-touch-icon.png', 'site.webmanifest']
DIRS = ['img', 'assets']
JUNK = {'.DS_Store', 'Thumbs.db'}


def minify_html(html):
    out = []
    pos = 0
    pat = re.compile(r'(<style\b[^>]*>)(.*?)(</style>)|(<script\b[^>]*>)(.*?)(</script>)', re.S | re.I)
    for m in pat.finditer(html):
        out.append(('html', html[pos:m.start()]))
        if m.group(1):
            out += [('raw', m.group(1)), ('css', m.group(2)), ('raw', m.group(3))]
        else:
            kind = 'json' if 'ld+json' in m.group(4) else 'js'
            out += [('raw', m.group(4)), (kind, m.group(5)), ('raw', m.group(6))]
        pos = m.end()
    out.append(('html', html[pos:]))
    res = []
    for kind, txt in out:
        if kind in ('raw', 'json'):
            res.append(txt)
        elif kind == 'css':
            t = re.sub(r'/\*.*?\*/', '', txt, flags=re.S)
            t = '\n'.join(l.strip() for l in t.splitlines() if l.strip())
            res.append('\n' + t + '\n')
        elif kind == 'js':
            lines, in_block = [], False
            for l in txt.splitlines():
                st = l.strip()
                if in_block:
                    if '*/' in st: in_block = False
                    continue
                if st.startswith('/*') and '*/' not in st:
                    in_block = True; continue
                if not st or st.startswith('//') or (st.startswith('/*') and st.endswith('*/')):
                    continue
                lines.append(st)
            res.append('\n' + '\n'.join(lines) + '\n')
        else:  # html
            t = re.sub(r'<!--(?!\[if).*?-->', '', txt, flags=re.S)
            t = '\n'.join(l.strip() for l in t.splitlines() if l.strip())
            res.append(('\n' if t else '') + t + ('\n' if t else ''))
    return ''.join(res).lstrip()


def main():
    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)
    copied = []
    for f in ROOT_FILES:
        src = os.path.join(ROOT, f)
        if not os.path.exists(src):
            print('  (no existe, se omite):', f); continue
        shutil.copy2(src, os.path.join(OUT, f)); copied.append(f)
    for d in DIRS:
        for base, dirs, files in os.walk(os.path.join(ROOT, d)):
            dirs[:] = [x for x in dirs if x not in JUNK]
            for fn in files:
                if fn in JUNK: continue
                rel = os.path.relpath(os.path.join(base, fn), ROOT)
                dst = os.path.join(OUT, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(os.path.join(ROOT, rel), dst); copied.append(rel)

    src_html = open(os.path.join(ROOT, 'index.html'), encoding='utf-8').read()
    final = minify_html(src_html) if MINIFY else src_html
    open(os.path.join(OUT, 'index.html'), 'w', encoding='utf-8').write(final)
    print(f'index.html: {len(src_html.encode()):,} B -> {len(final.encode()):,} B ({"minificado" if MINIFY else "sin minificar"})')

    refs = set()
    texts = [final]
    for extra in ('sitemap.xml', 'llms.txt', 'site.webmanifest', '404.html'):
        p = os.path.join(OUT, extra)
        if os.path.exists(p): texts.append(open(p, encoding='utf-8', errors='ignore').read())
    rx = re.compile(r'(?:(?<=["\'(=\s,])|^)/?((?:img|assets)/[^"\')\s,>]+?\.(?:webp|jpg|jpeg|png|svg|xml|js|json))', re.I)
    for t in texts:
        for m in rx.finditer(t): refs.add(unquote(m.group(1)))
    joined = ''.join(texts)
    for m in re.finditer(r'https://haciendaprimavera\.co/((?:img|assets)/[^"\'<\s]+)', joined):
        refs.add(unquote(m.group(1)))
    for m in re.finditer(r'(?:href|src)="/((?:favicon|icon|apple-touch|site\.webmanifest)[^"]*)"', final):
        refs.add(m.group(1))
    for m in re.finditer(r'srcset="([^"]+)"', final):
        for part in m.group(1).split(','):
            u = part.strip().split(' ')[0]
            if u.startswith(('img/', 'assets/')): refs.add(unquote(u))
    missing = sorted(r for r in refs if not os.path.exists(os.path.join(OUT, r)) and not r.startswith('assets/360/'))
    print('referencias locales:', len(refs), '| faltantes:', missing or 'ninguna')

    unref = sorted(c for c in copied if c.startswith(('img/', 'assets/'))
                   and not c.startswith('assets/360/') and c not in refs)
    print('sin referencia en el sitio:', len(unref))
    for u in unref: print('   ', u)
    for u in unref:
        os.remove(os.path.join(OUT, u)); copied.remove(u)
    print('excluidos del paquete:', len(unref))

    if os.path.exists(ZIP): os.remove(ZIP)
    with zipfile.ZipFile(ZIP, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for base, dirs, files in os.walk(OUT):
            dirs.sort()
            for fn in sorted(files):
                full = os.path.join(base, fn)
                z.write(full, os.path.relpath(full, OUT))
    total = sum(os.path.getsize(os.path.join(b, f)) for b, _, fs in os.walk(OUT) for f in fs)
    print(f'\n_publicar: {len(copied)} archivos, {total/1e6:.1f} MB | ZIP: {os.path.getsize(ZIP)/1e6:.1f} MB -> {ZIP}')
    if missing: sys.exit(2)


if __name__ == '__main__':
    main()
