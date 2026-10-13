import { formatPace } from "./units";

describe("formatPace", () => {
  test("keeps an ordinary metric pace unchanged", () => {
    expect(formatPace(308, { unitSystem: "metric" })).toBe("5:08 /km");
  });

  test("rolls metric pace to the next minute when rounded seconds reach 60", () => {
    const result = formatPace(299.5, { unitSystem: "metric" });

    expect(result).toBe("5:00 /km");
    expect(result).not.toContain(":60");
  });

  test("formats an exact whole-minute metric pace", () => {
    expect(formatPace(300, { unitSystem: "metric" })).toBe("5:00 /km");
  });

  test("keeps a metric pace below the rollover boundary at 4:59", () => {
    expect(formatPace(299.4, { unitSystem: "metric" })).toBe("4:59 /km");
  });

  test("rolls imperial pace to the next minute when converted rounded seconds reach 60", () => {
    const result = formatPace(299.5 / 1.60934, { unitSystem: "imperial" });

    expect(result).toBe("5:00 /mi");
    expect(result).not.toContain(":60 /mi");
  });

  test.each([null, undefined, NaN, 0, -1])("preserves invalid or missing input behavior for %p", (value) => {
    expect(formatPace(value, { unitSystem: "metric" })).toBe("--");
  });
});
