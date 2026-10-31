# Plan workflow n8n: nowe ogłoszenia Librus

Dokument opisuje docelowy przepływ n8n dla ogłoszeń pobieranych z kont Tosia
i Dorota. Jedno ogłoszenie widoczne na obu kontach ma być zapisane raz i
wysłane w jednym e-mailu. Ogłoszenia widoczne tylko na jednym koncie również
mają być obsługiwane.

## Co zwraca obecny skrypt

[get_unread_announcements.py](./get_unread_announcements.py) zwraca JSON w tej
postaci:

```json
{
  "announcements": [
    {
      "title": "Tytuł",
      "author": "Autor",
      "description": "Treść",
      "date": "Data z Librusa"
    }
  ]
}
```

Wynik nie zawiera konta, stabilnego ID, flagi przeczytania, hashy ani
znaczników czasu. Nazwy i dodatkowe wartości potrzebne DataTable tworzy n8n.
Pole `date` należy tam zmapować na `announcement_date`.

## DataTable z ogłoszeniami

Utwórz jedną tabelę, na przykład `librus_announcements`, z jednym wierszem na
kanoniczne ogłoszenie:

| Kolumna | Typ | Znaczenie |
|---|---|---|
| `dedupe_key` | String/Text | Klucz używany do znalezienia i aktualizacji istniejącego ogłoszenia. |
| `title` | String/Text | Tytuł z Librusa. |
| `author` | String/Text | Autor z Librusa. |
| `announcement_date` | String/Text | Data zwrócona przez Librusa; pozostaw jako tekst, dopóki jej format nie będzie pewnie parsowany. |
| `description` | String/Text | Wspólna treść ogłoszenia. |
| `seen_by_tosia` | Boolean | Czy ogłoszenie pojawiło się w pobraniu z konta Tosia. |
| `seen_by_dorota` | Boolean | Czy ogłoszenie pojawiło się w pobraniu z konta Dorota. |
| `content_hash` | String/Text | Hash aktualnego zestawu pól ogłoszenia, w tym treści. |
| `emailed_hash` | String/Text | Hash wersji, której e-mail został już wysłany albo która została uwzględniona w bazie początkowej. |
| `first_seen_at` | DateTime | Czas pierwszego zapisania ogłoszenia. |
| `last_seen_at` | DateTime | Czas ostatniego pobrania ogłoszenia. |
| `last_emailed_at` | DateTime | Czas ostatniego e-maila dla ogłoszenia; puste przed wysłaniem. |

Znaczniki czasu zapisuj jako DateTime w UTC. Flagi `seen_by_*` oznaczają, że
ogłoszenie kiedykolwiek pojawiło się na danym koncie; ustawiaj je na `true`,
gdy dane konto je zwróci (nie zeruj flagi, gdy w późniejszym odczycie wpisu
brakuje).

Opcjonalnie utwórz drugą tabelę `librus_workflow_state`, np. z kolumnami
`key` (String/Text) i `value` (String/Text), jeżeli zamiast ręcznego przełącznika
w workflow chcesz trwale przechowywać stan inicjalizacji (`baseline_complete`).

## Klucz do deduplikacji i hash treści

`librus_apix` nie zwraca stabilnego ID. Praktyczny klucz `dedupe_key` można
wyliczyć jako SHA-256 z tytułu, autora i daty po normalizacji:

1. Usuń białe znaki z początku i końca.
2. Zamień wielokrotne białe znaki na pojedynczą spację.
3. Ujednolić wielkość liter.
4. Połącz znormalizowane wartości tytułu, autora i daty separatorem, który nie
   występuje w danych, a następnie oblicz SHA-256.

Nie dodawaj opisu do `dedupe_key`: zmiana treści ma aktualizować istniejący
wiersz, a nie tworzyć nowy. `content_hash` oblicz oddzielnie z tytułu, autora,
daty i opisu. Wykryje wtedy zmianę treści dla tego samego klucza.

To heurystyka, nie gwarantowana tożsamość: dwa różne ogłoszenia z takim samym
tytułem, autorem i datą mogą zostać scalone. Jeśli w praktyce znajdziesz taki
przypadek, trzeba dodać do klucza kolejne pole lub inaczej rozróżniać rekordy.

## Przepływ workflow

