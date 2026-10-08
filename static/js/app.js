(() => {
  "use strict";
  const $ = (selector) => document.querySelector(selector);
  const feed = $("#feed");
  if (!feed) return;
  const params = new URLSearchParams(location.search);
  const savedView = document.body.dataset.view === "saved";
  const items = new Map(
    JSON.parse($("#pageItems").textContent).map((item) => [item.id, item]),
  );
  const safeUrl = (value) => {
    try {
      const url = new URL(value);
      return ["http:", "https:"].includes(url.protocol) ? url.href : "";
    } catch {
      return "";
    }
  };
  function readStorage(key, fallback) {
    try {
      return JSON.parse(localStorage.getItem(key)) || fallback;
    } catch {
      return fallback;
    }
  }
  const savedRaw = readStorage("myhub.saved", []);
  const saved = new Map(
    (Array.isArray(savedRaw) ? savedRaw : [])
      .filter(
        (item) => item && typeof item.id === "string" && safeUrl(item.url),
      )
      .map((item) => [item.id, item]),
  );
  const readRaw = readStorage("myhub.read", []);
  const read = new Set(
    Array.isArray(readRaw)
      ? readRaw.filter((id) => typeof id === "string")
      : [],
  );
  let toastTimer;
  function toast(message) {
    $("#toast").textContent = message;
    $("#toast").hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      $("#toast").hidden = true;
    }, 3300);
  }
  window.myhubToast = toast;
  document.addEventListener("myhub:items", (event) => {
    (event.detail?.items || []).forEach((item) => items.set(item.id, item));
    hydrate();
  });
  function persist(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
      return true;
    } catch {
      toast(
        "Nie udało się zapisać na urządzeniu. Sprawdź wolne miejsce lub ustawienia przeglądarki.",
      );
      return false;
    }
  }
  function dates(container = document) {
    container.querySelectorAll("[data-date]").forEach((el) => {
      const date = new Date(el.dataset.date);
      if (Number.isNaN(date.valueOf())) {
        el.textContent = "Brak daty źródła";
        return;
      }
      el.textContent = new Intl.DateTimeFormat("pl-PL", {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      }).format(date);
    });
  }
  function hydrate() {
    dates();
    document.querySelectorAll(".card").forEach((card) => {
      const button = card.querySelector("[data-bookmark]");
      if (button) {
        const isSaved = saved.has(card.dataset.id);
        button.setAttribute("aria-pressed", String(isSaved));
        button.setAttribute(
          "aria-label",
          `${isSaved ? "Usuń z zapisanych" : "Zapisz na później"}: ${card.querySelector("h2")?.textContent || ""}`,
        );
      }
      card.classList.toggle("is-read", read.has(card.dataset.id));
      const label = card.querySelector(".read-label");
      if (label) label.hidden = !read.has(card.dataset.id);
    });
    $("#savedCount").textContent = saved.size;
    $("#savedCount").hidden = !saved.size;
  }
  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = String(text);
    return node;
  }
  function renderSaved() {
    const fold = (value) =>
      String(value || "")
        .toLocaleLowerCase("pl")
        .replaceAll("ł", "l")
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "");
    const words = fold(params.get("q")).trim().split(/\s+/).filter(Boolean);
    const records = [...saved.values()]
      .filter((item) => {
        if (
          params.get("section") === "priority" &&
          !(item.priority || item.matched_keywords?.length)
        )
          return false;
        if (
          params.get("section") &&
          params.get("section") !== "priority" &&
          item.source_type !== params.get("section")
        )
          return false;
        if (params.get("lang") && item.language !== params.get("lang"))
          return false;
        if (params.get("source") && item.source !== params.get("source"))
          return false;
        if (
          params.get("category") &&
          fold(item.category) !== fold(params.get("category"))
        )
          return false;
        const text = fold(
          [
            item.title,
            item.summary,
            item.summary_pl,
            item.source,
            ...(item.tags || []),
            ...(item.matched_keywords || []),
          ].join(" "),
        );
        return words.every((word) => text.includes(word));
      })
      .sort((a, b) => {
        if (params.get("sort") === "priority") {
          const priority =
            Number(Boolean(b.priority || b.matched_keywords?.length)) -
            Number(Boolean(a.priority || a.matched_keywords?.length));
          if (priority) return priority;
        }
        return (
          (Date.parse(b.published_at) || 0) - (Date.parse(a.published_at) || 0)
        );
      });
    feed.replaceChildren();
    records.forEach((item) => {
      const card = element(
        "article",
        `card type-${["news", "reddit", "youtube", "deal"].includes(item.source_type) ? item.source_type : "news"}`,
      );
      card.dataset.id = item.id;
      const content = element("div", "card-content");
      const meta = element("div", "meta");
      meta.append(
        element("span", "source-line", item.source),
        element("span", "lang-pill", item.language === "pl" ? "PL" : "EN"),
      );
      const heading = element("h2");
      const link = element("a", "card-link", item.title);
      link.href = safeUrl(item.url);
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      heading.append(link);
      content.append(meta, heading);
      if (item.price)
        content.append(element("strong", "deal-price", item.price));
      if (item.source_type === "deal")
        content.append(
          element(
            "p",
            "saved-note",
            "Cena z momentu zapisu. Sprawdź aktualność oferty w źródle.",
          ),
        );
      const summary =
        item.source_type === "reddit" || item.language === "pl"
          ? item.summary
          : item.summary_pl || item.summary;
      if (summary) content.append(element("p", "card-summary", summary));
      const footer = element("footer", "card-footer");
      const dateWrap = element("div", "card-date");
      const time = element("time");
      time.dataset.date = item.published_at || "";
      dateWrap.append(time);
      const readLabel = element("span", "read-label", "Przeczytane");
      readLabel.hidden = true;
      dateWrap.append(readLabel);
      const button = element("button", "bookmark-button icon-button");
      button.type = "button";
      button.dataset.bookmark = item.id;
      button.append($(".saved-shortcut .icon").cloneNode(true));
      footer.append(dateWrap, button);
      content.append(footer);
      card.append(content);
      feed.append(card);
    });
    $("#resultCount").textContent = records.length;
    $("#emptyState").hidden = records.length > 0;
    $("#emptyState h2").textContent = saved.size
      ? "Brak zapisanych treści dla tych filtrów"
      : "Zostaw sobie coś na później";
    $("#emptyState p").textContent = saved.size
      ? "Wyczyść filtry, aby wrócić do swojej kolekcji."
      : "Dotknij zakładki na karcie. Treść będzie czekać tutaj, także offline po otwarciu tego widoku.";
    hydrate();
  }
  document.addEventListener("click", (event) => {
    const bookmark = event.target.closest("[data-bookmark]");
    if (bookmark) {
      const id = bookmark.dataset.bookmark;
      const previous = saved.get(id);
      if (previous) saved.delete(id);
      else if (items.has(id)) {
        if (saved.size >= 100) {
          toast(
            "Masz już 100 zapisanych treści. Usuń przeczytane, aby zrobić miejsce.",
          );
          return;
        }
        saved.set(id, { ...items.get(id), saved_at: new Date().toISOString() });
      }
      if (!persist("myhub.saved", [...saved.values()])) {
        if (previous) saved.set(id, previous);
        else saved.delete(id);
        hydrate();
        return;
      }
      if (savedView) renderSaved();
      else hydrate();
      toast(previous ? "Usunięto z zapisanych" : "Zapisano na później");
      return;
    }
    const link = event.target.closest(".card-link");
    if (link) {
      const id = link.closest(".card").dataset.id;
      read.delete(id);
      read.add(id);
      while (read.size > 1000) read.delete(read.values().next().value);
      persist("myhub.read", [...read]);
      hydrate();
    }
  });
  window.addEventListener("storage", (event) => {
    if (event.key === "myhub.saved") {
      const records = readStorage("myhub.saved", []);
      saved.clear();
      if (Array.isArray(records))
        records
          .filter(
            (item) => item && typeof item.id === "string" && safeUrl(item.url),
          )
          .forEach((item) => saved.set(item.id, item));
      if (savedView) renderSaved();
      else hydrate();
    }
  });
  async function loadMore() {
    const button = $("#loadMore");
    button.disabled = true;
    button.textContent = "Wczytuję…";
    try {
      const next = new URLSearchParams(params);
      next.set("page", Number(button.dataset.page) + 1);
      const response = await fetch(`/api/feed?${next}`, {
        signal: AbortSignal.timeout(15000),
      });
      if (!response.ok) throw new Error("Feed unavailable");
      const data = await response.json();
      // Same-origin, server-escaped HTML. Remove duplicates if collection ran between pages.
      const template = document.createElement("template");
      template.innerHTML = data.html;
      template.content.querySelectorAll(".card").forEach((card) => {
        if (items.has(card.dataset.id)) card.remove();
      });
      feed.append(template.content);
      data.items.forEach((item) => items.set(item.id, item));
      button.dataset.page = data.page;
      $("#pagination").hidden = !data.has_more;
      const count = data.count + (window.myhubExtraDeals || 0);
      $("#shownCount").textContent =
        `${feed.querySelectorAll(".card").length} z ${count} wpisów`;
      $("#resultCount").textContent = count;
      hydrate();
      if (response.headers.get("X-MyHub-Offline"))
        toast("Pokazuję zapisaną kopię offline");
    } catch {
      toast(
        "Nie udało się wczytać kolejnych wpisów. Spróbuj ponownie po odzyskaniu połączenia.",
      );
    } finally {
      button.disabled = false;
      button.textContent = "Pokaż więcej";
    }
  }
  $("#loadMore").addEventListener("click", loadMore);
  function connection() {
    $("#connectionStatus").textContent = navigator.onLine
      ? "Ostatnie zebranie"
      : "Offline · zapisana kopia";
    $("#statusDot").classList.toggle("warning", !navigator.onLine);
  }
  window.addEventListener("online", connection);
  window.addEventListener("offline", connection);
  if (!navigator.onLine) connection();
  async function refresh() {
    if (!navigator.onLine) {
      toast("Jesteś offline. Dostępna jest ostatnia zapisana kopia.");
      return;
    }
    $("#refreshButton").classList.add("busy");
    try {
      const response = await fetch("/health", {
        cache: "no-store",
        signal: AbortSignal.timeout(10000),
      });
      if (!response.ok || response.headers.get("X-MyHub-Offline"))
        throw new Error("Feed unavailable");
      location.reload();
    } catch {
      toast("Nie udało się odświeżyć. Spróbuj ponownie za chwilę.");
    } finally {
      $("#refreshButton").classList.remove("busy");
      $("#pullRefresh").classList.remove("visible");
    }
  }
  $("#refreshButton").addEventListener("click", refresh);
  const prefs = window.myhubPreferences;
  function densityControls() {
    const compact = prefs.density === "compact";
    $("#densityButton").textContent = compact
      ? "Widok pełny"
      : "Widok kompaktowy";
    $("#densityButton").setAttribute("aria-pressed", String(compact));
    $("#compactToggle").checked = compact;
  }
  $("#densityButton").addEventListener("click", () => {
    prefs.setDensity(prefs.density === "compact" ? "comfortable" : "compact");
    densityControls();
  });
  $("#compactToggle").addEventListener("change", (event) => {
    prefs.setDensity(event.target.checked ? "compact" : "comfortable");
    densityControls();
  });
  $("#themeSelect").value = prefs.theme;
  $("#themeSelect").addEventListener("change", (event) =>
    prefs.setTheme(event.target.value),
  );
  $("#preferencesButton").addEventListener("click", () =>
    $("#preferencesDialog").showModal(),
  );
  $("#closePreferences").addEventListener("click", () =>
    $("#preferencesDialog").close(),
  );
  $("#preferencesDialog").addEventListener("click", (event) => {
    if (
      event.target === event.currentTarget &&
      (event.clientX < event.currentTarget.getBoundingClientRect().left ||
        event.clientX > event.currentTarget.getBoundingClientRect().right ||
        event.clientY < event.currentTarget.getBoundingClientRect().top ||
        event.clientY > event.currentTarget.getBoundingClientRect().bottom)
    )
      event.currentTarget.close();
  });
  let installPrompt;
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    installPrompt = event;
    $("#installButton").hidden = false;
  });
  $("#installButton").addEventListener("click", async () => {
    if (!installPrompt) return;
    await installPrompt.prompt();
    installPrompt = null;
    $("#installButton").hidden = true;
  });
  window.addEventListener("appinstalled", () => {
    $("#installButton").hidden = true;
    toast("MyHub jest na Twoim ekranie głównym");
  });
  const sections = ["news", "reddit", "youtube", "deal"];
  let gesture;
  function resetGesture() {
    gesture = null;
    $("#pullRefresh").classList.remove("visible");
  }
  document.addEventListener(
    "touchstart",
    (event) => {
      resetGesture();
      if (
        event.touches.length !== 1 ||
        event.target.closest("input,select,button,details,dialog,.topic-chips")
      )
        return;
      const touch = event.touches[0];
      // Preserve iOS edge-back navigation and exclude saved collection from section swipes.
      gesture = {
        x: touch.clientX,
        y: touch.clientY,
        pull: false,
        top: scrollY <= 0,
        edge: touch.clientX < 24 || touch.clientX > innerWidth - 24,
      };
    },
    { passive: true },
  );
  document.addEventListener(
    "touchmove",
    (event) => {
      if (!gesture || event.touches.length !== 1) {
        resetGesture();
        return;
      }
      const dx = event.touches[0].clientX - gesture.x,
        dy = event.touches[0].clientY - gesture.y;
      if (gesture.top && scrollY <= 0 && dy > 35 && dy > Math.abs(dx) * 1.5) {
        $("#pullRefresh").classList.add("visible");
        gesture.pull = dy >= 95;
        $("#pullRefresh").textContent = gesture.pull
          ? "Puść, aby odświeżyć"
          : "Pociągnij, aby odświeżyć";
      } else {
        gesture.pull = false;
        $("#pullRefresh").classList.remove("visible");
      }
    },
    { passive: true },
  );
  document.addEventListener(
    "touchend",
    (event) => {
      if (!gesture || !event.changedTouches.length) return;
      const state = gesture;
      resetGesture();
      const dx = event.changedTouches[0].clientX - state.x,
        dy = event.changedTouches[0].clientY - state.y;
      if (state.pull && dy >= 95) {
        refresh();
        return;
      }
      if (
        savedView || document.body.dataset.view !== "feed" ||
        state.edge ||
        Math.abs(dx) < 90 ||
        Math.abs(dx) < Math.abs(dy) * 1.6
      )
        return;
      const current = sections.indexOf(document.body.dataset.section);
      const next = current + (dx < 0 ? 1 : -1);
      if (current < 0 || next < 0 || next >= sections.length) return;
      const search = new URLSearchParams(params);
      ["source", "category", "page", "view", "low"].forEach((key) =>
        search.delete(key),
      );
      if (sections[next]) search.set("section", sections[next]);
      else search.delete("section");
      location.href = `/?${search}`;
    },
    { passive: true },
  );
  document.addEventListener("touchcancel", resetGesture, { passive: true });
  if ("serviceWorker" in navigator) {
    let waitingWorker;
    let updating = false;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (updating) location.reload();
    });
    $("#updateButton").addEventListener("click", () => {
      if (waitingWorker) {
        updating = true;
        waitingWorker.postMessage({ type: "SKIP_WAITING" });
      }
    });
    window.addEventListener("load", async () => {
      try {
        const registration = await navigator.serviceWorker.register(
          "/service-worker.js",
          { scope: "/", updateViaCache: "none" },
        );
        const offerUpdate = () => {
          waitingWorker = registration.waiting;
          if (waitingWorker && navigator.serviceWorker.controller)
            $("#updateBanner").hidden = false;
        };
        offerUpdate();
        registration.addEventListener("updatefound", () => {
          const worker = registration.installing;
          worker?.addEventListener("statechange", () => {
            if (worker.state === "installed") offerUpdate();
          });
        });
        // Remove only MyHub's old registration whose /static/ scope could not control the feed.
        for (const old of await navigator.serviceWorker.getRegistrations()) {
          if (
            old.scope === `${location.origin}/static/` &&
            old.active?.scriptURL ===
              `${location.origin}/static/service-worker.js`
          )
            await old.unregister();
        }
      } catch {
        /* Online reading works even if the browser disallows service workers. */
      }
    });
  }
  dates();
  densityControls();
  if (savedView) renderSaved();
  else hydrate();
})();
