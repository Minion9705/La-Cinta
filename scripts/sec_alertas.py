#!/usr/bin/env python3
"""
La Cinta - lector de la SEC (EDGAR).

Lee los documentos recientes que presentan ante la SEC las empresas de
`empresas.txt`, los clasifica y escribe explicaciones en español en
`data/alertas.json`, que es lo que muestra el sitio.

- Sin dependencias: solo Python 3.9+.
- Gratis: EDGAR es público. La IA es OPCIONAL (si defines ANTHROPIC_API_KEY
  las explicaciones incluyen cifras del documento; si no, se usan plantillas).

Uso:
    SEC_USER_AGENT="La Cinta tu-correo@ejemplo.com" python scripts/sec_alertas.py
    python scripts/sec_alertas.py --loop 60      # repetir cada 60 s (en un servidor)

La SEC exige un User-Agent con un correo de contacto y máximo 10 consultas
por segundo. Este script respeta ese límite.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    ET_TZ = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    ET_TZ = timezone(timedelta(hours=-4))

RAIZ = Path(__file__).resolve().parent.parent
ARCHIVO_EMPRESAS = RAIZ / "empresas.txt"
ARCHIVO_SALIDA = RAIZ / "data" / "alertas.json"
CACHE_TICKERS = RAIZ / "data" / ".company_tickers.json"

USER_AGENT = os.environ.get("SEC_USER_AGENT", "").strip()
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODELO = os.environ.get("ANTHROPIC_MODEL", "").strip() or "claude-haiku-4-5"
DIAS_ATRAS = int(os.environ.get("DIAS_ATRAS", "3"))
MAX_ALERTAS = int(os.environ.get("MAX_ALERTAS", "300"))
MAX_IA_POR_CORRIDA = int(os.environ.get("MAX_IA_POR_CORRIDA", "25"))
# Form 4: solo mostrar compras/ventas en mercado abierto por encima de estos montos (USD)
MIN_COMPRA_DIRECTIVO = float(os.environ.get("MIN_COMPRA_DIRECTIVO", "100000"))
MIN_VENTA_DIRECTIVO = float(os.environ.get("MIN_VENTA_DIRECTIVO", "5000000"))

# Telegram (opcional): canal público donde se publican las alertas nuevas
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()      # p. ej. @lacinta_alertas
TELEGRAM_MIN_RELEVANCIA = int(os.environ.get("TELEGRAM_MIN_RELEVANCIA", "2") or 2)
TELEGRAM_MAX_POR_CORRIDA = int(os.environ.get("TELEGRAM_MAX_POR_CORRIDA", "15") or 15)
TELEGRAM_HORAS_MAX = int(os.environ.get("TELEGRAM_HORAS_MAX", "12") or 12)  # no enviar noticias viejas
SITIO_URL = os.environ.get("SITIO_URL", "").strip().rstrip("/")

FORMULARIOS = {"8-K", "4", "424B5", "10-Q", "10-K", "SC 13D", "SCHEDULE 13D"}

# ---------------------------------------------------------------------------
# Plantillas en español por ítem del 8-K
# sev: neg (suele ser negativo), pos (positivo), mix (depende), neu (informativo)
# tipo: res, dir, dil, int, deu, riesgo, rep, otros
# ---------------------------------------------------------------------------
ITEMS = {
    "1.03": dict(tipo="riesgo", sev="neg", t="{e} se declaró en quiebra o entró en un proceso similar",
                 pri="La empresa pidió protección por bancarrota. Es de las noticias más graves para un accionista.",
                 int="Ítem 1.03: bancarrota o administración judicial. Los accionistas comunes suelen ser los últimos en cobrar.",
                 por="En una quiebra, los accionistas pueden perder casi todo lo invertido."),
    "4.02": dict(tipo="riesgo", sev="neg", t="{e} dice que sus estados financieros anteriores no son confiables",
                 pri="La empresa admitió errores en números que ya había publicado y tendrá que corregirlos.",
                 int="Ítem 4.02: no confiabilidad de estados financieros previos; implica una reexpresión (restatement).",
                 por="Pone en duda las cuentas de la empresa y suele castigar fuerte a la acción."),
    "3.01": dict(tipo="riesgo", sev="neg", t="{e} recibió un aviso de la bolsa por incumplir sus reglas",
                 pri="La bolsa le avisó que no cumple alguna regla y podría sacarla de la lista si no lo corrige.",
                 int="Ítem 3.01: aviso de exclusión o incumplimiento de requisitos de cotización.",
                 por="Salir de la bolsa reduce mucho la facilidad para comprar o vender la acción."),
    "4.01": dict(tipo="riesgo", sev="neg", t="{e} cambió de auditor",
                 pri="La empresa cambió a la firma que revisa sus cuentas.",
                 int="Ítem 4.01: cambio del auditor independiente. Revisar si hubo desacuerdos reportados.",
                 por="Muchas veces es rutina, pero si hubo desacuerdos puede ser una señal de alerta."),
    "2.06": dict(tipo="riesgo", sev="neg", t="{e} reconoció que algunos de sus activos valen menos",
                 pri="La empresa aceptó que algo que compró o construyó vale menos de lo que decía en sus libros.",
                 int="Ítem 2.06: deterioro material (impairment). Cargo contable, generalmente sin salida de efectivo.",
                 por="Indica que una inversión pasada no salió como esperaban."),
    "2.02": dict(tipo="res", sev="mix", t="{e} publicó sus resultados del trimestre",
                 pri="La empresa dio a conocer cuánto vendió y ganó en el trimestre. Lo que más mueve la acción suele ser lo que espera para el futuro.",
                 int="Ítem 2.02: resultados de operaciones. Revisa el comunicado (anexo 99.1): ingresos, BPA, márgenes y guía.",
                 por="Los resultados y, sobre todo, la guía para el próximo trimestre suelen mover más la acción que cualquier otra noticia."),
    "5.02": dict(tipo="dir", sev="mix", t="Cambio en la dirección de {e}",
                 pri="Entró o salió alguien importante de la dirección o de la junta de la empresa.",
                 int="Ítem 5.02: salida/nombramiento de directivos o consejeros, o cambios en su compensación.",
                 por="Una salida repentina (sobre todo del CEO o del director financiero) suele preocupar al mercado."),
    "3.02": dict(tipo="dil", sev="neg", t="{e} vendió acciones nuevas fuera de bolsa",
                 pri="La empresa creó y vendió acciones nuevas. Cada acción existente representa un pedazo un poco más pequeño.",
                 int="Ítem 3.02: venta no registrada de valores de capital (colocación privada). Posible dilución.",
                 por="Más acciones en circulación = dilución para los accionistas actuales."),
    "1.01": dict(tipo="otros", sev="mix", t="{e} firmó un acuerdo importante",
                 pri="La empresa firmó un contrato importante (una compra, un préstamo, una alianza…).",
                 int="Ítem 1.01: acuerdo material definitivo. El impacto depende del tipo y tamaño del contrato.",
                 por="Puede cambiar el rumbo del negocio, para bien o para mal."),
    "1.02": dict(tipo="otros", sev="neg", t="{e} terminó un acuerdo importante",
                 pri="Se canceló un contrato importante de la empresa.",
                 int="Ítem 1.02: terminación de un acuerdo material definitivo.",
                 por="Perder un contrato relevante puede afectar ingresos futuros."),
    "2.01": dict(tipo="otros", sev="mix", t="{e} completó una compra o venta de activos",
                 pri="La empresa terminó de comprar o vender un negocio o activos importantes.",
                 int="Ítem 2.01: adquisición o disposición de activos completada.",
                 por="Cambia el tamaño o la composición del negocio."),
    "2.03": dict(tipo="deu", sev="mix", t="{e} pidió dinero prestado",
                 pri="La empresa pidió dinero prestado (emitió bonos o firmó un préstamo).",
                 int="Ítem 2.03: creación de una obligación financiera directa material.",
                 por="Más deuda da flexibilidad, pero también aumenta el riesgo y los intereses a pagar."),
    "2.05": dict(tipo="otros", sev="mix", t="{e} anunció una reestructuración",
                 pri="La empresa va a recortar costos: cierres, despidos o salida de algún negocio.",
                 int="Ítem 2.05: costos asociados a actividades de salida o disposición (reestructuración).",
                 por="Cuesta dinero hoy, pero el mercado a veces lo premia si mejora las ganancias futuras."),
    "5.01": dict(tipo="otros", sev="mix", t="Cambio de control en {e}",
                 pri="Cambió quién controla la empresa.",
                 int="Ítem 5.01: cambio en el control del registrante.",
                 por="Un nuevo dueño puede cambiar por completo la estrategia."),
    "5.03": dict(tipo="otros", sev="neu", t="{e} modificó sus estatutos",
                 pri="La empresa cambió sus reglas internas o su año fiscal.",
                 int="Ítem 5.03: enmiendas a estatutos o cambio de año fiscal.",
                 por="Normalmente es un trámite; rara vez mueve la acción."),
    "5.07": dict(tipo="otros", sev="neu", t="Resultados de la votación de accionistas de {e}",
                 pri="Se publicaron los resultados de lo que votaron los accionistas.",
                 int="Ítem 5.07: presentación de asuntos a votación de los tenedores.",
                 por="Informativo; importa si una propuesta relevante fue rechazada."),
    "7.01": dict(tipo="otros", sev="neu", t="{e} compartió una presentación para inversionistas",
                 pri="La empresa compartió una presentación o comunicado para inversionistas.",
                 int="Ítem 7.01: divulgación bajo Regulación FD (presentaciones, comunicados).",
                 por="A veces incluye actualizaciones de guía; vale la pena revisarlo."),
    "8.01": dict(tipo="otros", sev="neu", t="{e} comunicó un anuncio a sus inversionistas",
                 pri="La empresa comunicó algo que considera importante (puede ser un dividendo, una recompra u otro anuncio).",
                 int="Ítem 8.01: otros eventos. Suele incluir dividendos, recompras o actualizaciones relevantes.",
                 por="Depende del contenido; revisa el documento."),
}
# Orden de importancia para elegir el titular cuando hay varios ítems
PRIORIDAD = ["1.03", "4.02", "3.01", "2.02", "5.02", "3.02", "4.01", "2.06", "1.02",
             "1.01", "2.01", "2.03", "2.05", "5.01", "8.01", "7.01", "5.03", "5.07"]

FORM_PLANTILLAS = {
    "424B5": dict(tipo="dil", sev="neg", t="{e} ofrece nuevos valores al público",
                  pri="La empresa está vendiendo acciones o bonos nuevos. Si son acciones, tu parte de la empresa se diluye un poco.",
                  int="Prospecto 424B5: oferta registrada (acciones, bonos o notas). Revisa tamaño, precio y uso de los fondos.",
                  por="Una oferta de acciones grande suele presionar el precio a corto plazo."),
    "10-Q": dict(tipo="rep", sev="neu", t="{e} presentó su reporte trimestral (10-Q)",
                 pri="La empresa entregó su reporte oficial del trimestre, con todos los detalles.",
                 int="Formulario 10-Q: estados financieros trimestrales no auditados y análisis de la gerencia (MD&A).",
                 por="Normalmente ya se conocían los números, pero puede traer detalles nuevos sobre riesgos."),
    "10-K": dict(tipo="rep", sev="neu", t="{e} presentó su reporte anual (10-K)",
                 pri="La empresa entregó su reporte anual completo.",
                 int="Formulario 10-K: estados financieros auditados, factores de riesgo y MD&A.",
                 por="Es el documento más completo sobre la empresa; útil para revisar riesgos nuevos."),
    "SC 13D": dict(tipo="otros", sev="mix", t="Un inversionista tomó más del 5 % de {e}",
                   pri="Alguien compró una parte grande de la empresa y podría querer influir en sus decisiones.",
                   int="Schedule 13D: participación >5 % con posible intención activa (activismo).",
                   por="Los inversionistas activistas suelen presionar por cambios que a veces suben el precio."),
}
FORM_PLANTILLAS["SCHEDULE 13D"] = FORM_PLANTILLAS["SC 13D"]

# ---------------------------------------------------------------------------
# HTTP con límite de velocidad
# ---------------------------------------------------------------------------
_ultima = 0.0


def http_get(url: str, binario: bool = False, reintentos: int = 3):
    global _ultima
    for intento in range(reintentos):
        espera = 0.12 - (time.time() - _ultima)  # < 10 consultas por segundo
        if espera > 0:
            time.sleep(espera)
        _ultima = time.time()
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "identity",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                datos = r.read()
                return datos if binario else datos.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and intento < reintentos - 1:
                time.sleep(2 * (intento + 1))
                continue
            raise
        except urllib.error.URLError:
            if intento < reintentos - 1:
                time.sleep(2 * (intento + 1))
                continue
            raise


def leer_empresas() -> list[tuple[str, str]]:
    """Líneas 'TICKER' o 'TICKER | Nombre para mostrar'."""
    empresas = []
    for linea in ARCHIVO_EMPRESAS.read_text(encoding="utf-8").splitlines():
        linea = linea.split("#", 1)[0].strip()
        if not linea:
            continue
        ticker, _, nombre = linea.partition("|")
        empresas.append((ticker.strip().upper(), nombre.strip()))
    return empresas


def mapa_tickers() -> dict[str, dict]:
    """ticker -> {cik, nombre}. Se descarga una vez al día."""
    fresco = CACHE_TICKERS.exists() and (time.time() - CACHE_TICKERS.stat().st_mtime) < 86400
    if not fresco:
        CACHE_TICKERS.parent.mkdir(parents=True, exist_ok=True)
        CACHE_TICKERS.write_text(http_get("https://www.sec.gov/files/company_tickers.json"), encoding="utf-8")
    datos = json.loads(CACHE_TICKERS.read_text(encoding="utf-8"))
    return {v["ticker"].upper(): {"cik": int(v["cik_str"]), "nombre": v["title"]} for v in datos.values()}


def nombre_bonito(nombre: str) -> str:
    """'APPLE INC.' -> 'Apple' ; quita sufijos legales comunes."""
    n = re.sub(r"[,\.]?\s+(INC|CORP|CORPORATION|CO|COMPANY|LTD|PLC|HOLDINGS|GROUP|N\.V|S\.A|LP|L\.P)\.?$", "",
               nombre.strip(), flags=re.I)
    n = re.sub(r"[,\.]?\s+(INC|CORP|CORPORATION|CO|HOLDINGS)\.?$", "", n, flags=re.I)
    n = n.rstrip(" &,.")
    return n.title() if n.isupper() else n


def fecha_aceptacion(valor: str, respaldo: str) -> str:
    """EDGAR publica acceptanceDateTime en UTC, p. ej. '2026-09-22T01:31:12.000Z'."""
    try:
        base = datetime.strptime(valor[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        base = datetime.strptime(respaldo, "%Y-%m-%d").replace(hour=9, tzinfo=ET_TZ)
    return base.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def url_documento(cik: int, acc: str, doc: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{doc}"


def url_indice(cik: int, acc: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{acc}-index.htm"


# ---------------------------------------------------------------------------
# Form 4: compras y ventas de directivos
# ---------------------------------------------------------------------------
def analizar_form4(xml_texto: str) -> dict | None:
    try:
        raiz = ET.fromstring(xml_texto.encode("utf-8"))
    except ET.ParseError:
        return None

    def txt(nodo, ruta):
        e = nodo.find(ruta)
        return (e.text or "").strip() if e is not None and e.text else ""

    nombre = txt(raiz, "reportingOwner/reportingOwnerId/rptOwnerName")
    rel = raiz.find("reportingOwner/reportingOwnerRelationship")
    cargo = ""
    if rel is not None:
        cargo = txt(rel, "officerTitle")
        if not cargo and txt(rel, "isDirector") in ("1", "true"):
            cargo = "Consejero"
        if not cargo and txt(rel, "isTenPercentOwner") in ("1", "true"):
            cargo = "Accionista de más del 10 %"
    compras = ventas = 0.0
    acc_c = acc_v = 0.0
    for t in raiz.findall("nonDerivativeTable/nonDerivativeTransaction"):
        codigo = txt(t, "transactionCoding/transactionCode")
        try:
            acciones = float(txt(t, "transactionAmounts/transactionShares/value") or 0)
            precio = float(txt(t, "transactionAmounts/transactionPricePerShare/value") or 0)
        except ValueError:
            continue
        if codigo == "P":
            compras += acciones * precio
            acc_c += acciones
        elif codigo == "S":
            ventas += acciones * precio
            acc_v += acciones
    if compras == 0 and ventas == 0:
        return None
    return dict(nombre=nombre, cargo=cargo, compras=compras, ventas=ventas, acc_c=acc_c, acc_v=acc_v)


def dinero(v: float) -> str:
    if v >= 1e9:
        return f"${v / 1e9:,.1f} mil millones".replace(",", "X").replace(".", ",").replace("X", ".")
    if v >= 1e6:
        return f"${v / 1e6:,.1f} millones".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"${v:,.0f}".replace(",", ".")


def num_es(v: float, dec: int = 0) -> str:
    return f"{v:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def persona(nombre: str) -> str:
    """'Cook Timothy D' -> 'Timothy D Cook' (formato de la SEC: apellido primero).
    Las empresas y fondos ('Berkshire Hathaway Inc') se dejan en su orden."""
    if re.search(r"\b(inc|corp|corporation|co|llc|lp|l\.p|ltd|plc|trust|fund|holdings|group|partners|capital|management|bank|n\.a)\b\.?", nombre, re.I):
        return nombre.title() if nombre.isupper() else nombre
    partes = nombre.split()
    if len(partes) >= 2:
        return " ".join(partes[1:] + partes[:1]).title()
    return nombre.title()


def alerta_form4(base: dict, f4: dict) -> dict | None:
    e = base["empresa"]
    quien = persona(f4["nombre"]) + (f" ({f4['cargo']})" if f4["cargo"] else "")
    if f4["compras"] >= MIN_COMPRA_DIRECTIVO and f4["compras"] >= f4["ventas"]:
        precio = f4["compras"] / f4["acc_c"] if f4["acc_c"] else 0
        return {**base, "tipo": "int", "sev": "pos", "relevancia": 3 if f4["compras"] >= 1e6 else 2,
                "titulo": f"Un directivo de {e} compró {dinero(f4['compras'])} en acciones",
                "pri": f"{quien} compró acciones de su propia empresa con su dinero. Suele leerse como señal de confianza.",
                "int": f"Compra en mercado abierto (código P): {num_es(f4['acc_c'])} acciones a ~${num_es(precio, 2)}. Firmante: {quien}.",
                "porque": "Los directivos venden por muchas razones, pero compran por una: creen que la acción vale más."}
    if f4["ventas"] >= MIN_VENTA_DIRECTIVO:
        precio = f4["ventas"] / f4["acc_v"] if f4["acc_v"] else 0
        return {**base, "tipo": "int", "sev": "neu", "relevancia": 2 if f4["ventas"] >= 25e6 else 1,
                "titulo": f"Un directivo de {e} vendió {dinero(f4['ventas'])} en acciones",
                "pri": f"{quien} vendió acciones de la empresa. Es común (impuestos, planes programados), así que por sí sola no es mala señal.",
                "int": f"Venta en mercado abierto (código S): {num_es(f4['acc_v'])} acciones a ~${num_es(precio, 2)}. Revisa si es un plan 10b5-1.",
                "porque": "Las ventas de directivos son frecuentes; importan más si varios venden a la vez o si no hay plan programado."}
    return None


# ---------------------------------------------------------------------------
# IA opcional (Anthropic)
# ---------------------------------------------------------------------------
def texto_plano(html: str, limite: int = 14000) -> str:
    html = re.sub(r"(?is)<(script|style|ix:header).*?</\1>", " ", html)
    t = re.sub(r"(?s)<[^>]+>", " ", html)
    t = re.sub(r"&nbsp;|&#160;", " ", t)
    t = re.sub(r"&amp;", "&", t)
    t = re.sub(r"&#\d+;|&\w+;", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:limite]


def anexo_991(cik: int, acc: str) -> str | None:
    """Busca el comunicado de prensa (anexo 99.1) dentro del expediente."""
    try:
        idx = json.loads(http_get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/index.json"))
    except Exception:
        return None
    for it in idx.get("directory", {}).get("item", []):
        n = it.get("name", "").lower()
        if re.search(r"ex[-_]?99[-_.]?1|ex991|dex991", n) and n.endswith((".htm", ".html", ".txt")):
            return url_documento(cik, acc, it["name"])
    return None


PROMPT = """Eres el editor de La Cinta, un medio que explica en español, para inversionistas principiantes e intermedios, lo que las grandes empresas de la bolsa de EE. UU. presentan ante la SEC.

