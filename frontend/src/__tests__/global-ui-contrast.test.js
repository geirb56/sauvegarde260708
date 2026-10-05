import fs from "fs";
import path from "path";

const read = (file) => fs.readFileSync(path.join(__dirname, "..", file), "utf8");
const base = read("index.css");
const modern = read("styles/theme-modern.css");
const declarations = Object.fromEntries(
  [...`${base}\n${modern}`.matchAll(/(--[\w-]+):\s*([^;]+);/g)]
    .map(([, name, value]) => [name, value.trim()]),
);

function resolve(value) {
  return value.replace(/var\((--[\w-]+)\)/g, (_, name) => resolve(declarations[name]));
}

function rgb(value) {
  const color = resolve(value);
  if (color.startsWith("#")) {
    return [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16) / 255);
  }
  const [h, s, l] = color.replace(/hsl\(|\)|%/g, "").split(/\s+/).map(Number);
  const saturation = s / 100;
  const lightness = l / 100;
  const a = saturation * Math.min(lightness, 1 - lightness);
  return [0, 8, 4].map((n) => {
    const k = (n + h / 30) % 12;
    return lightness - a * Math.max(-1, Math.min(k - 3, 9 - k, 1));
  });
}

function luminance(color) {
  return rgb(color)
    .map((v) => v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)
    .reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i], 0);
}

function contrast(a, b) {
  const values = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (values[0] + 0.05) / (values[1] + 0.05);
}

describe("canonical RunIndex text contrast (not a complete WCAG audit)", () => {
  const text = ["--foreground", "--secondary-foreground", "--muted-foreground"];
  const surfaces = ["--background", "--card", "--popover", "--muted", "--secondary", "--accent",
    "--bg-secondary", "--bg-card-hover"];

  test.each(text.flatMap((foreground) => surfaces.map((background) => [foreground, background])))(
    "%s on %s meets AA for normal text",
    (foreground, background) => {
      expect(contrast(declarations[foreground], declarations[background])).toBeGreaterThanOrEqual(4.5);
    },
  );

  test.each([
    ["--text-primary", "--foreground"],
    ["--text-secondary", "--secondary-foreground"],
    ["--text-tertiary", "--muted-foreground"],
    ["--bg-primary", "--background"],
    ["--bg-card", "--card"],
    ["--border-color", "--border"],
    ["--border-color-light", "--border-strong"],
  ])("%s aliases %s rather than defining a competing palette", (legacy, canonical) => {
    expect(declarations[legacy]).toBe(`hsl(var(${canonical}))`);
  });

  test("keeps a distinct, ordered text hierarchy", () => {
    expect(luminance(declarations["--foreground"])).toBeGreaterThan(luminance(declarations["--secondary-foreground"]));
    expect(luminance(declarations["--secondary-foreground"])).toBeGreaterThan(luminance(declarations["--muted-foreground"]));
  });

  test.each([
    ["--primary-foreground", "--primary"],
    ["--destructive-foreground", "--destructive"],
    ["--status-danger", "--card"],
    ["--status-warning", "--card"],
    ["--status-success", "--card"],
    ["--status-info", "--card"],
    ["--accent-violet-light", "--card"],
  ])("semantic text %s on %s remains readable", (foreground, background) => {
    expect(contrast(declarations[foreground], declarations[background])).toBeGreaterThanOrEqual(4.5);
  });

  test("warning text remains AA on the composited goal/confidence badge surface", () => {
    // Measured goal card + orange badge background from the mobile fixture.
    expect(contrast(declarations["--status-warning"], "#4d3028")).toBeGreaterThanOrEqual(4.5);
  });

  test("mobile navigation never reduces labels below 11px", () => {
    const sizes = [...modern.matchAll(/\.nav-item-modern \.nav-label\s*\{[^}]*font-size:\s*([\d.]+)rem/g)];
    expect(sizes).toHaveLength(2);
    sizes.forEach(([, size]) => expect(Number(size) * 16).toBeGreaterThanOrEqual(11));
  });

  test.each(["input", "textarea", "select", "button", "label"])(
    "%s distinguishes disabled text without fading the entire control",
    (component) => {
      const source = read(`components/ui/${component}.jsx`);
      expect(source).not.toMatch(/(?:disabled|peer-disabled|data-\[disabled\]):opacity-/);
      expect(source).toContain("disabled:text-muted-foreground");
    },
  );
});
