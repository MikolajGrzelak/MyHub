const { test, expect } = require('@playwright/test');
const fs = require('node:fs/promises');

test('game shelf, personal target, session picker and real price observations', async ({page}) => {
  const errors = []; page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/?view=games&game=1977170');
  await expect(page.getByRole('heading', {name: 'Jusant.', exact: true})).toBeVisible();
  await expect(page.locator('#priceChart svg circle')).toHaveCount(2);
  await page.getByLabel('Rodzaj ceny na wykresie').selectOption('retail');
  await expect(page.locator('#priceChart')).toContainText('38.00–55.00');
  await page.getByLabel('Status', {exact: true}).selectOption('owned');
  await page.getByLabel('Cena docelowa (PLN)').fill('100');
  await page.getByLabel('Krótka sesja').selectOption('short');
  await page.getByLabel('Nastrój', {exact: true}).selectOption('relax');
  await page.getByRole('button', {name: 'Zapisz preferencje'}).click();
  await expect(page.locator('#personalPriceSignal')).toBeVisible();
  await page.reload();
  await expect(page.getByLabel('Status', {exact: true})).toHaveValue('owned');
  await expect(page.getByLabel('Cena docelowa (PLN)')).toHaveValue('100');
  await page.getByRole('link', {name: 'Wszystkie gry'}).click();
  await page.getByLabel('Półka', {exact: true}).selectOption('owned');
  await expect(page.locator('.game-tile:visible')).toHaveCount(1);
  await page.locator('.play-picker summary').click();
  await page.getByLabel('Czas', {exact: true}).selectOption('short');
  await page.getByLabel('Nastrój', {exact: true}).selectOption('relax');
  await page.getByRole('button', {name: 'Zaproponuj gry'}).click();
  await expect(page.locator('#gamePicks')).toContainText('Jusant');
  await page.getByLabel('Nastrój', {exact: true}).selectOption('challenge');
  await page.getByRole('button', {name: 'Zaproponuj gry'}).click();
  await expect(page.locator('#gamePicks')).toContainText('Brak pasujących oznaczeń');
  expect(errors).toEqual([]);
});

test('deals include current lows and a personal budget, with functional bookmarks', async ({page}) => {
  await page.goto('/?section=deal');
  const baseline = await page.locator('#feed .card').count();
  expect(baseline).toBe(25);
  await expect(page.locator('#feed')).not.toContainText('A Plague Tale: Innocence');
  await page.goto('/?view=games&game=752590');
  await page.getByLabel('Cena docelowa (PLN)').fill('25');
  await page.getByRole('button', {name: 'Zapisz preferencje'}).click();
  await page.getByRole('link', {name: 'Okazje', exact: true}).click();
  await expect(page.locator('#feed .card')).toHaveCount(26);
  const card = page.locator('#feed .card').filter({hasText: 'A Plague Tale: Innocence'});
  await expect(card).toContainText('Cena w Twoim zasięgu');
  await card.locator('[data-bookmark]').click();
  await expect(card.locator('[data-bookmark]')).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('link', {name: 'Zapisane na później', exact: true}).click();
  await expect(page.locator('#feed')).toContainText('A Plague Tale: Innocence');
});

test('a qualified deal surfaced by a personal target on a later page is not counted twice', async ({page}) => {
  await page.goto('/?view=games&game=1850570');
  await page.getByLabel('Cena docelowa (PLN)').fill('100');
  await page.getByRole('button', {name: 'Zapisz preferencje'}).click();
  await page.goto('/?section=deal&page=2');
  await expect(page.locator('#feed .card')).toHaveCount(1);
  await expect(page.locator('#resultCount')).toHaveText('25');
});