Empresa: {empresa} ({ticker})
Formulario: {form} {items}

Texto del documento (recortado):
<<<
{texto}
>>>

GUÍA DE ESTILO
- Titular: empieza por la empresa o por el hecho, en voz activa y en pasado ("Apple vendió…", "Renuncia el director financiero de…"). Entre 45 y 90 caracteres. Incluye LA cifra más importante si existe. Nada de "anuncia que", "informa sobre", signos de exclamación ni adjetivos como "impresionante" o "histórico".
- Principiante ("pri"): 1 o 2 frases cortas, como se lo explicarías a un amigo que nunca ha invertido. Sin siglas; si debes usar un término técnico, explícalo en la misma frase.
- Intermedio ("int"): 1 o 2 frases densas con las cifras exactas del documento (ingresos, BPA, márgenes, guía, montos, fechas, nombres y cargos). Puedes usar términos como BPA, guía, dilución, 10b5-1.
- "porque": 1 frase concreta sobre qué significa para el accionista. Nada genérico como "es importante para los inversionistas".
- Cifras en formato de EE. UU. en español: $8,42 mil millones; $1,31 por acción; +5,9 %. Cambios contra el mismo periodo del año anterior solo si el texto los da o permite calcularlos.
- Solo hechos del documento. No inventes cifras, no menciones estimados de analistas, no predigas el precio y no recomiendes comprar, vender ni mantener.

