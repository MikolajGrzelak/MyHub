# MyHub

Personal gaming + technology information hub built as a Flask PWA.

## MVP
- Flask web app
- installable PWA shell
- mobile-first feed UI
- foundation for RSS/Reddit collectors and push notifications

# MyHub – lista obserwowanych gier

Lista cen GG.deals jest w pliku `data/game_watchlist.json`.

## Jak dodać grę

1. Otwórz stronę gry na Steam.
2. W adresie znajdź liczbę po `/app/`. Przykład: `store.steampowered.com/app/1868140/DAVE_THE_DIVER/` → Steam App ID to `1868140`.
3. Otwórz `data/game_watchlist.json` na GitHubie i kliknij ikonę ołówka.
4. Przed końcowym `]` dodaj wpis (pamiętaj o przecinku między grami):

```json
{
  "name": "Nazwa gry",
  "steam_app_id": 1868140,
  "platform": "pc"
}
```

5. Kliknij **Commit changes**. Kolejny przebieg kolektora pobierze cenę z GG.deals.

## Xbox Play Anywhere

Jeżeli gra jest oficjalnie oznaczona jako Xbox Play Anywhere, zamiast `"pc"` wpisz:

```json
"platform": "xbox_play_anywhere"
```

MyHub pokaże wtedy etykietę **Xbox + PC · Play Anywhere**.

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
