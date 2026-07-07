/**
 * 板块颜色统一配置
 * 每个板块名对应一个固定 HSL 色相，保证同一板块在页面各处颜色一致。
 * 流入/上涨用较高饱和度，流出/下跌用较低亮度但仍保持可识别色相。
 */

const BASE_SATURATION = 70;
const BASE_LIGHTNESS = 55;

export function getSectorHue(sector) {
  if (!sector) return 0;
  let hash = 0;
  for (let i = 0; i < sector.length; i++) {
    hash = (hash << 5) - hash + sector.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash) % 360;
}

export function getSectorColor(sector, variant = 'base') {
  const hue = getSectorHue(sector);
  switch (variant) {
    case 'inflow':
      return `hsl(${hue}, ${BASE_SATURATION}%, 52%)`;
    case 'outflow':
      return `hsl(${hue}, ${BASE_SATURATION - 10}%, 42%)`;
    case 'dim':
      return `hsl(${hue}, ${BASE_SATURATION}%, 70%)`;
    default:
      return `hsl(${hue}, ${BASE_SATURATION}%, ${BASE_LIGHTNESS}%)`;
  }
}

export function getSectorColorHex(sector, variant = 'base') {
  return hslToHex(getSectorColor(sector, variant));
}

function hslToHex(hsl) {
  const match = hsl.match(/hsl\((\d+),\s*(\d+)%,\s*(\d+)%\)/);
  if (!match) return hsl;
  const h = parseInt(match[1], 10) / 360;
  const s = parseInt(match[2], 10) / 100;
  const l = parseInt(match[3], 10) / 100;

  const hue2rgb = (p, q, t) => {
    if (t < 0) t += 1;
    if (t > 1) t -= 1;
    if (t < 1 / 6) return p + (q - p) * 6 * t;
    if (t < 1 / 2) return q;
    if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
    return p;
  };

  let r, g, b;
  if (s === 0) {
    r = g = b = l;
  } else {
    const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
    const p = 2 * l - q;
    r = hue2rgb(p, q, h + 1 / 3);
    g = hue2rgb(p, q, h);
    b = hue2rgb(p, q, h - 1 / 3);
  }

  const toHex = (c) => {
    const hex = Math.round(c * 255).toString(16);
    return hex.length === 1 ? '0' + hex : hex;
  };
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
}
