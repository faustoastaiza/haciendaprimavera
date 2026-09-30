#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_jsonld.py - Generador determinista de JSON-LD para Hacienda Primavera.

Lee el HTML FINAL de la landing (index.html), DERIVA de el todos los hechos
(FAQ, tipologias, sala de ventas, hero, meta) con html.parser e inyecta un
unico bloque <script type="application/ld+json"> entre los marcadores

    <!-- JSON-LD:start -->  ...  <!-- JSON-LD:end -->

de modo que el marcado estructurado nunca contradiga el texto visible.
Solo libreria estandar de Python 3.

USO
    python3 build_jsonld.py <ruta/index.html>            escribe (idempotente)
    python3 build_jsonld.py --check <ruta/index.html>    verifica, NO escribe (exit 0 = OK)
    python3 build_jsonld.py --print <ruta/index.html>    imprime el bloque, NO escribe
    python3 build_jsonld.py --verify-video               re-verifica en YouTube (red) las
                                                         constantes de VERIFIED_VIDEOS
    Opciones: --strict (los WARN pasan a error)

Si los marcadores no existen, inserta el bloque justo antes de la primera linea
del <head> que contenga  <link rel="preconnect"  (fallback: antes de </head>).

CODIGOS DE SALIDA: 0 OK | 1 fallo de --check / --strict / verificacion | 2 error de uso o E/S
"""
import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import unicodedata
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlsplit

# --------------------------------------------------------------------------- #
# Constantes
# --------------------------------------------------------------------------- #
SITE = "https://haciendaprimavera.co/"          # se sobreescribe con <link rel=canonical> si existe
MARK_START = "<!-- JSON-LD:start -->"
MARK_END = "<!-- JSON-LD:end -->"
PRECONNECT = '<link rel="preconnect"'
LANG = "es-CO"

# Metadatos de video VERIFICADOS contra YouTube (no inventados). Un video del HTML cuyo id
# no este aqui NO genera VideoObject (regla: sin uploadDate verificado, se omite el nodo).
#   Fuente: https://www.youtube.com/watch?v=wH-PoqjtrCg  (microdata itemprop="uploadDate" /
#   "duration" y ytInitialPlayerResponse: uploadDate, publishDate, lengthSeconds=81,
#   approxDurationMs=80633). Verificado el 2026-09-29. Re-verificable con --verify-video.
VERIFIED_VIDEOS = {
    "wH-PoqjtrCg": {
        "uploadDate": "2022-12-26T15:06:27-08:00",
        "duration": "PT1M21S",
    },
}

# Amenidades: (nombre, [textos que deben existir LITERALMENTE en el texto visible]).
# Solo se emiten las que el HTML sustenta. Piscina/jacuzzi/kiosko NO van aqui (son adicionales).
AMENITIES = [
    ("Portería", ["portería"]),
    ("Cámaras de vigilancia digitalizada", ["cámaras de vigilancia digitalizada"]),
    ("Cerramiento perimetral", ["cerramiento perimetral"]),
    ("Vías internas con iluminación exterior solar", ["vías internas", "iluminación exterior solar"]),
    ("Áreas de reserva natural", ["áreas de reserva natural"]),
]

# Prohibiciones (se hacen cumplir en --check y antes de escribir).
FORBIDDEN_KEYS = {
    "offers", "offer", "price", "pricecurrency", "pricerange", "aggregaterating", "review",
    "reviews", "sameas", "logo", "geo", "datemodified", "datepublished", "potentialaction",
}
FORBIDDEN_TYPES = {
    "offer", "aggregateoffer", "product", "review", "aggregaterating", "vacationrental",
    "lodgingbusiness", "searchaction", "geocoordinates", "hotel", "apartment",
}
FORBIDDEN_AMENITY = re.compile(r"piscina|jacuzzi|kiosko", re.I)
FORBIDDEN_TEXT = re.compile(r"\bTODO\b|CONFIRMAR", re.I)
PRICE_TEXT = re.compile(r"\$\s?\d|\bCOP\b")

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
        "source", "track", "wbr"}
BLOCK = {"address", "article", "aside", "blockquote", "br", "button", "dd", "details", "div",
         "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3",
         "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p", "section", "summary",
         "table", "td", "th", "tr", "ul"}
SKIP_TEXT = {"script", "style", "template", "noscript", "svg", "head"}
NUM_WORDS = {1: "una", 2: "dos", 3: "tres", 4: "cuatro", 5: "cinco", 6: "seis", 7: "siete",
             8: "ocho", 9: "nueve", 10: "diez"}


class Warnings(list):
    def add(self, msg):
        if msg not in self:
            self.append(msg)


# --------------------------------------------------------------------------- #
# Mini DOM sobre html.parser (tolerante: cierres huerfanos ignorados)
# --------------------------------------------------------------------------- #
class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = attrs
        self.children = []
        self.parent = parent

    def has_class(self, cls):
        return cls in (self.attrs.get("class") or "").split()

    def elements(self):
        for c in self.children:
            if isinstance(c, Node):
                yield c
                yield from c.elements()

    def find_all(self, tag=None, cls=None, pred=None):
        out = []
        for n in self.elements():
            if tag and n.tag != tag:
                continue
            if cls and not n.has_class(cls):
                continue
            if pred and not pred(n):
                continue
            out.append(n)
        return out

    def find(self, *a, **k):
        r = self.find_all(*a, **k)
        return r[0] if r else None

    def ancestors(self):
        n = self.parent
        while n is not None:
            yield n
            n = n.parent


class TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {}, None)
        self.cur = self.root

    def _mk(self, tag, attrs):
        node = Node(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur)
        self.cur.children.append(node)
        return node

    def handle_starttag(self, tag, attrs):
        node = self._mk(tag, attrs)
        if tag not in VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self._mk(tag, attrs)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        n = self.cur
        while n is not None and n is not self.root and n.tag != tag:
            n = n.parent
        if n is not None and n is not self.root:
            self.cur = n.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def parse(src):
    tb = TreeBuilder()
    tb.feed(src)
    tb.close()
    return tb.root


def norm(s):
    """Normaliza espacios (incluye nbsp) a un solo espacio y recorta."""
    return " ".join((s or "").split())


def fold(s):
    """minusculas sin tildes, para comparar rotulos (dt)."""
    s = unicodedata.normalize("NFKD", norm(s)).casefold()
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def slugify(s):
    s = fold(s)
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def get_text(node, skip=SKIP_TEXT):
    parts = []

    def walk(n):
        for c in n.children:
            if isinstance(c, str):
                parts.append(c)
            elif c.tag not in skip:
                blk = c.tag in BLOCK
                if blk:
                    parts.append(" ")
                walk(c)
                if blk:
                    parts.append(" ")

    walk(node)
    return norm("".join(parts))


def get_lines(node):
    """Texto de un nodo dividido en lineas por <br>."""
    lines, cur = [], []

    def walk(n):
        for c in n.children:
            if isinstance(c, str):
                cur.append(c)
            elif c.tag == "br":
                lines.append(norm("".join(cur)))
                cur.clear()
            elif c.tag not in SKIP_TEXT:
                walk(c)

    walk(node)
    lines.append(norm("".join(cur)))
    return [ln for ln in lines if ln]


def dl_pairs(container):
    """{fold(dt): dd_node} para todos los dt/dd bajo container (dd = siguiente hermano dd)."""
    out = {}
    for dt in container.find_all("dt"):
        sibs = [c for c in dt.parent.children if isinstance(c, Node)]
        try:
            i = sibs.index(dt)
        except ValueError:
            continue
        for s in sibs[i + 1:]:
            if s.tag == "dt":
                break
            if s.tag == "dd":
                out.setdefault(fold(get_text(dt)), s)
                break
    return out


def parse_es_number(s):
    """'168,15' -> 168.15 ; '2.000' -> 2000 ; '3' -> 3 (formato es-CO)."""
    s = (s or "").strip()
    m = re.search(r"\d[\d.,]*", s)
    if not m:
        return None
    t = m.group(0).rstrip(".,")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", t):
        t = t.replace(".", "")
    try:
        v = float(t)
    except ValueError:
        return None
    return int(v) if v == int(v) and "," not in m.group(0) else v


def leading_int(s):
    m = re.match(r"\s*(\d+)", s or "")
    return int(m.group(1)) if m else None


def abs_url(u, site):
    if not u:
        return None
    if re.match(r"^[a-z][a-z0-9+.-]*:", u, re.I):
        return u
    return urljoin(site, quote(u, safe="/:%?=&#-._~"))


# --------------------------------------------------------------------------- #
# Extraccion de hechos desde el HTML
# --------------------------------------------------------------------------- #
def read_meta(doc):
    meta = {}
    for m in doc.find_all("meta"):
        key = m.attrs.get("name") or m.attrs.get("property")
        if key and "content" in m.attrs:
            meta.setdefault(key, m.attrs["content"])
    return meta


def extract_typologies(doc, site, warns):
    res = []
    for panel in doc.find_all(cls="typo-panel"):
        title_el = panel.find(cls="spec-title")
        raw = get_text(title_el) if title_el else ""
        name = re.sub(r"^casa\s+", "", raw, flags=re.I).strip()
        if not name:
            warns.add("typo-panel sin h3.spec-title legible (%s): se omite" % panel.attrs.get("id", "?"))
            continue
        pairs = {k: get_text(v) for k, v in dl_pairs(panel).items()}

        def pick(prefix):
            for k, v in pairs.items():
                if k.startswith(prefix):
                    return v
            return None

        area_txt = pick("area")
        area = parse_es_number(area_txt) if area_txt else None
        beds_txt = pick("habitacion")
        baths_txt = pick("bano")
        program = [get_text(li) for li in panel.find_all("li") if
                   any(a.has_class("spec-program") for a in li.ancestors())]
        main_img = panel.find("img", pred=lambda n: any(a.has_class("viewer-main") for a in n.ancestors()))
        src = None
        if main_img is not None:
            src = main_img.attrs.get("src") or main_img.attrs.get("data-src")
        if not src:
            for th in panel.find_all(cls="thumb"):
                if "data-src" in th.attrs and "data-plan" not in th.attrs:
                    src = th.attrs["data-src"]
                    break
        res.append({
            "name": name, "slug": slugify(name), "area_txt": area_txt, "area": area,
            "beds_txt": beds_txt, "beds": leading_int(beds_txt), "baths_txt": baths_txt,
            "baths": leading_int(baths_txt), "garage": pick("garaje"), "levels": pick("nivel"),
            "lot": pick("lote"), "program": program, "image": abs_url(src, site),
        })
    return res


def extract_faq(doc, warns):
    items = []
    for it in doc.find_all(cls="faq-item"):
        q_el = it.find(cls="faq-qt")
        a_el = it.find(cls="faq-a-inner")
        ps = a_el.find_all("p") if a_el is not None else []
        if q_el is None or not ps:
            warns.add("faq-item incompleto (sin span.faq-qt o sin <p> en .faq-a-inner): se omite")
            continue
        q = get_text(q_el)
        q = re.sub(r"^\d{1,2}\s*[.)\-\u2013\u2014\u00b7:]?\s*(?=[\u00bf\u00a1A-Z\u00c1\u00c9\u00cd\u00d3\u00da\u00dc\u00d1])", "", q)
        a = norm(" ".join(get_text(p) for p in ps))
        if q and a:
            items.append((q, a))
    return items


def extract_contact(doc, warns):
    box = doc.find(cls="contact-info")
    out = {}
    if box is None:
        warns.add("no se encontro .contact-info: se omite la sala de ventas")
        return out
    pairs = dl_pairs(box)
    for k, dd in pairs.items():
        if k.startswith("sala de ventas"):
            out["lines"] = get_lines(dd)
        elif k.startswith("whatsapp") or k.startswith("telefono"):
            out.setdefault("phone", get_text(dd))
        elif k.startswith("correo") or k.startswith("email"):
            out["email"] = get_text(dd)
    if "phone" not in out:
        a = box.find("a", pred=lambda n: n.attrs.get("href", "").startswith("tel:"))
        if a is not None:
            out["phone"] = get_text(a)
    if "email" not in out:
        a = box.find("a", pred=lambda n: n.attrs.get("href", "").startswith("mailto:"))
        if a is not None:
            out["email"] = get_text(a)
    return out


def extract_project(doc, body_text, n_typo, warns):
    ficha_el = doc.find(cls="ficha")
    ficha = {k: get_text(v) for k, v in dl_pairs(ficha_el).items()} if ficha_el is not None else {}
    p = {}
    m = re.search(r"\d+", ficha.get("casas", ""))
    if not m:
        m = re.search(r"(\d+)\s+casas", body_text)
        if m:
            warns.add("N de casas derivado del texto libre (no de la ficha tecnica)")
    p["casas"] = int(m.group(0) if m.lastindex is None else m.group(1)) if m else None
    p["una_planta"] = "una planta" in ficha.get("casas", "").lower() or "1 planta" in ficha.get("casas", "").lower()
    lot = ficha.get("lotes", "")
    m = re.search(r"\d{1,3}(?:\.\d{3})*(?:,\d+)?\s*m²", lot)
    p["lote"] = ("aprox. " if re.search(r"aprox", lot, re.I) else "") + m.group(0) if m else None
    des = ficha.get("desarrollo", "")
    m = re.search(r"(\d+)\s+etapas", des) or re.search(r"(\d+)\s+etapas", body_text)
    p["etapas"] = int(m.group(1)) if m else None
    m = re.search(r"etapa\s+(\d+)\s+en construcci[oó]n", des + " " + body_text, re.I)
    p["etapa_construccion"] = int(m.group(1)) if m else None
    p["adicionales"] = bool(re.search(
        r"piscina[^.]{0,80}jacuzzi[^.]{0,80}kiosko[^.]{0,80}m[oó]dulo de servicio[^.]{0,80}adicionales",
        body_text, re.I))
    p["n_typo"] = n_typo
    return p


def amenity_features(body_text, doc):
    corpus = body_text.casefold()
    box = doc.find(cls="ficha")
    if box is not None:  # tambien pares "rotulo valor" de la ficha (p. ej. Cerramiento + Perimetral ...)
        corpus += " " + " ".join(
            (k + " " + get_text(v)).casefold() for k, v in dl_pairs(box).items())
    out = []
    for name, needles in AMENITIES:
        if all(n.casefold() in corpus for n in needles):
            out.append({"@type": "LocationFeatureSpecification", "name": name, "value": True})
    return out


# --------------------------------------------------------------------------- #
# Construccion del grafo
# --------------------------------------------------------------------------- #
def si(site, frag):
    return site + "#" + frag


def ref(site, frag):
    return {"@id": si(site, frag)}


def house_description(t):
    parts = []
    lvl = t["levels"] or ""
    m = re.match(r"\s*(\d+)\s+planta", lvl, re.I)
    head = "Casa de campo"
    if m:
        n = int(m.group(1))
        head += " de una planta" if n == 1 else " de %d plantas" % n
    feats = []
    if t["beds"] is not None:
        b = "%d habitación" % t["beds"] if t["beds"] == 1 else "%d habitaciones" % t["beds"]
        prog = " ".join(t["program"]).casefold()
        if "estudio independiente" in prog:
            b += " y estudio independiente"
        elif "estudio" in (t["beds_txt"] or "").casefold() or "estudio" in prog:
            b += " y estudio"
        feats.append(b)
    if t["baths"] is not None:
        feats.append("%d baño" % t["baths"] if t["baths"] == 1 else "%d baños" % t["baths"])
    if t["garage"]:
        feats.append("garaje " + t["garage"].lower())
    s = head
    if feats:
        s += " con " + (", ".join(feats[:-1]) + " y " + feats[-1] if len(feats) > 1 else feats[0])
    parts.append(s + ".")
    tail = []
    if t["area_txt"]:
        tail.append(t["area_txt"].replace(" m²", "").strip() + " m² construidos")
    if t["lot"]:
        tail.append("en un lote de " + t["lot"][0].lower() + t["lot"][1:])
    if tail:
        parts.append(" ".join(tail) + ".")
    return " ".join(parts)


def build_graph(doc, warns):
    head_link = doc.find("link", pred=lambda n: n.attrs.get("rel", "").lower() == "canonical")
    site = SITE
    if head_link is not None and head_link.attrs.get("href", "").startswith("http"):
        site = head_link.attrs["href"].split("#")[0]
        if not site.endswith("/"):
            site += "/"
    meta = read_meta(doc)
    title_el = doc.find("title")
    title = get_text(title_el, skip=set()) if title_el else ""
    body = doc.find("body") or doc
    body_text = get_text(body)
    graph = []

    # ---- Organization PROA --------------------------------------------------
    org = {"@type": "Organization", "@id": si(site, "proa"), "name": "PROA"}
    if "PROA" not in body_text:
        warns.add("'PROA' no aparece en el texto visible")
    m = re.search(r"PROA\s*\(([^)]+)\)", body_text)
    if m:
        org["alternateName"] = norm(m.group(1))
    a = doc.find("a", pred=lambda n: "proarquitectura.co" in (urlsplit(n.attrs.get("href", "")).hostname or ""))
    if a is not None:
        u = urlsplit(a.attrs["href"])
        org["url"] = "%s://%s" % (u.scheme, u.netloc)
    else:
        warns.add("no hay enlace a proarquitectura.co: Organization sin url")
    graph.append(org)

    # ---- Sala de ventas ----------------------------------------------------
    contact = extract_contact(doc, warns)
    lines = contact.get("lines") or []
    has_agent = bool(lines)
    if has_agent:
        addr = {"@type": "PostalAddress", "streetAddress": lines[0]}
        if len(lines) > 1:
            loc = [norm(x) for x in lines[1].split(",")]
            addr["addressLocality"] = loc[0]
            if len(loc) > 1:
                addr["addressRegion"] = ", ".join(loc[1:])
        addr["addressCountry"] = "CO"
        agent = {"@type": "RealEstateAgent", "@id": si(site, "sala-de-ventas"),
                 "name": "Hacienda Primavera — Sala de ventas", "url": site, "address": addr}
        if contact.get("phone"):
            agent["telephone"] = contact["phone"]
        if contact.get("email"):
            agent["email"] = contact["email"]
        agent["parentOrganization"] = ref(site, "proa")
        graph.append(agent)
    else:
        warns.add("sin direccion de sala de ventas en el HTML: se omite RealEstateAgent")

    # ---- Tipologias --------------------------------------------------------
    typos = extract_typologies(doc, site, warns)
    seen = set()
    houses = []
    for t in typos:
        if t["slug"] in seen:
            warns.add("tipologia duplicada: " + t["name"])
            continue
        seen.add(t["slug"])
        node = {"@type": "SingleFamilyResidence", "@id": si(site, "casa-" + t["slug"]),
                "name": "Casa de campo " + t["name"], "description": house_description(t)}
        if t["area"] is not None:
            node["floorSize"] = {"@type": "QuantitativeValue", "value": t["area"], "unitCode": "MTK"}
        else:
            warns.add("sin area para " + t["name"])
        if t["beds"] is not None:
            node["numberOfBedrooms"] = t["beds"]
        if t["baths"] is not None:
            node["numberOfBathroomsTotal"] = t["baths"]
        if t["image"]:
            node["image"] = t["image"]
        else:
            warns.add("sin imagen para " + t["name"])
        houses.append(node)
    if not houses:
        warns.add("no se encontro ningun .typo-panel")

    # ---- Imagenes ----------------------------------------------------------
    og_url = abs_url(meta.get("og:image"), site)
    hero = doc.find("img", pred=lambda n: n.attrs.get("fetchpriority", "").lower() == "high")
    img_og = img_hero = None
    if og_url:
        img_og = {"@type": "ImageObject", "@id": si(site, "img-og"), "url": og_url, "contentUrl": og_url}
        w, h = leading_int(meta.get("og:image:width")), leading_int(meta.get("og:image:height"))
        if w and h:
            img_og["width"], img_og["height"] = w, h
        if meta.get("og:image:alt"):
            img_og["caption"] = norm(meta["og:image:alt"])
    else:
        warns.add("sin og:image: se omite #img-og")
    if hero is not None and hero.attrs.get("src"):
        hu = abs_url(hero.attrs["src"], site)
        img_hero = {"@type": "ImageObject", "@id": si(site, "img-hero"), "url": hu, "contentUrl": hu}
        w, h = leading_int(hero.attrs.get("width")), leading_int(hero.attrs.get("height"))
        if w and h:
            img_hero["width"], img_hero["height"] = w, h
        else:
            warns.add("la imagen del hero no declara width/height")
        cap = "Vista del conjunto (render ilustrativo)"
        fig = next((x for x in hero.ancestors() if x.tag == "figure"), None)
        fc = fig.find("figcaption") if fig is not None else None
        if fc is not None:
            spans = [get_text(s) for s in fc.find_all("span")]
            if len(spans) >= 2 and spans[0] and spans[1]:
                first = re.sub(r"^Fig\.?\s*\d+\s*[\u2014\u2013-]\s*", "", spans[0]).strip()
                cap = "%s (%s)" % (first, spans[1].lower())
        img_hero["caption"] = cap
    else:
        warns.add("no hay <img fetchpriority=high>: se omite #img-hero")

    # ---- Video (solo con metadatos verificados) ----------------------------
    video = None
    vfr = doc.find(pred=lambda n: "data-video" in n.attrs)
    vid_node = doc.find(pred=lambda n: n.attrs.get("id") == "video")
    if vfr is not None:
        vid = vfr.attrs["data-video"].strip()
        ver = VERIFIED_VIDEOS.get(vid)
        if ver and ver.get("uploadDate"):
            video = {"@type": "VideoObject", "@id": si(site, "video"),
                     "name": "Hacienda Primavera — Recorrido audiovisual"}
            lead = vid_node.find(cls="sec-lead") if vid_node is not None else None
            if lead is not None and get_text(lead):
                video["description"] = get_text(lead)
            else:
                warns.add("no se encontro descripcion del video (#video .sec-lead)")
            video["thumbnailUrl"] = "https://i.ytimg.com/vi/%s/maxresdefault.jpg" % vid
            video["uploadDate"] = ver["uploadDate"]
            if ver.get("duration"):
                video["duration"] = ver["duration"]
            video["embedUrl"] = "https://www.youtube-nocookie.com/embed/" + vid
        else:
            warns.add("video %s sin uploadDate verificado: se OMITE VideoObject" % vid)

    # ---- WebSite / WebPage -------------------------------------------------
    graph.append({"@type": "WebSite", "@id": si(site, "website"), "url": site,
                  "name": "Hacienda Primavera", "inLanguage": LANG, "publisher": ref(site, "proa")})
    page = {"@type": "WebPage", "@id": si(site, "webpage"), "url": site, "name": title,
            "description": norm(meta.get("description", "")), "inLanguage": LANG,
            "isPartOf": ref(site, "website"), "about": ref(site, "proyecto")}
    if not page["description"]:
        del page["description"]
        warns.add("sin meta description")
    if img_og:
        page["primaryImageOfPage"] = ref(site, "img-og")
    if video:
        page["video"] = ref(site, "video")
    graph.append(page)

    # ---- Proyecto ----------------------------------------------------------
    proj = extract_project(doc, body_text, len(houses), warns)
    bits = []
    if proj["casas"]:
        s = "%d casas de campo" % proj["casas"] + (" de una planta" if proj["una_planta"] else "")
        if proj["lote"]:
            s += " en lotes de " + proj["lote"]
        bits.append(s)
    elif proj["lote"]:
        bits.append("Lotes de " + proj["lote"])
    if proj["etapas"]:
        s = "desarrolladas en %d etapas" % proj["etapas"]
        if proj["etapa_construccion"] == 1:
            s += " con la primera en construcción"
        elif proj["etapa_construccion"]:
            s += " con la etapa %d en construcción" % proj["etapa_construccion"]
        bits.append(s)
    desc = ", ".join(bits)
    areas = [(t["area"], t["area_txt"]) for t in typos if t["area"] is not None]
    if areas:
        lo, hi = min(areas), max(areas)
        strip = lambda x: x.replace(" m²", "").strip()
        n = len(houses)
        word = NUM_WORDS.get(n, str(n))
        desc = (desc + ". " if desc else "") + \
            "%s tipologías de %s a %s m² construidos" % (word.capitalize(), strip(lo[1]), strip(hi[1]))
    if proj["adicionales"]:
        desc = (desc + ". " if desc else "") + \
            "La piscina, el jacuzzi, el kiosko y el módulo de servicio son adicionales"
    else:
        warns.add("no se hallo en el HTML la aclaracion de adicionales: no se incluye en la descripcion")
    desc = desc.strip()
    if desc and not desc.endswith("."):
        desc += "."
    if desc:
        desc = desc[0].upper() + desc[1:]
    project = {"@type": "GatedResidenceCommunity", "@id": si(site, "proyecto"), "name": "Hacienda Primavera"}
    if desc:
        project["description"] = desc
    if re.search(r"Eje Cafetero, Colombia", body_text):
        project["containedInPlace"] = {"@type": "Place", "name": "Eje Cafetero, Colombia"}
    else:
        warns.add("'Eje Cafetero, Colombia' no aparece en el texto visible: sin containedInPlace")
    if houses:
        project["containsPlace"] = [{"@id": h["@id"]} for h in houses]
    am = amenity_features(body_text, doc)
    if am:
        project["amenityFeature"] = am
    for name, needles in AMENITIES:
        if name not in [a["name"] for a in am]:
            warns.add("amenidad no sustentada en el HTML, omitida: " + name)
    if img_hero:
        project["image"] = ref(site, "img-hero")
    graph.append(project)
    graph.extend(houses)

    # ---- FAQ ---------------------------------------------------------------
    faq = extract_faq(doc, warns)
    if faq:
        sec = next((a for it in doc.find_all(cls="faq-item")[:1] for a in it.ancestors()
                    if a.attrs.get("id")), None)
        frag = sec.attrs["id"] if sec is not None else "preguntas"
        graph.append({
            "@type": "FAQPage", "@id": si(site, "faq"), "url": site + "#" + frag,
            "isPartOf": ref(site, "webpage"),
            "mainEntity": [{"@type": "Question", "name": q,
                            "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]})
    else:
        warns.add("no hay .faq-item: se omite FAQPage")

    if video:
        graph.append(video)
    if img_og:
        graph.append(img_og)
    if img_hero:
        graph.append(img_hero)
    return {"@context": "https://schema.org", "@graph": graph}, faq, body_text


def dump(data):
    s = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return s.replace("</", "<\\/").replace("<!--", "\\u003c!--")


def build_block(data, indent="", eol="\n"):
    return (MARK_START + eol + indent + '<script type="application/ld+json">' + dump(data) +
            "</script>" + eol + indent + MARK_END)


# --------------------------------------------------------------------------- #
# Inyeccion idempotente
# --------------------------------------------------------------------------- #
def detect_eol(src):
    crlf = src.count("\r\n")
    return "\r\n" if crlf and crlf * 2 > src.count("\n") else "\n"


def inject(src, data):
    eol = detect_eol(src)
    ns, ne = src.count(MARK_START), src.count(MARK_END)
    if ns != ne or ns > 1:
        raise ValueError("marcadores inconsistentes (start=%d, end=%d): corrijalos a mano" % (ns, ne))
    if ns == 1:
        i, j = src.index(MARK_START), src.index(MARK_END)
        if j < i:
            raise ValueError("el marcador end aparece antes que start")
        line_start = src.rfind("\n", 0, i) + 1
        lead = src[line_start:i]
        indent = lead if not lead.strip() else ""
        return src[:i] + build_block(data, indent, eol) + src[j + len(MARK_END):], "actualizado"
    h0 = src.find("<head")
    h1 = src.find("</head>")
    if h0 < 0 or h1 < 0:
        raise ValueError("no se encontro <head>...</head>")
    k = src.find(PRECONNECT, h0, h1)
    if k >= 0:
        ls = src.rfind("\n", 0, k) + 1
        lead = src[ls:k]
        indent = lead if not lead.strip() else ""
        return src[:ls] + indent + build_block(data, indent, eol) + eol + src[ls:], "insertado (antes de preconnect)"
    ls = src.rfind("\n", 0, h1) + 1
    lead = src[ls:h1]
    indent = lead if not lead.strip() else ""
    return src[:ls] + indent + build_block(data, indent, eol) + eol + src[ls:], "insertado (antes de </head>)"


# --------------------------------------------------------------------------- #
# Verificacion (--check)
# --------------------------------------------------------------------------- #
def collect_refs(o, out):
    if isinstance(o, dict):
        if set(o.keys()) == {"@id"}:
            out.add(o["@id"])
        for v in o.values():
            collect_refs(v, out)
    elif isinstance(o, list):
        for v in o:
            collect_refs(v, out)


def walk_forbidden(o, path, fails):
    if isinstance(o, dict):
        t = o.get("@type")
        for tt in (t if isinstance(t, list) else [t]):
            if isinstance(tt, str) and tt.casefold() in FORBIDDEN_TYPES:
                fails.append("tipo prohibido %s en %s" % (tt, path or "/"))
        for k, v in o.items():
            if k.casefold() in FORBIDDEN_KEYS:
                fails.append("propiedad prohibida '%s' en %s" % (k, path or "/"))
            walk_forbidden(v, path + "/" + k, fails)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            walk_forbidden(v, "%s[%d]" % (path, i), fails)
    elif isinstance(o, str) and FORBIDDEN_TEXT.search(o):
        fails.append("marcador TODO/CONFIRMAR en %s" % path)


def check_source(src, html_dir=None):
    """Devuelve (fails, warns). No escribe nada."""
    fails, warns = [], Warnings()
    ns, ne = src.count(MARK_START), src.count(MARK_END)
    if ns != 1 or ne != 1:
        fails.append("marcadores JSON-LD: start=%d end=%d (se esperaba 1 y 1)" % (ns, ne))
        return fails, warns
    i, j = src.index(MARK_START), src.index(MARK_END)
    if j < i:
        fails.append("el marcador end precede al start")
        return fails, warns
    region = src[i + len(MARK_START):j]
    if region.count("<script") != 1 or region.count("</script>") != 1:
        fails.append("entre los marcadores debe haber exactamente un <script>")
    doc = parse(src)
    lds = doc.find_all("script", pred=lambda n: n.attrs.get("type", "").strip().lower() == "application/ld+json")
    if not lds:
        fails.append("no existe <script type=application/ld+json>")
        return fails, warns
    if len(lds) > 1:
        fails.append("hay %d bloques ld+json; debe existir uno solo" % len(lds))
    raw = "".join(c for c in lds[0].children if isinstance(c, str))
    if "\n" in raw.strip():
        warns.add("el JSON no esta en una sola linea")
    try:
        data = json.loads(raw)
    except ValueError as e:
        fails.append("JSON no parsea: %s" % e)
        return fails, warns
    if data.get("@context") != "https://schema.org" or not isinstance(data.get("@graph"), list):
        fails.append("se esperaba @context schema.org y @graph")
        return fails, warns
    graph = data["@graph"]
    defined, dups = set(), set()
    for n in graph:
        if isinstance(n, dict) and "@id" in n:
            (dups if n["@id"] in defined else defined).add(n["@id"])
    if dups:
        fails.append("@id duplicados: %s" % sorted(dups))
    refs = set()
    collect_refs(graph, refs)
    missing = sorted(refs - defined)
    if missing:
        fails.append("@id referenciados que no existen: %s" % missing)
    # --- prohibiciones -------------------------------------------------------
    walk_forbidden(data, "", fails)
    for n in graph:
        if isinstance(n, dict) and n.get("@type") == "GatedResidenceCommunity":
            for bad in ("address", "geo"):
                if bad in n:
                    fails.append("el proyecto no debe llevar '%s'" % bad)
            for a in n.get("amenityFeature", []):
                if FORBIDDEN_AMENITY.search(a.get("name", "")):
                    fails.append("amenityFeature prohibida: %s" % a.get("name"))
    if "</script" in raw.lower():
        fails.append("el JSON contiene </script")
    # --- FAQ literal vs texto visible -----------------------------------------
    body = doc.find("body") or doc
    body_norm = get_text(body)
    warn_dummy = Warnings()
    vis_faq = extract_faq(doc, warn_dummy)
    faq_nodes = [n for n in graph if isinstance(n, dict) and n.get("@type") == "FAQPage"]
    if not vis_faq and faq_nodes:
        fails.append("FAQPage presente pero el HTML no tiene .faq-item")
    if vis_faq and not faq_nodes:
        fails.append("el HTML tiene FAQ visible pero falta FAQPage")
    for fn in faq_nodes:
        ents = fn.get("mainEntity", [])
        if len(ents) != len(vis_faq):
            fails.append("FAQPage tiene %d preguntas y el HTML %d" % (len(ents), len(vis_faq)))
        for k, e in enumerate(ents):
            q = e.get("name", "")
            a = (e.get("acceptedAnswer") or {}).get("text", "")
            if k < len(vis_faq):
                if norm(q) != vis_faq[k][0]:
                    fails.append("FAQ #%d pregunta no coincide con el texto visible: %r" % (k + 1, q[:60]))
                if norm(a) != vis_faq[k][1]:
                    fails.append("FAQ #%d respuesta no coincide con el texto visible" % (k + 1))
            if norm(q) not in body_norm:
                fails.append("FAQ #%d pregunta no aparece en el texto visible" % (k + 1))
            if norm(a) not in body_norm:
                fails.append("FAQ #%d respuesta no aparece en el texto visible" % (k + 1))
    # --- vigencia: el bloque debe ser igual al que se generaria hoy -------------
    gen_warns = Warnings()
    fresh, _, _ = build_graph(doc, gen_warns)
    for w in gen_warns:
        warns.add(w)
    if fresh != data:
        by_id = {n.get("@id"): n for n in data["@graph"] if isinstance(n, dict)}
        diff = [n["@id"].split("#")[-1] for n in fresh["@graph"] if by_id.get(n["@id"]) != n]
        extra = [k.split("#")[-1] for k in by_id if k not in {n["@id"] for n in fresh["@graph"]}]
        fails.append("bloque DESACTUALIZADO respecto al HTML (nodos distintos: %s%s); ejecute build_jsonld.py"
                     % (", ".join(diff) or "-", "; sobrantes: " + ", ".join(extra) if extra else ""))
    # --- avisos ---------------------------------------------------------------
    for s in _strings(data):
        if PRICE_TEXT.search(s):
            warns.add("el JSON-LD contiene un precio/COP (texto visible que se replica literalmente): "
                      + PRICE_TEXT.search(s).group(0) + " ... " + s[max(0, PRICE_TEXT.search(s).start() - 30):
                                                                       PRICE_TEXT.search(s).end() + 20])
    if html_dir:
        base = fresh_site(doc)
        for u in _strings(data):
            if u.startswith(base) and re.search(r"\.(webp|jpe?g|png|avif|svg)$", u, re.I):
                path = os.path.join(html_dir, u[len(base):])
                if not os.path.isfile(path):
                    warns.add("imagen referenciada no existe en disco: " + u[len(base):])
    return fails, warns


def _strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from _strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from _strings(v)


def fresh_site(doc):
    link = doc.find("link", pred=lambda n: n.attrs.get("rel", "").lower() == "canonical")
    if link is not None and link.attrs.get("href", "").startswith("http"):
        s = link.attrs["href"].split("#")[0]
        return s if s.endswith("/") else s + "/"
    return SITE


# --------------------------------------------------------------------------- #
# Verificacion en vivo del video (opcional, usa red)
# --------------------------------------------------------------------------- #
def verify_video():
    import urllib.request
    ok = True
    for vid, ver in VERIFIED_VIDEOS.items():
        req = urllib.request.Request(
            "https://www.youtube.com/watch?v=" + vid,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                     "Accept": "text/html,*/*;q=0.8", "Accept-Language": "es-CO,es;q=0.9"})
        try:
            html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            print("ERROR de red verificando %s: %s" % (vid, e), file=sys.stderr)
            return 2
        doc = parse(html)
        live = {}
        for m in doc.find_all("meta"):
            ip = m.attrs.get("itemprop")
            if ip in ("uploadDate", "duration", "datePublished", "name"):
                live.setdefault(ip, m.attrs.get("content"))
        for k in ("uploadDate", "duration"):
            good = live.get(k) == ver[k]
            ok &= good
            print("%-11s constante=%s  youtube=%s  %s" % (k, ver[k], live.get(k), "OK" if good else "DIFIERE"))
        print("titulo      %s" % live.get("name"))
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def read_file(path):
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


def write_file(path, text):
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".jsonld-", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        shutil.copymode(path, tmp)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def report(fails, warns, stream=sys.stderr):
    for w in warns:
        print("WARN: " + w, file=stream)
    for f in fails:
        print("FAIL: " + f, file=stream)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Inyecta/verifica el bloque JSON-LD de index.html")
    ap.add_argument("html", nargs="?", help="ruta a index.html")
    ap.add_argument("--check", action="store_true", help="solo verificar (no escribe)")
    ap.add_argument("--print", dest="print_", action="store_true", help="imprimir el bloque (no escribe)")
    ap.add_argument("--strict", action="store_true", help="los WARN cuentan como error")
    ap.add_argument("--verify-video", action="store_true", help="re-verificar el video en YouTube")
    args = ap.parse_args(argv)

    if args.verify_video:
        return verify_video()
    if not args.html:
        ap.print_usage(sys.stderr)
        return 2
    try:
        src = read_file(args.html)
    except OSError as e:
        print("ERROR: no se puede leer %s: %s" % (args.html, e), file=sys.stderr)
        return 2
    html_dir = os.path.dirname(os.path.abspath(args.html))

    if args.check:
        fails, warns = check_source(src, html_dir)
        report(fails, warns)
        if fails or (args.strict and warns):
            print("CHECK: FALLO (%d error(es), %d aviso(s))" % (len(fails), len(warns)))
            return 1
        print("CHECK: OK (%d aviso(s))" % len(warns))
        return 0

    warns = Warnings()
    doc = parse(src)
    data, faq, _ = build_graph(doc, warns)
    fails = []
    walk_forbidden(data, "", fails)
    if fails:
        report(fails, warns)
        return 1
    try:
        new_src, action = inject(src, data)
    except ValueError as e:
        print("ERROR: %s" % e, file=sys.stderr)
        return 2
    # Fail-closed: el resultado debe pasar --check antes de escribirse.
    fails, cwarns = check_source(new_src, html_dir)
    for w in cwarns:
        warns.add(w)
    report(fails, warns)
    if fails or (args.strict and warns):
        print("ABORTADO: el bloque generado no pasa la verificacion; no se escribio nada.", file=sys.stderr)
        return 1
    if args.print_:
        i = new_src.index(MARK_START)
        j = new_src.index(MARK_END) + len(MARK_END)
        sys.stdout.write(new_src[i:j] + "\n")
        return 0
    others = [n for n in doc.find_all("script", pred=lambda n: n.attrs.get("type", "").lower() == "application/ld+json")]
    if others and MARK_START not in src:
        print("WARN: ya existian %d bloque(s) ld+json fuera de los marcadores; revise duplicados" % len(others),
              file=sys.stderr)
    if new_src == src:
        print("SIN CAMBIOS: %s ya estaba al dia (%d nodos)" % (args.html, len(data["@graph"])))
        return 0
    write_file(args.html, new_src)
    print("OK: JSON-LD %s en %s (%d nodos, %d bytes de JSON)" %
          (action, args.html, len(data["@graph"]), len(dump(data).encode("utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
