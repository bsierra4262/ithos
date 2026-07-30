#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Genera el LOGO de ITHOS (icono + imágenes del instalador) IGUAL al reactor de la web
(comun/estilo_ithos.py .reactor): ticks exteriores + anillo + anillo interior segmentado (4 arcos) +
núcleo brillante, cian sobre fondo oscuro. Uso: python build/hacer_icono.py"""
import os
import math
from PIL import Image, ImageDraw, ImageFilter

BASE = os.path.dirname(os.path.abspath(__file__))
BG = (3, 6, 13)                # #03060d  (mismo fondo que la web)
CY = (47, 227, 255)            # #2fe3ff  (cian de marca)
CY_SOFT = (47, 227, 255, 110)


def _reactor(d, cx, cy, R):
    """Reactor ITHOS (igual que el .reactor CSS de la web)."""
    # ticks exteriores (como una regla) cada 9°
    r_out, r_in = R * 0.99, R * 0.84
    tw = max(1, int(R * 0.035))
    for a in range(0, 360, 9):
        rad = math.radians(a)
        d.line([cx + r_out * math.cos(rad), cy + r_out * math.sin(rad),
                cx + r_in * math.cos(rad), cy + r_in * math.sin(rad)], fill=CY, width=tw)
    # anillo exterior fino
    d.ellipse([cx - R * 0.78, cy - R * 0.78, cx + R * 0.78, cy + R * 0.78],
              outline=CY, width=max(1, int(R * 0.045)))
    # anillo INTERIOR segmentado (4 arcos) + borde fino
    ri = R * 0.50
    bbox = [cx - ri, cy - ri, cx + ri, cy + ri]
    aw = max(2, int(R * 0.11))
    for s in (8, 98, 188, 278):
        d.arc(bbox, s, s + 54, fill=CY, width=aw)
    d.ellipse(bbox, outline=(47, 227, 255), width=max(1, int(R * 0.02)))
    # núcleo brillante
    rc = R * 0.19
    d.ellipse([cx - rc, cy - rc, cx + rc, cy + rc], fill=CY)


def _icono(size=256):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = size * 0.05
    d.rounded_rectangle([m, m, size - m, size - m], radius=size * 0.23, fill=BG + (255,),
                        outline=(45, 224, 255, 60), width=max(1, size // 80))
    # glow: reactor en una capa aparte, desenfocada, por debajo
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    _reactor(ImageDraw.Draw(glow), size / 2, size / 2, size * 0.34)
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(size * 0.03)))
    _reactor(d, size / 2, size / 2, size * 0.34)
    return img


def _fuente(tam):
    from PIL import ImageFont
    for f in ("Orbitron-Bold.ttf", "arialbd.ttf", "seguisb.ttf", "segoeui.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(f, tam)
        except OSError:
            continue
    return ImageFont.load_default()


def _centrado(d, cx, y, txt, fuente, fill, sp=0):
    try:
        x0, _, x1, _ = d.textbbox((0, 0), txt, font=fuente)
        d.text((cx - (x1 - x0) / 2, y), txt, font=fuente, fill=fill)
    except Exception:  # noqa: BLE001
        d.text((cx, y), txt, font=fuente, fill=fill)


def _wizard(w, h, grande=True):
    """Imagen del asistente de instalación (BMP): fondo oscuro + reactor + wordmark ITHOS."""
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    cx = w / 2
    if grande:
        # glow + reactor arriba, wordmark abajo (banner vertical del wizard)
        R = w * 0.30
        glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        _reactor(ImageDraw.Draw(glow), cx, h * 0.28, R)
        img.paste(Image.alpha_composite(img.convert("RGBA"),
                  glow.filter(ImageFilter.GaussianBlur(w * 0.02))).convert("RGB"), (0, 0))
        d = ImageDraw.Draw(img)
        _reactor(d, cx, h * 0.28, R)
        _centrado(d, cx, h * 0.50, "ITHOS", _fuente(int(w * 0.24)), CY)
        _centrado(d, cx, h * 0.63, "Agente", _fuente(int(w * 0.10)), (150, 190, 220))
        _centrado(d, cx, h * 0.90, "INTELLIHELP S.A.", _fuente(int(w * 0.065)), (95, 127, 156))
    else:
        _reactor(d, cx, h * 0.5, h * 0.36)
    return img


def main():
    base = _icono(256)
    tam = [16, 24, 32, 48, 64, 128, 256]
    base.save(os.path.join(BASE, "ithos.ico"), sizes=[(s, s) for s in tam])
    base.save(os.path.join(BASE, "ithos.png"))
    try:
        base.save(os.path.join(BASE, "ithos.icns"))   # macOS (best-effort)
    except Exception:  # noqa: BLE001
        pass
    _wizard(164, 314, grande=True).save(os.path.join(BASE, "ithos_wizard.bmp"))
    _wizard(55, 58, grande=False).save(os.path.join(BASE, "ithos_wizard_small.bmp"))
    print("Logo ITHOS (icono + wizard) generado en", BASE)


if __name__ == "__main__":
    main()
