# MyHub — zasady pracy nad projektem

Ten plik jest stałym kontekstem dla kolejnych sesji pracy nad MyHub. Przed wprowadzaniem zmian przeczytaj go oraz sprawdź aktualny stan repozytorium — nie zakładaj, że opis poniżej zastępuje bieżący kod.

## Sposób pracy

- Użytkownik opisuje problem lub funkcję zwykle na podstawie działania PWA na iPhonie i często dołącza screenshot.
- Najpierw sprawdź aktualne pliki w repozytorium i, jeśli problem dotyczy danych lub collectora, także aktualny `data/feed.json` oraz logi ostatniego GitHub Actions.
- Nie zgaduj stanu aplikacji na podstawie poprzedniej rozmowy. Repozytorium jest źródłem prawdy.
- Jeśli przyczyna jest jasna, wprowadzaj poprawkę bez odsyłania użytkownika do ręcznej edycji plików.
- Po zmianie sprawdź zależności między frontendem, backendem, collectorem i workflow. Unikaj poprawki jednego miejsca, która łamie drugie.
- Przy błędach parserów preferuj brak danych zamiast danych niepewnych. Szczególnie ceny ofert nie mogą być zgadywane.
- Zmiany rób małymi, opisowymi commitami. Przy większej zmianie można rozdzielić frontend/backend/collector na osobne commity.
- Po wdrożeniu krótko wyjaśnij użytkownikowi: co było przyczyną, co zmieniono i czego oczekiwać po następnym runie.
- Nie deklaruj, że coś działa, dopóki nie zostało potwierdzone logiem, wynikiem collectora lub danymi po deployu. Jeśli to dopiero test, nazwij to testem.

## Repozytorium i deploy

- Repo: `MikolajGrzelak/MyHub`, branch domyślny: `main`.
- Produkcja: PythonAnywhere, `MyHub.pythonanywhere.com`.
- GitHub Actions zbiera dane, zapisuje `data/feed.json`, wysyła pliki do PythonAnywhere, przeładowuje aplikację i sprawdza `/health`.
- Główny workflow: `.github/workflows/collect.yml`.
- Harmonogram GitHub Actions bywał problematyczny. Zanim zmienisz scheduler, sprawdź eventy ostatnich runów (`schedule`, `workflow_dispatch`, `push`) i logi.
- W repo może istnieć tymczasowy trigger `push` ograniczony do zmian workflow, używany do wdrożeń bez ręcznego `workflow_dispatch`. Sprawdź jego aktualny stan przed użyciem.
- Użytkownik nie zawsze ma pod ręką urządzenie z GitHub Authenticator, więc jeśli autoryzowane narzędzia GitHub pozwalają wykonać potrzebną zmianę/deploy bez jego ręcznego logowania, preferuj tę drogę.
- Nie obiecuj uruchomienia `workflow_dispatch`, jeśli dostępne narzędzie GitHub nie ma takiej operacji.

## Architektura

- Flask: `app.py`.
- UI: `templates/index.html`, `static/css/app.css`.
- PWA: `static/manifest.json`, `static/service-worker.js`.
- Collector: przede wszystkim `collectors/rss.py`.
- Źródła/konfiguracja feedów: `feeds.py`.
- Dane: `data/feed.json`.
- Słowa kluczowe ofert: `data/deal_keywords.json`.
- Collector uruchamia się w GitHub Actions, ponieważ PythonAnywhere Free ma ograniczenia outbound.
- Gemini służy do polskich streszczeń angielskich newsów. Redditu nie tłumaczymy — pokazujemy oryginalny tekst autora.

## UI / UX

- Aplikacja jest mobile-first i głównym urządzeniem jest iPhone jako PWA.
- Dolna nawigacja: Start, News, Reddit, YouTube, Okazje.
- Użytkownik chce możliwie natywne, „aplikacyjne” zachowanie.
- Obsługujemy swipe lewo/prawo między głównymi sekcjami oraz pull-to-refresh.
- Zwracaj szczególną uwagę na iOS safe area, Dynamic Island/status bar i dolny home indicator.
- Nie dodawaj sticky elementów u góry, które mogą wejść pod status bar albo zasłaniać filtry. Po zmianach PWA pamiętaj o cache service workera; jeśli CSS/JS może być trzymany przez stary cache, podbij wersję cache.
- Daty mają być absolutne w formacie typu `24.09, 14:41`, na podstawie czasu publikacji źródła, a nie czasu pobrania.
- Filtr źródeł jest grupowany według typu: News, Reddit, YouTube, Okazje. W konkretnej sekcji pokazuj odpowiednie źródła.
- Całe karty mają być wygodne do kliknięcia na telefonie.

## Okazje / Pepper

- Pepper i ŁowcyChin są źródłami ofert.
- Pokazujemy tylko aktywne oferty; wygasłe mają znikać.
- Priorytetem jest wiarygodność. Nigdy nie przypisuj ceny znalezionej „gdzieś na stronie” do konkretnej oferty.
- Historycznie scraping HTML Peppera mylił cenę bieżącą z przekreśloną albo z cenami rekomendowanych ofert. Nie wracaj do globalnego regexu po całej stronie.
- Próbowaliśmy nieoficjalnego GraphQL Peppera. Zwraca strukturalne pola ceny/statusu, ale w teście dał tylko małe okno najnowszych ofert, przez co nie nadaje się samodzielnie do discovery po naszych keywordach.
- Aktualny kierunek to hybryda: discovery ofert po keywordach przez wyszukiwanie Peppera, a GraphQL wyłącznie do wzbogacenia po dokładnym `threadId`. Jeżeli dokładnej oferty nie da się zweryfikować w danych strukturalnych, cena ma pozostać pusta.
- Przy regresji cen testuj konkretne znane przykłady i porównuj `data/feed.json` z ofertą źródłową. Nie rozszerzaj regexów w ciemno.

## Reddit / YouTube / News

- Reddit: aktywne m.in. r/LegionGo, r/Vibecoding, r/Age_30_plus_Gamers, r/Steamdeck. Tekst pozostaje w oryginale.
- YouTube: monitorowana jest lista kanałów technologicznych/gamingowych zdefiniowana w projekcie; przed zmianą listy sprawdź aktualny kod/konfigurację.
- News: źródła polskie i angielskie; angielskie newsy mogą być streszczane przez Gemini po polsku.
- „Dla Ciebie”/priorytet bazuje m.in. na dopasowanych keywordach.

## Debugowanie

1. Odtwórz problem na podstawie screena/opisu i sprawdź bieżący kod.
2. Dla problemów z danymi sprawdź konkretny rekord w `data/feed.json`.
3. Dla collectora sprawdź log ostatniego workflow, nie tylko jego zielony/czerwony status.
4. Ustal, czy błąd powstaje przy discovery, parsowaniu, merge, renderowaniu czy cache/deployu.
5. Wprowadź najmniejszą poprawkę usuwającą przyczynę.
6. Jeśli zmiana dotyczy PWA CSS/JS, uwzględnij service-worker cache.
7. Po runie zweryfikuj wynik w wygenerowanym feedzie/logu zamiast zakładać sukces.

## Preferencje użytkownika

- Rozmowa po polsku.
- Konkretne działanie jest lepsze niż długa instrukcja ręcznej edycji.
- Użytkownik dobrze radzi sobie technicznie, ale oczekuje, że przy dostępie do repo asystent sam sprawdzi kod, logi i wdroży poprawkę.
- Krótkie podsumowanie po zmianie jest wystarczające; szczegóły techniczne podawaj wtedy, gdy pomagają zrozumieć problem lub podjąć decyzję.
