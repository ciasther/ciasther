# Co dokładnie liczy profil

**Nie jest to licznik odsłon ani oszacowanie liczby linii kodu.** Liczby pochodzą z API GitHub. Aktualizuje je workflow, a profil wyświetla zapisane SVG. Odwiedzający nie używa tokenu ani nie odpytuje API.

| Metryka | Źródło i zakres |
| :--- | :--- |
| Repozytoria publiczne | `GET /user` → `public_repos`. Własne repozytoria na koncie, w tym forki i archiwa. |
| Repozytoria prywatne | `GET /user` → `owned_private_repos`. Cały licznik własnych prywatnych repozytoriów, bez pobierania ich listy. |
| Repozytoria razem | Suma dwóch powyższych pól. Nie używa `total_private_repos`, które nie jest tożsame z własnością. |
| Contributions | `viewer.contributionsCollection.contributionCalendar.totalContributions`. Zakres od początku dnia UTC sprzed 364 dni do chwili odczytu: 365 dat kalendarzowych, wliczając dziś. |
| Dni z aktywnością | Liczba unikalnych dat z `contributionCount > 0` w tym samym zakresie. |
| Gwiazdki publiczne | Suma `stargazers_count` własnych publicznych repozytoriów. Pełna paginacja po 100 wyników; obejmuje też gwiazdki własnych forków, nie repozytoriów źródłowych. |
| Obserwujący | `GET /user` → `followers`. |

## Prywatne repozytoria a prywatna aktywność

Licznik repozytoriów prywatnych obejmuje **własność** na osobistym koncie `ciasther`. Nie dodaje repozytoriów cudzych ani organizacyjnych tylko dlatego, że masz do nich dostęp. Contributions dotyczą natomiast aktywności konta, także poza własnymi repozytoriami, w zakresie zliczonym i udostępnionym przez GitHub.

Do prywatnego kalendarza wymagane są token `read:user` oraz odpowiednie ustawienie **Private contributions**. Generator nie potrafi wiarygodnie odróżnić całkowitego braku kwalifikującej się prywatnej aktywności od wyłączenia jej udostępniania, kiedy API zwraca same zera. Nie deklaruje, że ten przełącznik został automatycznie zweryfikowany.

`restrictedContributionsCount` służy wyłącznie kontroli spójności odpowiedzi. **Nie dodajemy go do `totalContributions`**, ponieważ groziłoby to ponownym zliczeniem prywatnego wkładu. Nie nazywamy contributions commitami: GitHub uwzględnia również inne rodzaje aktywności.

Kalendarz nie jest odpowiednikiem `git log --all`. Obowiązują zasady GitHub dotyczące autorstwa, powiązania adresu e-mail z kontem, odpowiednich gałęzi i rodzajów wkładu. Nie obejmuje całej pracy lokalnej, nieopublikowanych gałęzi czy aktywności w innych serwisach. Nie jest miarą jakości, liczby przepracowanych godzin ani produktywności.

## Co jest publiczne

`assets/stats.json`, SVG i tabela w README zawierają tylko zatwierdzone agregaty oraz zakres i czas odczytu. Codzienne agregaty pozostają też w publicznej historii Git — ich zmiany mogą wskazywać, że trwała praca lub powstało repozytorium. To zamierzony skutek publicznego licznika.

Generator nie pobiera listy prywatnych repozytoriów, commitów, kodu, gałęzi ani członków organizacji. Odpowiedź `/user` może zawierać inne prywatne informacje konta; skrypt odczytuje z niej tylko login do kontroli oraz trzy liczniki, a całej odpowiedzi nie zapisuje i nie wypisuje. Daty dzienne z GraphQL są przetwarzane wyłącznie w pamięci, aby policzyć aktywne dni.

Do odczytu służy dedykowany PAT classic **wyłącznie `read:user`**. Do zapisu gotowych plików workflow używa innego tokenu: krótkotrwałego `GITHUB_TOKEN` z `contents: write` w samym repozytorium profilu. Pull requesty uruchamiają wyłącznie testy, bez sekretu. Nie stosujemy `pull_request_target`, pobierania obcego kodu z tokenem ani zewnętrznego hostingu kart.

To nadal sekret: `read:user` daje dostęp do prywatnych danych profilu. Nie udostępniaj go innym osobom. Główne ryzyko ograniczamy przez brak uprawnień do prywatnego kodu i brak uprawnień zapisu w tym tokenie.

## Pierwszy start i awarie

Dostarczona paczka zawiera `null`, a widok wyświetla `—`. Nie zawiera zmyślonych wyników. Dopiero `--fetch` z prawidłowym tokenem tworzy prawdziwy odczyt. Braki danych, zły zakres tokenu, niezgodny użytkownik, niepełny JSON, błędy GraphQL i niespójna paginacja przerywają aktualizację przed zapisem.

Dokumentacja producenta: [GET /user](https://docs.github.com/en/rest/users/users#get-the-authenticated-user), [ContributionsCollection](https://docs.github.com/en/graphql/reference/users#contributionscollection), [ustawienia prywatnych contributions](https://docs.github.com/en/account-and-profile/how-tos/contribution-settings/manage-visibility-settings-for-private-contributions-and-achievements), [co GitHub uznaje za contributions](https://docs.github.com/en/account-and-profile/reference/profile-contributions-reference).
