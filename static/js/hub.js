(() => {
  "use strict";
  const $ = (selector) => document.querySelector(selector);
  const data = JSON.parse($("#hubData")?.textContent || "{}");
  const games = Array.isArray(data.games) ? data.games : [];
  const statuses = {watching: "Obserwuję", owned: "Mam", playing: "Gram teraz", paused: "Odłożona", completed: "Ukończona"};
  const read = (key, fallback) => {
    try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
  };
  const write = (key, value) => {
    try { localStorage.setItem(key, JSON.stringify(value)); return true; }
    catch { window.myhubToast?.("Nie udało się zapisać danych na urządzeniu."); return false; }
  };
  let shelf = read("myhub.games", {});
  if (!shelf || typeof shelf !== "object" || Array.isArray(shelf)) shelf = {};
  const pref = (id) => shelf[id] && typeof shelf[id] === "object" ? shelf[id] : {};
  const number = (value) => ["number", "string"].includes(typeof value) && String(value).trim() !== "" && !isNaN(value) && isFinite(Number(value)) && Number(value) >= 0 ? Number(value) : null;
  const priceInRange = (game) => {
    const target = number(pref(game.id).target), current = number(game.price?.current_price);
    return target !== null && current !== null && game.price?.price_verified === true && game.price?.active === true && (game.price?.currency || "PLN") === "PLN" && current <= target;
  };
  const fold = (text) => String(text).toLocaleLowerCase("pl").replaceAll("ł", "l").normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  const node = (tag, text, className) => {
    const el = document.createElement(tag);
    if (text != null) el.textContent = text;
    if (className) el.className = className;
    return el;
  };
  function library() {
    if (!$("#gameGrid")) return;
    const search = fold($("#gameSearch").value), filter = $("#libraryFilter").value;
    let count = 0;
    games.forEach((game) => {
      const tile = document.querySelector(`.game-tile[data-game-id="${game.id}"]`);
      if (!tile) return;
      const state = pref(game.id).status || "watching";
      tile.querySelector("[data-game-status]").textContent = statuses[state] || statuses.watching;
      tile.querySelector(".personal-deal").hidden = !priceInRange(game);
      tile.hidden = !fold(game.name).includes(search) || (filter !== "all" && (filter === "deals" ? !priceInRange(game) : state !== filter));
      if (!tile.hidden) count++;
    });
    $("#libraryCount").textContent = `${count} z ${games.length} gier`;
    $("#libraryEmpty").hidden = count > 0;
  }
  $("#gameSearch")?.addEventListener("input", library);
  $("#libraryFilter")?.addEventListener("change", library);
  function personalPrice() {
    const game = games.find((g) => g.id === data.selected);
    if (!game || !$("#personalPriceSignal")) return;
    $("#personalPriceSignal").hidden = !priceInRange(game);
    $("#personalPriceSignal").textContent = "Cena w Twoim zasięgu · spełnia Twój próg";
  }
  if (data.selected && $("#saveGame")) {
    const p = pref(data.selected);
    $("#gameStatus").value = statuses[p.status] ? p.status : "watching";
    $("#gameTarget").value = number(p.target) ?? "";
    $("#gameSession").value = ["short", "long"].includes(p.session) ? p.session : "unknown";
    $("#gameMood").value = ["story", "relax", "challenge"].includes(p.mood) ? p.mood : "any";
    $("#gameNote").value = String(p.note || "").slice(0, 500);
    $("#saveGame").addEventListener("click", () => {
      if (!$("#gameTarget").checkValidity()) { $("#gameTarget").reportValidity(); return; }
      const next = {...shelf, [data.selected]: {status: $("#gameStatus").value, target: number($("#gameTarget").value),
        session: $("#gameSession").value, mood: $("#gameMood").value, note: $("#gameNote").value.trim(),
        updated_at: new Date().toISOString(), paused_at: $("#gameStatus").value === "paused" ?
          (pref(data.selected).status === "paused" ? pref(data.selected).paused_at : new Date().toISOString()) : null}};
      if (write("myhub.games", next)) { shelf = next; personalPrice(); window.myhubToast?.("Zapisano Twoją półkę i cenę docelową"); }
    });
    personalPrice();
  }
  $("#pickGame")?.addEventListener("click", () => {
    const time = $("#pickTime").value, mood = $("#pickMood").value;
    const candidates = games.filter((game) => {
      const p = pref(game.id);
      return ["owned", "playing", "paused"].includes(p.status) && (time === "any" || p.session === time) && (mood === "any" || p.mood === mood);
    });
    // Shuffle a copy so each visit can surface a different part of the backlog.
    for (let i = candidates.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [candidates[i], candidates[j]] = [candidates[j], candidates[i]];
    }
    $("#gamePicks").replaceChildren();
    candidates.slice(0, 3).forEach((game) => {
      const link = node("a", null, "pick-result"); link.href = `/?view=games&game=${game.id}`;
      link.append(node("strong", game.name), node("span", `${statuses[pref(game.id).status]}${time === "short" ? " · oznaczona jako dobra na 30 minut" : ""}${mood !== "any" ? " · pasuje do Twojego nastroju" : ""}`));
      $("#gamePicks").append(link);
    });
    if (!candidates.length) $("#gamePicks").append(node("p", "Brak pasujących oznaczeń. Na karcie gry ustaw posiadanie, długość sesji i nastrój albo poszerz wybór.", "privacy-note"));
  });
  if (data.home) {
    const last = read("myhub.lastVisit", null);
    const cutoff = Date.parse(last);
    if (Number.isFinite(cutoff)) {
      const newItems = (data.visits || []).filter((i) => Date.parse(i.date) > cutoff);
      $("#visitNote").textContent = newItems.length ? `${newItems.length} nowych wpisów od Twojej ostatniej wizyty.` : "Jesteś na bieżąco ze swoim przeglądem.";
      $("#visitNote").hidden = false;
    }
    write("myhub.lastVisit", new Date().toISOString());
  }
  if ($("#returnSignals")) {
    games.filter((g) => pref(g.id).status === "paused").forEach((game) => {
      const paused = Date.parse(pref(game.id).paused_at);
      if (!Number.isFinite(paused) || !game.latest_announcement || Date.parse(game.latest_announcement) <= paused) return;
      const link = node("a", `${game.name} · nowy komunikat twórców`, "pick-result");
      link.href = `/?view=games&game=${game.id}`; $("#returnList").append(link);
    });
    $("#returnSignals").hidden = !$("#returnList").children.length;
  }
  if ($("#watchedDeals")) {
    const fragment = $("#watchedDeals").content;
    const additional = [];
    const params = new URLSearchParams(location.search);
    games.filter(priceInRange).forEach((game) => {
      const price = game.price;
      if (params.get("source") && params.get("source") !== price.source) return;
      if (params.get("lang") && params.get("lang") !== price.language) return;
      if (params.get("category") && fold(params.get("category")) !== fold(price.category)) return;
      const text = fold([price.title, price.source, price.summary].join(" "));
      if (fold(params.get("q") || "").split(/\s+/).some((word) => !text.includes(word))) return;
      let card = [...$("#feed").querySelectorAll(".card")].find((c) => c.dataset.id === price.id);
      if (!card) {
        card = [...fragment.querySelectorAll(".card")].find((c) => c.dataset.id === price.id)?.cloneNode(true);
        if (!card) return;
        $("#feed").prepend(card); additional.push(price);
      }
      if (!price.within_target) card.querySelector(".card-content").append(node("div", "Cena w Twoim zasięgu · Twój próg", "match"));
    });
    if (additional.length) {
      window.myhubExtraDeals = additional.filter((price) => !price.deal_qualified).length;
      $("#resultCount").textContent = Number($("#resultCount").textContent) + window.myhubExtraDeals;
      $("#emptyState").hidden = true;
      document.dispatchEvent(new CustomEvent("myhub:items", {detail: {items: additional}}));
    }
    const flagOwned = () => {
      games.filter((game) => ["owned", "playing", "paused", "completed"].includes(pref(game.id).status)).forEach((game) => {
        const card = [...$("#feed").querySelectorAll(".card")].find((c) => c.dataset.id === game.price?.id);
        if (card && !card.querySelector(".owned-label")) card.querySelector(".card-content").append(node("p", "Masz już tę grę na swojej półce", "owned-label match"));
      });
    };
    flagOwned();
    new MutationObserver(flagOwned).observe($("#feed"), {childList: true});
  }
  function chart() {
    if (!$("#priceChart")) return;
    const kind = $("#historyKind").value;
    const points = (data.history || []).filter((p) => number(p[kind]) !== null && Number.isFinite(Date.parse(p.at)));
    $("#priceChart").replaceChildren();
    if (!points.length) { $("#priceChart").append(node("p", "Historia pojawi się po zebraniu pierwszych cen.", "privacy-note")); return; }
    const currency = points[points.length - 1].currency || "PLN";
    const same = points.filter((p) => (p.currency || "PLN") === currency);
    const values = same.map((p) => Number(p[kind])), low = Math.min(...values), high = Math.max(...values);
    const start = Date.parse(same[0].at), end = Date.parse(same[same.length - 1].at);
    const coordinates = same.map((p) => [20 + (Date.parse(p.at) - start) / (end - start || 1) * 560,
      120 - (Number(p[kind]) - low) / (high - low || 1) * 90]);
    const ns = "http://www.w3.org/2000/svg", svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 600 150"); svg.setAttribute("aria-hidden", "true");
    const line = document.createElementNS(ns, "polyline");
    line.setAttribute("points", coordinates.map((xy) => xy.join(",")).join(" "));
    line.setAttribute("fill", "none"); line.setAttribute("stroke", "var(--accent)"); line.setAttribute("stroke-width", "3");
    line.setAttribute("stroke-dasharray", "5 5");
    svg.append(line);
    same.forEach((p, i) => {
      const circle = document.createElementNS(ns, "circle"), title = document.createElementNS(ns, "title");
      circle.setAttribute("cx", coordinates[i][0]); circle.setAttribute("cy", coordinates[i][1]); circle.setAttribute("r", "4"); circle.setAttribute("fill", "var(--accent)");
      title.textContent = `${new Date(p.at).toLocaleString("pl-PL")}: ${Number(p[kind]).toFixed(2)} ${currency}`; circle.append(title); svg.append(circle);
    });
    $("#priceChart").append(svg, node("p", `${same.length} obserwacji · zakres ${low.toFixed(2)}–${high.toFixed(2)} ${currency}`, "privacy-note"));
    $("#priceChart").append(node("p", `${new Date(same[0].at).toLocaleDateString("pl-PL")} → ${new Date(same[same.length - 1].at).toLocaleDateString("pl-PL")}`, "privacy-note"));
    $("#priceChart").setAttribute("aria-label", `Historia ceny: ${same.length} obserwacji, od ${low.toFixed(2)} do ${high.toFixed(2)} ${currency}`);
  }
  $("#historyKind")?.addEventListener("change", chart);
  function hardware() {
    if (!$("#deviceModel")) return;
    const profiles = {balanced: "Zbalansowany", battery: "Bateria", performance: "Płynność", quality: "Jakość obrazu"};
    const models = {
      legion: {name: "Legion Go · Z1 Extreme", query: "Legion Go", support: "https://pcsupport.lenovo.com/"},
      deck: {name: "Steam Deck", query: "Steam Deck", support: "https://help.steampowered.com/"},
      ally: {name: "ROG Ally", query: "ROG Ally", support: "https://www.asus.com/support/"},
      other: {name: "Inne urządzenie", query: "handheld", support: null},
    };
    let device = read("myhub.device", {});
    if (!device || typeof device !== "object" || Array.isArray(device)) device = {};
    let journal = read("myhub.tests", []);
    journal = Array.isArray(journal) ? journal.filter((r) => r && typeof r.id === "string").slice(-200) : [];
    let editing = null, deleted = null;
    const applyDevice = () => {
      $("#deviceModel").value = models[device.model] ? device.model : "legion";
      $("#deviceName").value = String(device.name || "").slice(0, 80);
      $("#deviceNote").value = String(device.note || "").slice(0, 1000);
      deviceLinks();
    };
    function deviceLinks() {
      const model = models[$("#deviceModel").value];
      $("#deviceNews").href = `/?q=${encodeURIComponent(model.query)}`;
      $("#deviceSupport").hidden = !model.support;
      if (model.support) $("#deviceSupport").href = model.support;
    }
    $("#deviceModel").addEventListener("change", deviceLinks);
    $("#saveDevice").addEventListener("click", () => {
      const next = {model: $("#deviceModel").value, name: $("#deviceName").value.trim(), note: $("#deviceNote").value.trim(), updated_at: new Date().toISOString()};
      if (write("myhub.device", next)) { device = next; window.myhubToast?.("Zapisano Twój sprzęt"); }
    });
    function journalView() {
      const filter = $("#journalFilter").value;
      const records = [...journal].filter((r) => filter === "all" || r.game_id === filter).sort((a, b) => (Date.parse(b.created_at) || 0) - (Date.parse(a.created_at) || 0));
      $("#journalList").replaceChildren(); $("#journalCount").textContent = `${records.length} pomiarów`;
      if (!records.length) { $("#journalList").append(node("p", "Brak pomiarów. Zapisz pierwszy test powyżej.", "privacy-note")); return; }
      const wrap = node("div", null, "history-table-wrap"), table = node("table", null, "history-table"), head = node("tr");
      ["Gra / urządzenie", "FPS", "APU (W)", "Profil / rozdzielczość"].forEach((name) => head.append(node("th", name)));
      const thead = node("thead"); thead.append(head); const tbody = node("tbody");
      records.forEach((r) => {
        const row = node("tr");
        row.append(node("td", `${games.find((g) => g.id === r.game_id)?.name || "Inny test"} · ${r.device_name || "Bez nazwy"}`),
          node("td", r.fps ?? "—"), node("td", r.watts ?? "—"), node("td", `${profiles[r.profile] || "Zbalansowany"} · ${r.resolution || "—"}`));
        tbody.append(row);
      }); table.append(thead, tbody); wrap.append(table); $("#journalList").append(wrap);
      records.forEach((r) => {
        const detail = node("details", null, "journal-entry"), summary = node("summary", `${games.find((g) => g.id === r.game_id)?.name || "Inny test"} · ${new Date(r.created_at).toLocaleString("pl-PL")}`);
        detail.append(summary, node("p", `${r.device_name || ""} · ${r.version || "Wersja niepodana"}`, "privacy-note"));
        if (r.note) detail.append(node("p", r.note, "journal-note"));
        const edit = node("button", "Edytuj", "text-button"), remove = node("button", "Usuń pomiar", "text-button");
        edit.type = remove.type = "button";
        edit.addEventListener("click", () => {
          editing = r.id;
          $("#testGame").value = r.game_id; $("#testProfile").value = profiles[r.profile] ? r.profile : "balanced";
          $("#testFps").value = r.fps ?? ""; $("#testWatts").value = r.watts ?? "";
          $("#testResolution").value = r.resolution || ""; $("#testVersion").value = r.version || ""; $("#testNote").value = r.note || "";
          $("#testForm button[type=submit]").textContent = "Zapisz zmiany pomiaru"; $("#cancelEdit").hidden = false;
          // Keep the form still while the user changes fields and submits it.
          $("#testForm").scrollIntoView({behavior: "instant", block: "start"});
        });
        remove.addEventListener("click", () => {
          const next = journal.filter((i) => i.id !== r.id);
          if (write("myhub.tests", next)) {
            deleted = r; journal = next; $("#undoTest").hidden = false;
            if (editing === r.id) resetForm(); journalView(); window.myhubToast?.("Usunięto pomiar. Możesz cofnąć usunięcie.");
          }
        });
        detail.append(edit, remove); $("#journalList").append(detail);
      });
    }
    function resetForm() {
      editing = null; $("#testForm").reset(); $("#cancelEdit").hidden = true;
      $("#testForm button[type=submit]").textContent = "Zapisz pomiar";
    }
    $("#cancelEdit").addEventListener("click", resetForm);
    $("#undoTest").addEventListener("click", () => {
      if (!deleted || journal.length >= 200) return;
      const next = [...journal.filter((r) => r.id !== deleted.id), deleted];
      if (write("myhub.tests", next)) { journal = next; deleted = null; $("#undoTest").hidden = true; journalView(); }
    });
    $("#testForm").addEventListener("submit", (event) => {
      event.preventDefault(); if (!$("#testForm").reportValidity()) return;
      if (!editing && journal.length >= 200) { window.myhubToast?.("Dziennik mieści 200 pomiarów. Wyeksportuj kopię i usuń starsze wpisy."); return; }
      const previous = journal.find((r) => r.id === editing), now = new Date().toISOString();
      const record = {id: editing || crypto.randomUUID(), game_id: $("#testGame").value, profile: $("#testProfile").value,
        fps: number($("#testFps").value), watts: number($("#testWatts").value), resolution: $("#testResolution").value.trim(),
        version: $("#testVersion").value.trim(), note: $("#testNote").value.trim(),
        device_name: previous?.device_name || $("#deviceName").value.trim() || models[$("#deviceModel").value].name,
        device_model: previous?.device_model || $("#deviceModel").value, created_at: previous?.created_at || now, updated_at: now};
      const next = [...journal.filter((r) => r.id !== record.id), record];
      if (write("myhub.tests", next)) { journal = next; resetForm(); journalView(); window.myhubToast?.("Zapisano pomiar"); }
    });
    $("#journalFilter").addEventListener("change", journalView);
    $("#exportPersonal").addEventListener("click", () => {
      const payload = {schema: 1, exported_at: new Date().toISOString(), games: read("myhub.games", {}),
        device: read("myhub.device", {}), tests: read("myhub.tests", []), saved: read("myhub.saved", [])};
      const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], {type: "application/json"}));
      const link = node("a"); link.href = url; link.download = `myhub-backup-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    $("#importPersonal").addEventListener("change", async (event) => {
      const file = event.target.files?.[0]; if (!file) return;
      try {
        if (file.size > 2_000_000) throw new Error("Plik jest za duży (maks. 2 MB).");
        const incoming = JSON.parse(await file.text());
        if (!incoming || incoming.schema !== 1 || !incoming.games || typeof incoming.games !== "object" || Array.isArray(incoming.games) || !Array.isArray(incoming.tests) || !Array.isArray(incoming.saved)) throw new Error("To nie jest poprawna kopia MyHub.");
        const text = (v, max) => typeof v === "string" ? v.slice(0, max) : "";
        const validDate = (v) => typeof v === "string" && Number.isFinite(Date.parse(v)) ? new Date(v).toISOString() : null;
        const newer = (a, b, key = "updated_at") => (Date.parse(b?.[key]) || 0) > (Date.parse(a?.[key]) || 0) ? b : a;
        const mergedGames = {...shelf};
        Object.entries(incoming.games).slice(0, 500).forEach(([id, p]) => {
          if (!/^\d{1,10}$/.test(id) || !p || typeof p !== "object" || !statuses[p.status]) return;
          const clean = {status: p.status, target: number(p.target) !== null && number(p.target) <= 10000 ? number(p.target) : null,
            session: ["short", "long"].includes(p.session) ? p.session : "unknown", mood: ["story", "relax", "challenge"].includes(p.mood) ? p.mood : "any",
            note: text(p.note, 500), updated_at: validDate(p.updated_at), paused_at: validDate(p.paused_at)};
          mergedGames[id] = mergedGames[id] ? newer(mergedGames[id], clean) : clean;
        });
        const mergedTests = new Map(journal.map((r) => [r.id, r]));
        incoming.tests.slice(0, 200).forEach((r) => {
          if (!r || typeof r !== "object" || !/^[\w-]{1,80}$/.test(r.id) || !validDate(r.created_at)) return;
          const clean = {id: r.id, game_id: /^\d{1,10}$/.test(r.game_id) ? r.game_id : "other", profile: profiles[r.profile] ? r.profile : "balanced",
            fps: number(r.fps) !== null && number(r.fps) <= 1000 ? number(r.fps) : null, watts: number(r.watts) !== null && number(r.watts) <= 300 ? number(r.watts) : null,
            resolution: text(r.resolution, 40), version: text(r.version, 100), note: text(r.note, 1000), device_name: text(r.device_name, 80),
            device_model: models[r.device_model] ? r.device_model : "other", created_at: validDate(r.created_at), updated_at: validDate(r.updated_at)};
          mergedTests.set(clean.id, mergedTests.has(clean.id) ? newer(mergedTests.get(clean.id), clean) : clean);
        });
        if (mergedTests.size > 200) throw new Error("Po połączeniu byłoby ponad 200 pomiarów. Usuń starsze wpisy po zapisaniu kopii.");
        const safeUrl = (value) => { try { return ["http:", "https:"].includes(new URL(value).protocol); } catch { return false; } };
        const existingSaved = read("myhub.saved", []);
        const mergedSaved = new Map((Array.isArray(existingSaved) ? existingSaved : []).map((r) => [r.id, r]));
        incoming.saved.slice(0, 100).forEach((r) => {
          if (!r || typeof r.id !== "string" || !safeUrl(r.url) || typeof r.title !== "string") return;
          const clean = {...r, id: text(r.id, 128), title: text(r.title, 300), summary: text(r.summary, 1200), summary_pl: text(r.summary_pl, 1200),
            saved_at: validDate(r.saved_at), tags: Array.isArray(r.tags) ? r.tags.slice(0, 8).map((t) => text(t, 80)) : [],
            matched_keywords: Array.isArray(r.matched_keywords) ? r.matched_keywords.slice(0, 8).map((t) => text(t, 80)) : []};
          mergedSaved.set(clean.id, mergedSaved.has(clean.id) ? newer(mergedSaved.get(clean.id), clean, "saved_at") : clean);
        });
        if (mergedSaved.size > 100) throw new Error("Po połączeniu byłoby ponad 100 zapisanych treści. Zwolnij miejsce przed importem.");
        let nextDevice = device;
        if (incoming.device && typeof incoming.device === "object" && models[incoming.device.model]) {
          const clean = {model: incoming.device.model, name: text(incoming.device.name, 80), note: text(incoming.device.note, 1000), updated_at: validDate(incoming.device.updated_at)};
          nextDevice = Object.keys(device).length ? newer(device, clean) : clean;
        }
        const entries = [["myhub.games", mergedGames], ["myhub.device", nextDevice], ["myhub.tests", [...mergedTests.values()]], ["myhub.saved", [...mergedSaved.values()]]];
        const before = entries.map(([key]) => [key, localStorage.getItem(key)]);
        try { entries.forEach(([key, value]) => localStorage.setItem(key, JSON.stringify(value))); }
        catch (error) { before.forEach(([key, value]) => { try { value === null ? localStorage.removeItem(key) : localStorage.setItem(key, value); } catch {} }); throw error; }
        shelf = mergedGames; device = nextDevice; journal = [...mergedTests.values()]; resetForm(); applyDevice(); journalView();
        window.dispatchEvent(new StorageEvent("storage", {key: "myhub.saved"}));
        window.myhubToast?.("Wczytano kopię i połączono dane");
      } catch (error) { window.myhubToast?.(error instanceof SyntaxError ? "Plik nie zawiera poprawnego JSON." : error.message || "Nie udało się wczytać kopii."); }
      finally { event.target.value = ""; }
    });
    applyDevice(); journalView();
  }
  hardware();
  library(); chart();
})();
