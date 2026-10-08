# MyHub

Personal gaming + technology information hub built as a Flask PWA.

## Aplikacja

MyHub łączy newsy, Reddit, YouTube i okazje w jednym feedzie dostosowanym do iPhone'a i większych ekranów.

- Wyszukiwanie całego feedu po tytule, opisie, źródle i tagach, również bez polskich znaków.
- Łączone filtry języka, kategorii i źródła; sortowanie od najnowszych lub dopasowanych.
- Stronicowanie po 36 wpisów zamiast obcinania wyników do 120.
- Zapisywanie do 100 treści na później, oznaczenie przeczytania, motyw jasny/ciemny/systemowy i widok kompaktowy.
- Dolna nawigacja, gesty przełączania sekcji i pull-to-refresh, z uwzględnieniem iOS safe area.
- Offline dla wcześniej odwiedzonych widoków. Nieodwiedzony filtr pokazuje ekran offline, zamiast wyników z innego filtra. Ceny w zapisanych treściach są kopią z momentu zapisu.

Zakładki, historia przeczytania i ustawienia są przechowywane lokalnie w przeglądarce. Nie synchronizują się między urządzeniami i mogą zniknąć po usunięciu danych witryny. Odświeżenie aplikacji pobiera ostatni feed; nowe dane zbiera osobno GitHub Actions.

