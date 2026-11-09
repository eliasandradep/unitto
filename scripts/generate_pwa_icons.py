"""Gera os ícones do PWA a partir de static/images/logo.png.

Roda uma única vez (ou sempre que o logo mudar) para produzir os PNGs em
static/images/icons/. Não é uma dependência de runtime da aplicação.
"""
from PIL import Image

SRC = 'static/images/logo.png'
OUT_DIR = 'static/images/icons'
BG = (27, 45, 110, 255)  # --sidebar-bg

# Bbox do símbolo "U" (sem o texto "Unitto" / "Gestão Unificada" abaixo).
MARK_BBOX = (56, 49, 964, 814)


def build_icon(mark, size, scale, out_path, opaque=True):
    canvas = Image.new('RGBA', (size, size), BG if opaque else (0, 0, 0, 0))
    target_w = int(size * scale)
    ratio = target_w / mark.width
    target_h = int(mark.height * ratio)
    resized = mark.resize((target_w, target_h), Image.LANCZOS)
    x = (size - target_w) // 2
    y = (size - target_h) // 2
    canvas.alpha_composite(resized, (x, y))
    canvas.save(out_path)
    print('wrote', out_path, canvas.size)


def main():
    import os
    os.makedirs(OUT_DIR, exist_ok=True)
    logo = Image.open(SRC)
    mark = logo.crop(MARK_BBOX)

    # Ícones "any": preenchem quase todo o canvas, fundo navy da marca.
    build_icon(mark, 192, 0.72, f'{OUT_DIR}/icon-192.png')
    build_icon(mark, 512, 0.72, f'{OUT_DIR}/icon-512.png')

    # Ícones "maskable": símbolo cabe na safe-zone central (~80%) de qualquer
    # máscara (círculo, squircle...) que o SO aplicar por cima.
    build_icon(mark, 192, 0.56, f'{OUT_DIR}/icon-maskable-192.png')
    build_icon(mark, 512, 0.56, f'{OUT_DIR}/icon-maskable-512.png')

    # apple-touch-icon: iOS não respeita transparência, então precisa de
    # fundo opaco preenchendo o quadrado (o próprio iOS arredonda os cantos).
    build_icon(mark, 180, 0.72, 'static/images/apple-touch-icon.png')

    # Favicon simples (opaco, fundo navy) para a aba do navegador.
    build_icon(mark, 32, 0.8, 'static/images/favicon-32.png')
    build_icon(mark, 64, 0.8, 'static/images/favicon-64.png')


if __name__ == '__main__':
    main()
