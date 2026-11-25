"""앱 아이콘 생성 — 보라/인디고 톤 말풍선

    python3 projects/sms-helper/assets/make_icons.py

projects/sms-helper/icons/ 아래에 512·192·180·maskable 512 를 만든다.
"""
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'icons')

SS = 4  # 슈퍼샘플링 배수


def lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def draw_icon(size, bubble_scale=1.0, radius_ratio=0.0):
    """정사각 배경 + 흰 말풍선(점 3개). radius_ratio>0 이면 모서리를 둥글게 깎는다."""
    n = size * SS
    img = Image.new('RGBA', (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 배경: 위쪽 밝은 인디고 → 아래쪽 짙은 인디고
    top, bottom = (99, 102, 241), (67, 56, 202)
    band = max(1, n // 128)
    for y in range(0, n, band):
        d.rectangle([0, y, n, y + band], fill=lerp(top, bottom, y / max(1, n - 1)))

    # 말풍선 (가운데 기준)
    cx, cy = n / 2, n / 2
    bw = n * 0.62 * bubble_scale
    bh = n * 0.47 * bubble_scale
    l, r = cx - bw / 2, cx + bw / 2
    t, b = cy - bh / 2 - n * 0.02 * bubble_scale, cy + bh / 2 - n * 0.02 * bubble_scale
    rad = bh * 0.34
    d.rounded_rectangle([l, t, r, b], radius=rad, fill=(255, 255, 255, 255))

    # 꼬리 (왼쪽 아래)
    tail_x = l + bw * 0.26
    d.polygon([
        (tail_x, b - rad * 0.35),
        (tail_x + bw * 0.21, b - rad * 0.35),
        (tail_x - bw * 0.055, b + n * 0.115 * bubble_scale),
    ], fill=(255, 255, 255, 255))

    # 점 3개
    dot_r = n * 0.038 * bubble_scale
    gap = n * 0.095 * bubble_scale
    dot_y = cy - n * 0.02 * bubble_scale
    for k in (-1, 0, 1):
        x = cx + k * gap
        d.ellipse([x - dot_r, dot_y - dot_r, x + dot_r, dot_y + dot_r], fill=(79, 70, 229, 255))

    if radius_ratio:
        mask = Image.new('L', (n, n), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, n, n], radius=int(n * radius_ratio), fill=255)
        img.putalpha(mask)

    return img.resize((size, size), Image.LANCZOS)


def main():
    os.makedirs(OUT, exist_ok=True)
    jobs = [
        ('icon-512.png', 512, 1.0, 0.0),
        ('icon-192.png', 192, 1.0, 0.0),
        ('icon-180.png', 180, 1.0, 0.0),
        # maskable: 안전 영역(가운데 80%) 안에 들어오도록 작게, 배경은 꽉 차게
        ('icon-maskable-512.png', 512, 0.78, 0.0),
    ]
    for name, size, scale, radius in jobs:
        img = draw_icon(size, scale, radius)
        path = os.path.join(OUT, name)
        img.save(path, 'PNG', optimize=True)
        print(path, os.path.getsize(path), 'bytes')


if __name__ == '__main__':
    main()