EJEMPLOS DE TONO
- titulo: "Nike vendió 10 % menos y retiró su pronóstico para el año"
  pri: "A Nike le fue peor que el año pasado y ya no se atreve a decir cuánto venderá en los próximos meses."
- titulo: "Renuncia el director financiero de Boeing tras 3 años en el cargo"
  pri: "Se va la persona que maneja el dinero de la empresa. Todavía no han dicho quién la reemplazará."
- titulo: "JPMorgan subirá su dividendo 8 %, a $1,25 por acción"
  pri: "El banco pagará un poco más a sus accionistas cada trimestre."

Devuelve SOLO un JSON válido con estas claves:
"titulo", "pri", "int", "porque",
"cifras": lista de 0 a 3 cifras clave cortas (máx. 28 caracteres cada una), p. ej. ["Ingresos $8,42 mil M (+5,9 %)", "BPA $1,31", "Guía Q4 más baja"],
"sev": "pos" | "neg" | "mix" | "neu" (cómo suele interpretarlo el mercado),
"tipo": "res" | "dir" | "dil" | "int" | "deu" | "riesgo" | "rep" | "otros" (recompras y dividendos van en "otros"),
"relevancia": 1 (rutina, casi nunca mueve la acción), 2 (vale la pena saberlo) o 3 (puede mover la acción con fuerza)."""


def explicar_con_ia(alerta: dict, texto: str) -> dict | None:
    cuerpo = json.dumps({
        "model": MODELO,
        "max_tokens": 900,
        "messages": [{"role": "user", "content": PROMPT.format(
            empresa=alerta["empresa"], ticker=alerta["ticker"], form=alerta["form"],
            items=("ítems " + ", ".join(alerta.get("items", []))) if alerta.get("items") else "",
            texto=texto)}],
    }).encode("utf-8")
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=cuerpo, headers={
        "x-api-key": API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read().decode("utf-8"))
        salida = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
        m = re.search(r"\{.*\}", salida, re.S)
        if not m:
            return None
        datos = json.loads(m.group(0))
        limpio = {k: str(datos[k]).strip() for k in ("titulo", "pri", "int", "porque") if datos.get(k)}
        if datos.get("sev") in ("pos", "neg", "mix", "neu"):
            limpio["sev"] = datos["sev"]
        if datos.get("tipo") in ("res", "dir", "dil", "int", "deu", "riesgo", "rep", "otros"):
            limpio["tipo"] = datos["tipo"]
        if isinstance(datos.get("cifras"), list):
            limpio["cifras"] = [str(c).strip()[:40] for c in datos["cifras"] if str(c).strip()][:3]
        if datos.get("relevancia") in (1, 2, 3, "1", "2", "3"):
            limpio["relevancia"] = int(datos["relevancia"])
        return limpio if all(k in limpio for k in ("titulo", "pri", "int", "porque")) else None
    except Exception as e:  # la IA nunca debe tumbar el proceso
        print(f"  IA no disponible para {alerta['id']}: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Construcción de alertas
# ---------------------------------------------------------------------------
def alerta_desde_plantilla(base: dict, items: list[str]) -> dict | None:
    form = base["form"]
    if form == "8-K":
        relevantes = [i for i in PRIORIDAD if i in items]
        if not relevantes:
            return None
        p = ITEMS[relevantes[0]]
    elif form in FORM_PLANTILLAS:
        p = FORM_PLANTILLAS[form]
    else:
        return None
    return {**base, "items": items, "tipo": p["tipo"], "sev": p["sev"], "relevancia": relevancia_base(p),
            "titulo": p["t"].format(e=base["empresa"]), "pri": p["pri"], "int": p["int"], "porque": p["por"]}


def relevancia_base(p: dict) -> int:
    if p["tipo"] in ("riesgo", "res") or p["sev"] == "neg":
        return 3
    return 1 if p["sev"] == "neu" else 2


def procesar_empresa(ticker: str, info: dict, vistos: set[str], limite: datetime, nombre: str = "") -> list[dict]:
    cik = info["cik"]
    datos = json.loads(http_get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json"))
    empresa = nombre or nombre_bonito(datos.get("name") or info["nombre"])
    r = datos.get("filings", {}).get("recent", {})
    nuevas = []
    for i, form in enumerate(r.get("form", [])):
        if form not in FORMULARIOS:
            continue
        acc = r["accessionNumber"][i]
        if acc in vistos:
            continue
        fecha = fecha_aceptacion(r.get("acceptanceDateTime", [""] * (i + 1))[i], r["filingDate"][i])
        if datetime.strptime(fecha, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) < limite:
            continue
        doc = r.get("primaryDocument", [""] * (i + 1))[i]
        items = [x.strip() for x in (r.get("items", [""] * (i + 1))[i] or "").split(",") if x.strip()]
        base = {"id": acc, "ticker": ticker, "empresa": empresa, "form": form, "fecha": fecha,
                "url": url_indice(cik, acc), "doc": url_documento(cik, acc, doc) if doc else url_indice(cik, acc),
                "ia": False}
        if form == "4":
            if not doc:
                continue
            xml_doc = re.sub(r"^xslF345X\d+/", "", doc)  # el documento crudo, sin la hoja de estilo
            try:
                f4 = analizar_form4(http_get(url_documento(cik, acc, xml_doc)))
            except Exception:
                f4 = None
            a = alerta_form4({**base, "items": []}, f4) if f4 else None
        else:
            a = alerta_desde_plantilla(base, items)
        vistos.add(acc)  # procesado (aunque no genere alerta), para no repetirlo
        if a:
            nuevas.append(a)
    return nuevas


def enriquecer_con_ia(alertas: list[dict]) -> None:
    if not API_KEY:
        return
    hechas = 0
    for a in alertas:
        if hechas >= MAX_IA_POR_CORRIDA:
            break
        if a["form"] not in ("8-K", "424B5", "SC 13D", "SCHEDULE 13D"):
            continue  # Form 4 ya trae cifras; 10-Q/10-K son muy largos para esta versión
        try:
            m = re.match(r"https://www\.sec\.gov/Archives/edgar/data/(\d+)/", a["url"])
            fuente = anexo_991(int(m.group(1)), a["id"]) if (m and "2.02" in a.get("items", [])) else None
            texto = texto_plano(http_get(fuente or a["doc"]))
            if fuente:  # añade también el 8-K por contexto
                texto = texto[:11000] + " … " + texto_plano(http_get(a["doc"]), 3000)
        except Exception as e:
            print(f"  No se pudo leer {a['doc']}: {e}", file=sys.stderr)
            continue
        extra = explicar_con_ia(a, texto)
        hechas += 1
        if extra:
            a.update(extra)
            a["ia"] = True



# ---------------------------------------------------------------------------
# Telegram (opcional)
# ---------------------------------------------------------------------------
def _h(t: str) -> str:
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def mensaje_telegram(a: dict) -> str:
    punto = {"pos": "🟢", "neg": "🔴", "mix": "🟡"}.get(a.get("sev"), "⚪")
    lineas = [f"{punto} <b>{_h(a['ticker'])}</b> · {_h(a['titulo'])}", "", _h(a["pri"])]
    if a.get("cifras"):
        lineas += ["", " · ".join(_h(c) for c in a["cifras"])]
    lineas += ["", f"<i>Por qué importa:</i> {_h(a['porque'])}", ""]
    enlaces = [f'<a href="{_h(a.get("doc") or a["url"])}">Documento en la SEC</a>']
    if SITIO_URL:
        enlaces.append(f'<a href="{_h(SITIO_URL)}/?t={_h(a["ticker"])}#buscar">Ver en La Cinta</a>')
    lineas.append(" | ".join(enlaces))
    return "\n".join(lineas)


def enviar_telegram(alertas: list[dict]) -> int:
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT):
        return 0
    limite = datetime.now(timezone.utc) - timedelta(hours=TELEGRAM_HORAS_MAX)
    candidatas = [a for a in alertas
                  if a.get("relevancia", 2) >= TELEGRAM_MIN_RELEVANCIA
                  and datetime.strptime(a["fecha"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) >= limite]
    candidatas = sorted(candidatas, key=lambda a: a["fecha"])[-TELEGRAM_MAX_POR_CORRIDA:]  # en orden cronológico
    enviados = 0
    for a in candidatas:
        cuerpo = json.dumps({"chat_id": TELEGRAM_CHAT, "text": mensaje_telegram(a), "parse_mode": "HTML",
                             "disable_web_page_preview": True}).encode("utf-8")
        for intento in range(3):
            req = urllib.request.Request(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                                         data=cuerpo, headers={"content-type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    json.loads(r.read().decode("utf-8"))
                enviados += 1
                a["telegram"] = True
                break
            except urllib.error.HTTPError as e:
                if e.code == 429 and intento < 2:  # Telegram pide esperar
                    try:
                        espera = json.loads(e.read().decode("utf-8")).get("parameters", {}).get("retry_after", 5)
                    except Exception:
                        espera = 5
                    time.sleep(min(int(espera) + 1, 60))
                    continue
                print(f"  Telegram rechazó {a['id']}: {e.code} {e.read()[:200]!r}", file=sys.stderr)
                break
            except Exception as e:
                print(f"  Telegram no disponible: {e}", file=sys.stderr)
                return enviados
        time.sleep(3.1)  # los canales admiten ~20 mensajes por minuto
    if enviados:
        print(f"{enviados} alertas enviadas a Telegram")
    return enviados


def cargar_estado() -> dict:
    if ARCHIVO_SALIDA.exists():
        try:
            return json.loads(ARCHIVO_SALIDA.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"alertas": [], "vistos": []}


def guardar(estado: dict) -> None:
    ARCHIVO_SALIDA.parent.mkdir(parents=True, exist_ok=True)
    tmp = ARCHIVO_SALIDA.with_suffix(".tmp")
    tmp.write_text(json.dumps(estado, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ARCHIVO_SALIDA)


def una_corrida() -> int:
    estado = cargar_estado()
    vistos = set(estado.get("vistos", []))
    limite = datetime.now(timezone.utc) - timedelta(days=DIAS_ATRAS)
    mapa = mapa_tickers()
    nuevas: list[dict] = []
    for t, nombre in leer_empresas():
        info = mapa.get(t) or mapa.get(t.replace(".", "-"))
        if not info:
            print(f"  {t}: no encontrado en la SEC (revisa el símbolo)", file=sys.stderr)
            continue
        try:
            nuevas.extend(procesar_empresa(t, info, vistos, limite, nombre))
        except Exception as e:
            print(f"  {t}: error {e}", file=sys.stderr)
    nuevas.sort(key=lambda a: a["fecha"], reverse=True)
    # Si no hay nada nuevo, no reescribir el archivo (evita un commit cada 10 min),
    # salvo una vez por hora para que el sitio muestre la hora de revisión.
    previo = estado.get("actualizado")
    if not nuevas and set(estado.get("vistos", [])) == vistos and previo:
        try:
            edad = datetime.now(timezone.utc) - datetime.strptime(previo, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if edad < timedelta(minutes=60):
                print("Sin novedades")
                return 0
        except ValueError:
            pass
    enriquecer_con_ia(nuevas)
    enviar_telegram(nuevas)
    alertas = sorted(nuevas + estado.get("alertas", []), key=lambda a: a["fecha"], reverse=True)[:MAX_ALERTAS]
    estado = {
        "actualizado": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "alertas": alertas,
        "vistos": sorted(vistos)[-5000:],
    }
    guardar(estado)
    print(f"{len(nuevas)} alertas nuevas · {len(alertas)} en total")
    return len(nuevas)


def main() -> None:
    ap = argparse.ArgumentParser(description="Lee EDGAR y genera data/alertas.json")
    ap.add_argument("--loop", type=int, default=0, help="repetir cada N segundos (0 = una sola vez)")
    args = ap.parse_args()
    if "@" not in USER_AGENT:
        sys.exit("Falta SEC_USER_AGENT con un correo de contacto, p. ej.: \"La Cinta tu-correo@ejemplo.com\"")
    while True:
        una_corrida()
        if not args.loop:
            break
        time.sleep(max(30, args.loop))


if __name__ == "__main__":
    main()