test('hardware journal supports edit, undo, export and safe backup import', async ({page}) => {
  const errors = []; page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('/?view=hardware');
  await page.getByLabel('Własna nazwa / wariant').fill('Mój Legion');
  await page.getByRole('button', {name: 'Zapisz sprzęt'}).click();
  await page.getByLabel('Gra', {exact: true}).selectOption('1977170');
  await page.getByLabel('Średni FPS').fill('42');
  await page.getByLabel('Limit mocy APU (W)').fill('15');
  await page.getByLabel('Rozdzielczość', {exact: true}).fill('1280 x 800');
  await page.getByLabel('Ustawienia, scena testowa i uwagi').fill('Scena testowa\nFSR wyłączony');
  await page.getByRole('button', {name: 'Zapisz pomiar', exact: true}).click();
  await expect(page.locator('#journalCount')).toContainText('1 pomiarów');
  await page.locator('.journal-entry summary').click();
  await page.getByRole('button', {name: 'Edytuj', exact: true}).click();
  await page.getByLabel('Średni FPS').fill('45');
  await page.getByRole('button', {name: 'Zapisz zmiany pomiaru'}).click();
  await expect(page.locator('#journalList table')).toContainText('45');
  await page.locator('.journal-entry summary').click();
  await page.getByRole('button', {name: 'Usuń pomiar'}).click();
  await expect(page.locator('#journalCount')).toContainText('0 pomiarów');
  await page.getByRole('button', {name: 'Cofnij usunięcie'}).click();
  await expect(page.locator('#journalCount')).toContainText('1 pomiarów');
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', {name: 'Pobierz kopię JSON'}).click();
  const download = await downloadPromise;
  const backup = JSON.parse(await fs.readFile(await download.path(), 'utf8'));
  expect(backup.tests[0].fps).toBe(45); expect(backup.device.name).toBe('Mój Legion');
  await page.evaluate(() => { ['myhub.games', 'myhub.device', 'myhub.tests', 'myhub.saved'].forEach((key) => localStorage.removeItem(key)); });
  await page.reload();
  await expect(page.locator('#journalCount')).toContainText('0 pomiarów');
  backup.tests[0].note = '<img src=x onerror=alert(1)>';
  backup.saved.push({id: 'unsafe', title: 'unsafe bookmark', url: 'javascript:alert(1)'});
  await page.locator('#importPersonal').setInputFiles({name: 'backup.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(backup))});
  await expect(page.locator('#toast')).toContainText('Wczytano kopię');
  await expect(page.getByLabel('Własna nazwa / wariant')).toHaveValue('Mój Legion');
  await expect(page.locator('#journalCount')).toContainText('1 pomiarów');
  await page.locator('.journal-entry summary').click();
  await expect(page.locator('.journal-note')).toHaveText('<img src=x onerror=alert(1)>');
  await expect(page.locator('.journal-note img')).toHaveCount(0);
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('myhub.saved')))).toEqual([]);
  expect(errors).toEqual([]);
});

test('paused-game announcements and the last-visit digest use real dates', async ({page}) => {
  await page.goto('/');
  await page.evaluate(() => {
    localStorage.setItem('myhub.lastVisit', JSON.stringify('2026-10-06T08:00:00Z'));
    localStorage.setItem('myhub.games', JSON.stringify({'1977170': {status: 'paused', paused_at: '2026-10-06T08:00:00Z'}}));
  });
  await page.reload();
  await expect(page.locator('#visitNote')).toContainText('nowych wpisów');
  await page.goto('/?view=games');
  await expect(page.locator('#returnSignals')).toBeVisible();
  await expect(page.locator('#returnList')).toContainText('Jusant');
  await page.evaluate(() => localStorage.setItem('myhub.games', JSON.stringify({'1977170': {status: 'paused', paused_at: '2026-10-08T08:00:00Z'}})));
  await page.reload();
  await expect(page.locator('#returnSignals')).toBeHidden();
});

test('all new views fit a narrow phone and preserve saved personal data offline', async ({page, context, browserName}, testInfo) => {
  const errors = []; page.on('pageerror', (e) => errors.push(e.message));
  await page.setViewportSize({width: 320, height: 700});
  for (const [name, url] of [['games', '/?view=games'], ['game', '/?view=games&game=1977170'], ['hardware', '/?view=hardware'], ['home', '/']]) {
    await page.goto(url);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({path: testInfo.outputPath(`${name}-320.png`)});
  }
  if (browserName !== 'webkit') {
    await page.evaluate(async () => { await navigator.serviceWorker.ready; });
    await page.goto('/?view=games&game=1977170');
    await page.getByLabel('Status', {exact: true}).selectOption('owned');
    await page.getByRole('button', {name: 'Zapisz preferencje'}).click();
    await page.waitForFunction(async () => {
      const keys = await caches.keys();
      for (const key of keys.filter((k) => k.includes('pages'))) if (await (await caches.open(key)).match('/?view=games&game=1977170')) return true;
      return false;
    });
    await context.setOffline(true); await page.reload();
    await expect(page.getByLabel('Status', {exact: true})).toHaveValue('owned');
    await expect(page.locator('#connectionStatus')).toContainText('Offline');
    await context.setOffline(false);
  }
  expect(errors).toEqual([]);
});