## Uruchomienie i weryfikacja

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt -r collector-requirements.txt
python -m flask --app app run --port 5056
```

W drugim terminalu z aktywnym środowiskiem:

```bash
python -m unittest discover -s tests -v
npm ci
npx playwright install chromium webkit
npm test
```

Testy backendu i collectora używają lokalnych danych i mocków, bez kluczy API. Testy przeglądarkowe obejmują Chromium, mobilny WebKit, zapisane treści, wyszukiwanie, układ, ustawienia i cache offline. Tryb offline service workera jest sprawdzany w Chromium; zachowanie zainstalowanej PWA na fizycznym iPhonie wymaga osobnego sprawdzenia. Zrzuty ekranu i ślady nieudanych testów trafiają do `test-results/`.

## Pliki i wdrożenie

Backend to `app.py`, szablony kart to `templates/_cards.html`, a interakcje i ustawienia znajdują się w `static/js/`. PWA rejestruje `/service-worker.js` ze scope `/`. Wersja `APP_VERSION` w backendzie musi odpowiadać `VERSION` w service workerze; po zmianie zasobów podbij obie. Istniejąca sesja proponuje odświeżenie po instalacji nowego workera.

`/health` podaje liczbę wpisów, czas zebrania i wersję aplikacji. Jeśli feed jest nieprawidłowy, zwraca HTTP 503, a aplikacja korzysta z ostatniej poprawnej kopii dostępnej w procesie. Plik jest odczytywany ponownie tylko po zmianie jego sygnatury.

`.github/workflows/check.yml` uruchamia testy przy pull requestach. `.github/workflows/collect.yml` sprawdza kontrakty, zbiera dane, wysyła cały katalog szablonów i zasobów do PythonAnywhere, przeładowuje aplikację i sprawdza dostępność. Zmiany na osobnej gałęzi nie wdrażają się na produkcję. Po scaleniu zmian kodu, zasobów lub konfiguracji źródeł na `main` uruchamia się deploy; kolejne wdrożenia wykonuje także harmonogram. Sam commit `data/feed.json` nie uruchamia ponownie kolektora.

Przy ograniczaniu wielkości feedu wszystkie świeżo zweryfikowane, aktywne okazje i ceny obserwowanych gier zachowują swoje miejsce, także przy starej dacie publikacji albo niezmienionej cenie. Pozostałe miejsca do celu 450 wpisów zajmują najnowsze trafne treści. Jeśli aktywnych okazji jest więcej niż 450, zachowywane są wszystkie.

Ikony PNG dla Androida i iOS są zapisane w repozytorium. Po zmianie `static/icon.svg` odtwórz je przez `npm run icons`.

# MyHub – lista obserwowanych gier

Lista cen GG.deals jest w pliku `data/game_watchlist.json`.

## Jak dodać grę

1. Otwórz stronę gry na Steam.
2. W adresie znajdź liczbę po `/app/`. Przykład: `store.steampowered.com/app/1868140/DAVE_THE_DIVER/` → Steam App ID to `1868140`.
3. Otwórz `data/game_watchlist.json` na GitHubie i kliknij ikonę ołówka. Plik zawiera obiekt z tablicą `games`.
4. Przed końcowym `]` tablicy `games` dodaj wpis (pamiętaj o przecinku między grami):

```json
{
  "name": "Nazwa gry",
  "steam_app_id": 1868140,
  "platform": "pc"
}
```

5. Kliknij **Commit changes**. Kolejny przebieg kolektora pobierze cenę z GG.deals.

## Xbox Play Anywhere

Jeżeli gra jest oficjalnie oznaczona jako Xbox Play Anywhere, zamiast `"pc"` wpisz (obsługiwane jest też dotychczasowe `"xbox_play_anywhere": true`):

```json
"platform": "xbox_play_anywhere"
```

To pole opisuje obserwowaną grę, ale ceny pobierane przez Steam App ID dotyczą ofert PC. MyHub nie przypisuje im uprawnień Xbox Play Anywhere. Cross-buy trzeba potwierdzić dla konkretnej oferty w sklepie Xbox/Windows.

## Cena docelowa (opcjonalnie)

Możesz dodać np.:

```json
"target_price": 50
```

Gdy aktualne minimum spadnie do 50 zł lub niżej, gra dostanie priorytet.

## Jak usunąć grę

Usuń cały obiekt gry z `game_watchlist.json`, pilnując poprawnych przecinków między pozostałymi wpisami.

## Zasady naszej listy

Preferujemy gry PC i Xbox Play Anywhere, szczególnie dobrze pasujące do handheldów. Nie dodajemy FPS-ów ani RTS-ów. Dla GG.deals kluczowym identyfikatorem jest `steam_app_id`, dlatego nie zmieniaj go na Xbox Store ID.

## Osobiste centrum gier i sprzętu

- Start przeplata News, Reddit, YouTube i kwalifikujące się okazje. Identyczne tytuły są grupowane z linkami do innych źródeł; pełne listy pozostają w sekcjach. Licznik od ostatniej wizyty korzysta z `first_seen_at`, a data na karcie nadal jest datą źródła.
- Wyszukiwanie jest domyślnie zwinięte; aktywne zapytanie otwiera pole automatycznie.
- Okazje pokazują tylko aktywne, zweryfikowane ceny osiągające próg lub minimum historyczne dostępne teraz. Samo dopasowanie keyworda nie kwalifikuje oferty. Własne progi są lokalne i dodają pasujące oferty na urządzeniu, bez wysyłania preferencji do serwera.
- `/?view=games` pokazuje katalog z `data/game_watchlist.json`; `&game=STEAM_ID` otwiera cenę, historię i wzmianki. Półka, notatki, nastrój i długość sesji są zapisane lokalnie w `myhub.games`. Wybór gry na 30 minut opiera się na oznaczeniach użytkownika, bez automatycznego zgadywania posiadania lub wydajności.
- Steam `GetNewsForApp/v2` zbiera do dwóch komunikatów twórców z ostatnich 60 dni na grę, przez collector w Actions. Brak komunikatów lub błąd źródła nie jest potwierdzeniem braku aktualizacji. Nowy komunikat po odłożeniu gry pojawia się w bibliotece; nie oznacza automatycznie naprawienia problemu.
- `data/price_history.json` zapisuje wyłącznie rzeczywiste, zweryfikowane obserwacje GG.deals, oddzielnie oficjalne sklepy i keyshopy. Niezmienione ceny aktualizują czas ostatniej weryfikacji; zmiany tworzą punkt. Zachowujemy 120 punktów na grę. To nie jest kompletna historia rynku; minimum GG.deals pozostaje osobnym polem. Workflow commituje i wdraża feed, historię oraz katalog gier.
- `/?view=hardware` zawiera własny profil urządzenia, radar handheldów i dziennik do 200 pomiarów (`myhub.device`, `myhub.tests`). FPS i limit APU wpisuje użytkownik; nie są automatycznymi benchmarkami. Edycja zachowuje pierwotne urządzenie pomiaru; usunięcie można cofnąć.
- Eksport JSON (schema 1) obejmuje półkę, progi, sprzęt, pomiary i zapisane treści. Import do 2 MB łączy nowsze oznaczenia i waliduje identyfikatory, limity oraz URL-e. Przekroczenie limitu kończy import bez zmian; nie są usuwane starsze dane, aby zmieścić kopię.
- Odwiedzone karty gier i centrum sprzętu działają z dokładnej kopii offline. Lokalne dane nie są automatycznie synchronizowane. Po wyczyszczeniu danych przeglądarki odtwórz je z eksportu.

Testy przeglądarkowe uruchamiają `tests/serve.py` z tymczasowym, powtarzalnym feedem i historią. Nie zmieniają produkcyjnych plików danych i nie zależą od aktualnych promocji. Przegląd produkcji należy wykonać dodatkowo po wdrożeniu.