1. **Schedule Trigger** uruchamia cykl.
2. Dla każdego konta uruchom istniejący GitHub Actions workflow osobno,
   przekazując `who` (`Tosia` lub `Dorota`) oraz `resumeUrl` webhooka n8n.
   Obecny workflow obsługuje konto przez `repository_dispatch` z payloadem
   `who` i `resumeUrl` ([workflow](./.github/workflows/get-unread-announcements.yml)).
3. Rozróżnij callbacki, np. przekazując osobny URL webhooka dla każdego konta
   albo dodając `runId` i `who` do query string `resumeUrl`. Obecny GitHub
   workflow przekazuje callbackowi JSON z ogłoszeniami, ale nie dołącza do
   payloadu `who`; n8n musi więc zachować konto i przebieg po stronie URL lub
   innego kontekstu uruchomienia.
4. Zachowaj wyniki dla obu kont pod tym samym `runId` i poczekaj na oba udane
   pobrania przed scaleniem oraz wysyłką. Dopiero wtedy ustaw flagi źródłowe i
   zastosuj regułę inicjalizacji.
5. Rozłącz tablicę `announcements` na osobne elementy. Dodaj do każdego elementu
   konto źródłowe, `dedupe_key`, `content_hash` i czas UTC `now`.
6. Zbierz oba zestawy i pogrupuj po `dedupe_key`. Dla wspólnego wpisu zachowaj
   jeden rekord, ustaw obie flagi `seen_by_*` na `true` i nie wysyłaj dwóch
   e-maili. Dla wpisu z jednego konta ustaw tylko odpowiednią flagę.
7. Dla każdego scalonego wpisu odczytaj wiersz DataTable po `dedupe_key`:
   - Jeśli nie istnieje, przygotuj nowy wiersz.
   - Jeśli istnieje, zaktualizuj treść, `content_hash`, flagi widoczności oraz
     `last_seen_at`; zachowaj `first_seen_at`.
8. Jeśli tryb inicjalny jest aktywny, zapisz wszystkie rekordy jako bazę
   początkową, ustaw `emailed_hash = content_hash`, nie wysyłaj e-maili i nie
   włączaj trybu normalnego, dopóki oba pobrania nie zakończą się sukcesem.
9. Po inicjalizacji wyślij pojedynczy e-mail, jeśli rekord jest nowy lub
   `content_hash` różni się od `emailed_hash`. Po **udanym** wysłaniu zaktualizuj
   `emailed_hash = content_hash` i `last_emailed_at`. Po błędzie wysyłki nie
   zmieniaj `emailed_hash`, aby następny przebieg mógł ponowić powiadomienie.
10. Gdy hash treści się nie zmienił, nie wysyłaj ponownie e-maila; nadal
   aktualizuj `last_seen_at` i flagi `seen_by_*`.

Skonfiguruj przebiegi tak, aby nie nakładały się równolegle. DataTable nie
powinien być traktowany jako mechanizm gwarantujący unikalność
`dedupe_key` przy dwóch jednoczesnych zapisach.

## Pierwsze uruchomienie

Pierwsze uruchomienie ma tylko zbudować bazę i nie wysyłać maili ze starszymi
ogłoszeniami. Najprościej użyć przełącznika trybu inicjalnego w workflow albo
wartości `baseline_complete` w osobnej tabeli stanu. Po pobraniu obu kont
sprawdź tabelę, następnie oznacz inicjalizację jako zakończoną. Nie włączaj
normalnego wysyłania po sukcesie tylko jednego konta — inaczej starsze
ogłoszenia z drugiego konta mogą zostać omyłkowo wysłane jako nowe.

## Test przed włączeniem cyklicznym

- Pierwszy test tworzy wiersze z obu kont, ale nie wysyła maili.
- Wspólny wpis ma jeden wiersz, dwie flagi `seen_by_*` i nie powoduje
  powielonego e-maila.
- Wpis widoczny na jednym koncie ma tylko jego flagę.
- Kolejne pobranie bez zmian nie wysyła ponownego e-maila.
- Nowe ogłoszenie powoduje jeden e-mail i jeden wiersz.
- Zmieniona treść aktualizuje istniejący wiersz i wysyła e-mail z aktualizacją.
- Nieudana wysyłka nie oznacza wersji jako wysłanej.
