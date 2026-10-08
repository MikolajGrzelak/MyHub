const { test, expect } = require("@playwright/test");

test("section swipes preserve search, cancel safely and keep pull refresh separate", async ({
  page,
  isMobile,
}) => {
  test.skip(!isMobile, "Touch navigation is a mobile feature.");
  await page.goto("/?section=news&lang=pl&q=Legion");
  const touch = async (type, x, y) => {
    await page.waitForLoadState("domcontentloaded");
    return page.evaluate(
      ({ type, x, y }) => {
        const event = new Event(type, { bubbles: true });
        Object.defineProperty(event, "touches", {
          value: type === "touchend" ? [] : [{ clientX: x, clientY: y }],
        });
        Object.defineProperty(event, "changedTouches", {
          value: [{ clientX: x, clientY: y }],
        });
        document.body.dispatchEvent(event);
      },
      { type, x, y },
    );
  };
  await touch("touchstart", 190, 300);
  await touch("touchend", 70, 300);
  await expect(page).toHaveURL(/section=reddit/);
  expect(new URL(page.url()).searchParams.get("q")).toBe("Legion");
  expect(new URL(page.url()).searchParams.get("lang")).toBe("pl");
  await touch("touchstart", 190, 300);
  await touch("touchcancel", 80, 300);
  await touch("touchend", 70, 300);
  await expect(page).toHaveURL(/section=reddit/);
  await touch("touchstart", 10, 300);
  await touch("touchend", 170, 300);
  await expect(page).toHaveURL(/section=reddit/);
  await page.evaluate(() => scrollTo({ top: 0, behavior: "instant" }));
  await page.route("**/health", (route) =>
    route.fulfill({ status: 503, body: "Unavailable" }),
  );
  await touch("touchstart", 150, 100);
  await touch("touchmove", 150, 220);
  await expect(page.locator("#pullRefresh")).toContainText("Puść");
  await touch("touchend", 150, 220);
  await expect(page.locator("#toast")).toContainText("Nie udało się odświeżyć");
});

test("mobile layout, search, filters and progressively loading the whole feed", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(page.locator(".card")).toHaveCount(36);
  await expect(
    page.getByRole("navigation", { name: "Główna nawigacja" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: "Pokaż więcej", exact: true }).click();
  await expect(page.locator(".card")).toHaveCount(51);
  await expect(page.getByRole("searchbox")).toBeHidden();
  await page.locator(".search-panel summary").click();
  await page.getByRole("searchbox").fill("Legion Go");
  await page.getByRole("button", { name: "Wyszukaj", exact: true }).click();
  await expect(page.locator(".active-filters")).toContainText("Legion Go");
  await page.getByRole("link", { name: "EN", exact: true }).click();
  expect(new URL(page.url()).searchParams.get("q")).toBe("Legion Go");
  await page.goto("/?section=youtube");
  await page.locator(".filter-panel summary").click();
  await expect(page.locator("select[name=source] optgroup")).toHaveCount(1);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
});

test("saved collection survives reload, marks read and can be removed", async ({
  page,
  context,
}) => {
  await page.goto("/?section=deal");
  const first = page.locator(".card").first();
  const title = await first.locator("h2").innerText();
  await first.locator("[data-bookmark]").click();
  await expect(first.locator("[data-bookmark]")).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await page
    .getByRole("link", { name: "Zapisane na później", exact: true })
    .click();
  await expect(page.locator(".card")).toHaveCount(1);
  await expect(page.locator("h2").filter({ hasText: title })).toBeVisible();
  await expect(page.locator(".saved-note")).toContainText(
    "Cena z momentu zapisu",
  );
  await page.reload();
  await expect(page.locator(".card")).toHaveCount(1);
  // Abort external navigation while checking read state and native new-tab behavior.
  await context.route("https://gg.deals/**", (route) => route.abort());
  const popup = context.waitForEvent("page");
  await page.locator(".card-link").click();
  await (await popup).close();
  await expect(page.locator(".read-label")).toBeVisible();
  await page.locator("[data-bookmark]").click();
  await expect(page.locator(".card")).toHaveCount(0);
  await expect(page.locator("#emptyState")).toBeVisible();
});

test("theme and density persist; preferences dialog is accessible", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Ustawienia widoku" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByLabel("Motyw", { exact: true }).selectOption("light");
  await page.getByLabel("Kompaktowe karty").check();
  await page.getByRole("button", { name: "Zamknij ustawienia" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(page.locator("html")).toHaveAttribute("data-density", "compact");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(page.getByRole("button", { name: "Widok pełny" })).toBeVisible();
});

test("worker controls the root and offline retains only exact visited views", async ({
  page,
  context,
  browserName,
}) => {
  test.skip(
    browserName === "webkit",
    "Playwright WebKit does not provide reliable service worker emulation; test Safari layout and interactions separately.",
  );
  await page.goto("/");
  await page.evaluate(async () => {
    await navigator.serviceWorker.ready;
    if (!navigator.serviceWorker.controller)
      await new Promise((resolve) =>
        navigator.serviceWorker.addEventListener("controllerchange", resolve, {
          once: true,
        }),
      );
  });
  await page.goto("/?section=reddit");
  await page.locator(".card").first().locator("[data-bookmark]").click();
  await page.goto("/?view=saved");
  await expect(page.locator(".card")).toHaveCount(1);
  await page.evaluate(async () => {
    while (!(await caches.keys()).some((key) => key.includes("pages")))
      await new Promise((resolve) => setTimeout(resolve, 100));
  });
  await context.setOffline(true);
  await page.reload();
  await expect(page.locator(".card")).toHaveCount(1);
  await expect(page.locator("#connectionStatus")).toContainText("Offline");
  await page.goto("/?section=reddit");
  await expect(page.locator(".card")).toHaveCount(36);
  await page.goto("/?q=never-visited-offline-test");
  await expect(
    page.getByRole("heading", { name: "Chwilowo offline." }),
  ).toBeVisible();
  await context.setOffline(false);
});

test("capture reviewable screen and verify long narrow layouts", async ({
  page,
}, testInfo) => {
  await page.goto("/");
  await page.evaluate(() => scrollTo({ top: 0, behavior: "instant" }));
  await page.screenshot({
    path: testInfo.outputPath("myhub-home.png"),
    fullPage: false,
  });
  await page.goto("/?section=deal");
  await page.evaluate(() => scrollTo({ top: 0, behavior: "instant" }));
  await page.screenshot({
    path: testInfo.outputPath("myhub-deals.png"),
    fullPage: false,
  });
  await page.setViewportSize({ width: 320, height: 700 });
  await page.goto('/?section=news');
  await page.locator(".filter-panel summary").click();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
