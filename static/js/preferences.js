(() => {
  const root = document.documentElement;
  let theme = "dark";
  let density = "comfortable";
  try {
    theme = localStorage.getItem("myhub.theme") || theme;
    density = localStorage.getItem("myhub.density") || density;
  } catch {
    /* Storage can be disabled; keep usable defaults. */
  }
  const media = matchMedia("(prefers-color-scheme: light)");
  const apply = () => {
    root.dataset.theme =
      theme === "system" ? (media.matches ? "light" : "dark") : theme;
    root.dataset.density = density;
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute(
        "content",
        root.dataset.theme === "light" ? "#f5f5fa" : "#0c0d12",
      );
  };
  window.myhubPreferences = {
    get theme() {
      return theme;
    },
    get density() {
      return density;
    },
    setTheme(value) {
      theme = ["dark", "light", "system"].includes(value) ? value : "dark";
      try {
        localStorage.setItem("myhub.theme", theme);
      } catch {}
      apply();
    },
    setDensity(value) {
      density = value === "compact" ? "compact" : "comfortable";
      try {
        localStorage.setItem("myhub.density", density);
      } catch {}
      apply();
    },
  };
  media.addEventListener("change", apply);
  apply();
})();
