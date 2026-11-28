"""앱 아이콘 생성 — 핑크 유리 말풍선 아이콘 하나로 웹·PWA·iOS·안드로이드·윈도우 아이콘을 모두 만든다.

쓰는 법
    python3 assets/make_icons.py
        커밋해 둔 `assets/icon-source.png`(투명 1024)로 모든 아이콘을 다시 만든다.

    python3 assets/make_icons.py --raw ~/downloads/pink-glass-chat-icon.png
        새 원본 PNG(순백 배경)에서 배경을 투명하게 따고 master 를 새로 만든 뒤 전부 다시 만든다.

원본에서 배경을 따는 방법 (순백 배경 → 투명)
    · 물체는 핑크색(채도 있음), 그림자는 무채색 회색이라 `채도` 로 둘을 가른다.
    · 테두리에서 이어진 아주 밝은 픽셀만 '바깥' 으로 보고 물체 안쪽(흰 점 3개·하이라이트)은 건드리지 않는다.
    · 테두리 픽셀은 주변 물체 색을 기준으로 덮인 비율(알파)을 계산해 안티앨리어싱을 살리고,
      흰색이 섞인 색을 되돌려(unmultiply) 흰 테두리가 남지 않게 한다.

만드는 파일
    icons/icon-512.png · icon-maskable-512.png · icon-192.png   웹 파비콘·PWA (투명)
    icons/icon-180.png                                          iOS 홈 화면 (흰 배경)
    icons/favicon.ico                                           브라우저 탭 (16·32·48)
    desktop/assets/icon.ico                                     윈도우 위젯 exe·설치판·바로가기
    android/.../mipmap-xxxhdpi/ic_launcher.png                  안드로이드 (흰 배경 432)
    android/.../mipmap-xxxhdpi/ic_launcher_round.png            둥근 런처용 (흰 원 432)
    android/.../mipmap-xxxhdpi/ic_launcher_foreground.png       adaptive icon 앞면 (투명 432)
    android/.../mipmap-anydpi-v26/ic_launcher*.xml              adaptive icon 정의
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                      # projects/sms-helper
DOWNLOADS = os.path.dirname(os.path.dirname(ROOT)) + "/downloads"
MASTER = os.path.join(HERE, "icon-source.png")
WHITE = (255, 255, 255, 255)
CLEAR = (0, 0, 0, 0)


# --------------------------------------------------------------------------- 배경 따기
def _box_sum(a, r):
    """(2r+1)² 창 합 — 적분 이미지로 한 번에 계산한다."""
    p = np.pad(a, ((r + 1, r), (r + 1, r)) + ((0, 0),) * (a.ndim - 2), mode="constant")
    c = p.cumsum(0).cumsum(1)
    h, w = a.shape[:2]
    k = 2 * r + 1
    return c[k:k + h, k:k + w] - c[0:h, k:k + w] - c[k:k + h, 0:w] + c[0:h, 0:w]


def cut_out_white(img, bg_L=245, bg_chroma=10, band=4, ref_r=6, neutral=12):
    """순백 배경을 투명하게 딴 RGBA 를 돌려준다.

    bg_L·bg_chroma: 이보다 밝고 무채색인 픽셀을 '배경 후보' 로 본다.
    neutral: 채도가 이보다 낮은 픽셀(그림자·배경)은 알파 0.
    """
    rgb = np.asarray(img.convert("RGB")).astype(np.float32)
    lum = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    chroma = rgb.max(2) - rgb.min(2)

    bglike = (lum >= bg_L) & (chroma <= bg_chroma)
    mask = Image.fromarray((bglike * 255).astype(np.uint8), "L").copy()
    ImageDraw.floodfill(mask, (0, 0), 128, thresh=0)
    outside = np.asarray(mask) == 128              # 테두리에서 이어진 배경

    grown = outside.copy()
    for _ in range(band):
        p = np.pad(grown, 1, constant_values=False)
        grown = (p[1:-1, 1:-1] | p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:])
    core = ~grown                                   # 확실히 물체 안쪽 (흰 점·하이라이트 포함)

    # 테두리 픽셀이 덮인 비율을 재려면 '바로 옆 물체 색' 이 필요하다
    count = _box_sum(core.astype(np.float32), ref_r)
    total = _box_sum(rgb * core[..., None], ref_r)
    ref = np.where(count[..., None] > 0,
                   total / np.maximum(count, 1e-6)[..., None],
                   rgb.reshape(-1, 3).mean(0))

    # C = a·F + (1-a)·254  →  a = (254-C)/(254-F). 대비가 가장 큰 채널로 계산한다.
    den = 254.0 - ref
    pick = np.argmax(den, axis=2)[..., None]
    a_loc = np.clip((np.take_along_axis(254.0 - rgb, pick, axis=2)[..., 0]
                     / np.maximum(np.take_along_axis(den, pick, axis=2)[..., 0], 1e-3)), 0.0, 1.0)

    alpha = np.where(chroma < neutral, 0.0, a_loc)
    alpha[core] = 1.0

    out = np.zeros((*lum.shape, 4), np.float32)
    out[..., :3] = np.where(core[..., None], rgb, ref)   # 테두리는 주변 물체 색으로 — 흰 테두리 제거
    out[..., 3] = alpha * 255.0
    return Image.fromarray(out.round().astype(np.uint8), "RGBA")


def build_master(raw_path, transparent_out=None):
    """원본 PNG → (투명 전체 해상도) + (물체가 캔버스를 꽉 채운 정사각 1024 master)."""
    im = Image.open(raw_path)
    cut = cut_out_white(im)
    if transparent_out:
        os.makedirs(os.path.dirname(transparent_out), exist_ok=True)
        cut.save(transparent_out, "PNG", optimize=True)
        print("transparent", transparent_out)

    box = cut.getbbox() or (0, 0, cut.width, cut.height)
    alpha = np.asarray(cut)[..., 3]
    ys, xs = np.where(alpha > 8)
    box = (max(0, xs.min() - 2), max(0, ys.min() - 2),
           min(cut.width, xs.max() + 3), min(cut.height, ys.max() + 3))
    art = cut.crop(box)
    side = max(art.size)
    square = Image.new("RGBA", (side, side), CLEAR)
    square.paste(art, ((side - art.width) // 2, (side - art.height) // 2))
    master = square.resize((1024, 1024), Image.LANCZOS)
    master.save(MASTER, "PNG", optimize=True)
    print("master", MASTER, master.size)
    return master


# --------------------------------------------------------------------------- 아이콘 그리기
def render(art, size, ratio, bg=CLEAR, shape="square"):
    """art(정사각 master)를 size 캔버스 안에 ratio 만큼 넣는다. bg 가 있으면 배경을 깐다."""
    canvas = Image.new("RGBA", (size, size), bg)
    inner = max(1, int(round(size * ratio)))
    pic = art.resize((inner, inner), Image.LANCZOS)
    xy = ((size - inner) // 2, (size - inner) // 2)

    if shape in ("circle", "rounded"):
        mask = Image.new("L", (size, size), 0)
        d = ImageDraw.Draw(mask)
        if shape == "circle":
            d.ellipse([0, 0, size - 1, size - 1], fill=255)
        else:
            d.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(size * 0.22), fill=255)
        canvas.putalpha(mask)

    canvas.alpha_composite(pic, xy)
    return canvas


def save_ico(art, path, sizes, ratio):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    frames = [render(art, s, ratio) for s in sizes]
    big = frames[-1]
    big.save(path, format="ICO", sizes=[(s, s) for s in sizes])
    print("ico", path, sizes)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", help="원본 PNG(순백 배경). 주면 master 를 새로 만든다")
    ap.add_argument("--transparent-out", default=os.path.join(DOWNLOADS, "pink-glass-chat-icon-transparent.png"),
                    help="투명 처리한 전체 해상도 PNG 저장 경로")
    args = ap.parse_args(argv)

    if args.raw:
        art = build_master(args.raw, args.transparent_out)
    else:
        art = Image.open(MASTER).convert("RGBA")

    icons = os.path.join(ROOT, "icons")
    os.makedirs(icons, exist_ok=True)

    jobs = [
        (os.path.join(icons, "icon-512.png"), 512, 0.86, CLEAR, "square"),
        (os.path.join(icons, "icon-192.png"), 192, 0.86, CLEAR, "square"),
        (os.path.join(icons, "icon-180.png"), 180, 0.80, WHITE, "square"),   # iOS 홈 화면 — 흰 배경
        (os.path.join(icons, "icon-maskable-512.png"), 512, 0.62, WHITE, "square"),
    ]
    for path, size, ratio, bg, shape in jobs:
        render(art, size, ratio, bg, shape).save(path, "PNG", optimize=True)
        print("png", path, os.path.getsize(path))

    save_ico(art, os.path.join(icons, "favicon.ico"), [16, 32, 48], 0.98)
    save_ico(art, os.path.join(ROOT, "desktop", "assets", "icon.ico"),
             [16, 24, 32, 48, 64, 128, 256], 0.94)

    res = os.path.join(ROOT, "android", "app", "src", "main", "res")
    android = [
        (os.path.join(res, "mipmap-xxxhdpi", "ic_launcher.png"), 432, 0.72, WHITE, "square"),
        (os.path.join(res, "mipmap-xxxhdpi", "ic_launcher_round.png"), 432, 0.62, WHITE, "circle"),
        (os.path.join(res, "mipmap-xxxhdpi", "ic_launcher_foreground.png"), 432, 0.60, CLEAR, "square"),
    ]
    for path, size, ratio, bg, shape in android:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        render(art, size, ratio, bg, shape).save(path, "PNG", optimize=True)
        print("png", path, os.path.getsize(path))

    anydpi = os.path.join(res, "mipmap-anydpi-v26")
    os.makedirs(anydpi, exist_ok=True)
    template = ('<?xml version="1.0" encoding="utf-8"?>\n'
                '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
                '    <background android:drawable="@color/ic_launcher_background" />\n'
                '    <foreground android:drawable="@mipmap/ic_launcher_foreground" />\n'
                '</adaptive-icon>\n')
    for name in ("ic_launcher.xml", "ic_launcher_round.xml"):
        with open(os.path.join(anydpi, name), "w", encoding="utf-8") as fp:
            fp.write(template)
        print("xml", os.path.join(anydpi, name))

    colors = os.path.join(res, "values", "colors.xml")
    with open(colors, "w", encoding="utf-8") as fp:
        fp.write('<?xml version="1.0" encoding="utf-8"?>\n'
                 '<resources>\n'
                 '    <color name="ic_launcher_background">#FFFFFF</color>\n'
                 '</resources>\n')
    print("xml", colors)
    return 0


if __name__ == "__main__":
    sys.exit(main())
