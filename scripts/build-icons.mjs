// Raster variants of the existing vector app icon, with maskable-safe padding.
import sharp from "sharp";
import { mkdir, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
const root = new URL("../", import.meta.url);
await mkdir(new URL("static/icons/", root), { recursive: true });
const svg = await readFile(new URL("static/icon.svg", root));
for (const [name, size] of [
  ["icon-192.png", 192],
  ["icon-512.png", 512],
  ["apple-touch-icon.png", 180],
]) {
  const padding = Math.round(size * 0.11);
  const logo = await sharp(svg)
    .resize(size - 2 * padding, size - 2 * padding)
    .png()
    .toBuffer();
  await sharp({
    create: { width: size, height: size, channels: 4, background: "#0c0d12" },
  })
    .composite([{ input: logo, top: padding, left: padding }])
    .png()
    .toFile(
      fileURLToPath(new URL(`static/icons/${name}`, root)),
    );
}
