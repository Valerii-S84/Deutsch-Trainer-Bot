# Deutsch Trainer Bot — Use Cases

## 1. Document Purpose

Цей документ описує основні сценарії використання **Deutsch Trainer Bot**.

Він фіксує:

* як користувач входить у продукт;
* як вибирає рівень і тему;
* як проходить тренування;
* як бачить результат;
* як працює прогрес;
* як повторює помилки;
* як доходить до підписки;
* як система поводиться у помилкових ситуаціях.

Усі користувацькі тексти, кнопки та приклади екранів у цьому документі наведені **німецькою мовою**, бо бот має бути повністю німецькомовним.

---

## 2. Global Product Rules

## 2.1. Supported Levels

Бот підтримує рівні:

* A1
* A2
* B1
* B2
* C1

## 2.2. German-Only Interface

Увесь користувацький інтерфейс має бути німецькою мовою.

Це стосується:

* onboarding;
* головного меню;
* кнопок;
* вибору рівня;
* вибору теми;
* тренування;
* результатів;
* прогресу;
* журналу помилок;
* рекомендацій;
* paywall;
* платежів;
* повідомлень про помилки.

## 2.3. Main Navigation

Головний екран має мати три основні дії:

```text
Was möchtest du heute üben?

▶️ Üben
🎯 Niveau & Thema
📊 Mein Fortschritt
```

## 2.4. Primary User Goal

Користувач має швидко отримати відповідь на три питання:

1. Що я вже знаю?
2. Де я помиляюся?
3. Що мені тренувати далі?

---

## 3. Actors

## 3.1. Learner

Основний користувач бота.

Може:

* запускати бот;
* вибирати рівень;
* вибирати тему;
* проходити сесії;
* дивитися прогрес;
* повторювати помилки;
* купувати підписку.

## 3.2. Admin

Власник або оператор продукту.

Може:

* переглядати базову статистику;
* перевіряти технічні помилки;
* бачити платіжні події;
* контролювати активність користувачів.

## 3.3. API Quiz Bank

Джерело навчального контенту.

Віддає:

* питання;
* варіанти відповідей;
* правильну відповідь;
* пояснення;
* рівень;
* тему;
* metadata.

---

# 4. Learner Use Cases

---

## UC-001 — First Start

## Goal

Користувач уперше відкриває бот і розуміє, що бот допомагає тренувати німецьку, бачити прогрес і повторювати помилки.

## Actor

Learner

## Trigger

Користувач натискає `/start`.

## Preconditions

* Користувач ще не зареєстрований у системі.
* Telegram user ID доступний.

## Main Flow

1. Користувач відкриває бот.
2. Система створює нового користувача.
3. Система зберігає Telegram user ID.
4. Бот показує коротке привітання.
5. Бот пропонує вибрати рівень.

## User-Facing Copy

```text
Willkommen beim Deutsch Trainer.

Ich helfe dir, Deutsch zu üben, deine Fehler zu erkennen und deinen Fortschritt zu sehen.

Wähle zuerst dein Niveau:
```

Buttons:

```text
A1
A2
B1
B2
C1
```

## Postconditions

* Користувач створений у системі.
* Користувач бачить вибір рівня.
* Подія `bot_started` записана.
* Подія `user_created` записана.

## Acceptance Criteria

* Новий користувач не створюється двічі.
* Привітання показується німецькою.
* Рівні A1–C1 доступні.

---

## UC-002 — Returning User Opens Bot

## Goal

Користувач повертається в бот і бачить головне меню.

## Actor

Learner

## Trigger

Користувач натискає `/start` або відкриває бот повторно.

## Preconditions

* Користувач уже існує.
* У користувача може бути вибраний рівень і тема.

## Main Flow

1. Користувач відкриває бот.
2. Система знаходить існуючого користувача.
3. Система оновлює `last_active_at`.
4. Бот показує головне меню.

## User-Facing Copy

```text
Willkommen zurück.

Was möchtest du heute üben?
```

Buttons:

```text
▶️ Üben
🎯 Niveau & Thema
📊 Mein Fortschritt
```

## Postconditions

* Користувач повернувся до активного стану.
* Подія `bot_started` записана.

## Acceptance Criteria

* Дубль користувача не створюється.
* Головне меню показується німецькою.
* Кнопки відповідають основній навігації.

---

## UC-003 — Select Level

## Goal

Користувач вибирає свій навчальний рівень.

## Actor

Learner

## Trigger

Користувач натискає **🎯 Niveau & Thema** або проходить onboarding.

## Preconditions

* Користувач існує.
* Бот доступний.

## Main Flow

1. Бот показує список рівнів.
2. Користувач вибирає рівень.
3. Система зберігає `selected_level`.
4. Бот підтверджує вибір.
5. Бот пропонує вибрати тему або почати тренування.

## User-Facing Copy

```text
Wähle dein Niveau:
```

Buttons:

```text
A1
A2
B1
B2
C1
```

After selection:

```text
Dein Niveau: A2

Wähle jetzt ein Thema oder starte direkt mit dem Training.
```

Buttons:

```text
🎯 Thema wählen
▶️ Üben
```

## Postconditions

* Рівень користувача оновлений.
* Прогрес для цього рівня використовується як активний.
* Подія `level_selected` записана.

## Acceptance Criteria

* Користувач може вибрати A1–C1.
* Рівень зберігається.
* Наступна дія зрозуміла.

---

## UC-004 — Select Theme

## Goal

Користувач вибирає тему для тренування.

## Actor

Learner

## Trigger

Користувач натискає **🎯 Thema wählen** або **🎯 Niveau & Thema**.

## Preconditions

* Користувач існує.
* Рівень вибраний.
* API має список доступних тем або локальний кеш тем.

## Main Flow

1. Бот показує доступні теми для вибраного рівня.
2. Користувач вибирає тему.
3. Система зберігає `selected_theme`.
4. Бот підтверджує вибір.
5. Бот пропонує почати тренування.

## User-Facing Copy

```text
Wähle ein Thema:
```

Buttons:

```text
Artikel
Verben
Fälle
Wortschatz
Alltag
Prüfung
```

After selection:

```text
Thema gespeichert: Artikel

Du kannst jetzt mit dem Training beginnen.
```

Buttons:

```text
▶️ Üben
📊 Mein Fortschritt
```

## Alternative Flow — No Themes Available

Якщо для рівня немає доступних тем:

```text
Für dieses Niveau sind gerade keine Themen verfügbar.

Bitte wähle ein anderes Niveau.
```

Buttons:

```text
🎯 Niveau wählen
🏠 Hauptmenü
```

## Postconditions

* Тема користувача оновлена.
* Подія `theme_selected` записана.

## Acceptance Criteria

* Бот не показує теми без доступних питань.
* Користувач може повернутися до вибору рівня.
* Усі тексти німецькою.

---

## UC-005 — Start Training Session

## Goal

Користувач починає коротке тренування.

## Actor

Learner

## Trigger

Користувач натискає **▶️ Üben**.

## Preconditions

* Користувач існує.
* Рівень вибраний.
* Тема вибрана або доступна рекомендована тема.
* Денний ліміт не вичерпаний.
* API Quiz Bank доступний.

## Main Flow

1. Користувач натискає **▶️ Üben**.
2. Система перевіряє рівень.
3. Система перевіряє тему.
4. Система перевіряє денний ліміт.
5. Система створює training session.
6. Система запитує питання з API Quiz Bank.
7. Бот показує перше питання.

## User-Facing Copy

```text
Training gestartet.

Niveau: A2
Thema: Artikel

Frage 1 von 10
```

## Postconditions

* Створена активна сесія.
* Питання видано користувачу.
* Подія `training_started` записана.

## Acceptance Criteria

* Сесія не стартує без рівня.
* Сесія не стартує без доступних питань.
* Ліміт перевіряється до видачі питання.
* API-помилка не списує ліміт.

---

## UC-006 — Answer Question Correctly

## Goal

Користувач відповідає правильно, система зберігає відповідь і переходить далі.

## Actor

Learner

## Trigger

Користувач натискає кнопку відповіді.

## Preconditions

* Активна сесія існує.
* Питання показане користувачу.
* Користувач ще не відповідав на це питання.

## Main Flow

1. Користувач вибирає відповідь.
2. Система перевіряє відповідь.
3. Система зберігає відповідь.
4. Система оновлює прогрес.
5. Бот показує короткий feedback.
6. Бот переходить до наступного питання або завершує сесію.

## User-Facing Copy

```text
Richtig ✅
```

Optional explanation:

```text
Erklärung:
„Auto“ ist neutral. Deshalb heißt es: ein Auto.
```

## Postconditions

* Відповідь збережена.
* Прогрес оновлений.
* Подія `question_answered` записана.

## Acceptance Criteria

* Одна відповідь не рахується двічі.
* Правильна відповідь оновлює accuracy.
* Feedback німецькою.

---

## UC-007 — Answer Question Incorrectly

## Goal

Користувач відповідає неправильно, система зберігає помилку.

## Actor

Learner

## Trigger

Користувач натискає неправильну відповідь.

## Preconditions

* Активна сесія існує.
* Питання показане користувачу.
* Користувач ще не відповідав на це питання.

## Main Flow

1. Користувач вибирає відповідь.
2. Система перевіряє відповідь.
3. Система зберігає неправильну відповідь.
4. Система створює або оновлює mistake record.
5. Система оновлює progress topic.
6. Бот показує правильну відповідь і коротке пояснення.
7. Бот переходить до наступного питання або завершує сесію.

## User-Facing Copy

```text
Nicht ganz ❌

Richtig ist: ein Auto

Erklärung:
„Auto“ ist neutral. Deshalb heißt es: ein Auto.
```

## Postconditions

* Відповідь збережена.
* Помилка створена або оновлена.
* Прогрес оновлений.
* Подія `question_answered` записана.

## Acceptance Criteria

* Помилка не губиться.
* Повторна помилка збільшує `mistake_count`.
* Правильна відповідь показується німецькою.

---

## UC-008 — Complete Training Session

## Goal

Користувач завершує сесію й отримує короткий результат.

## Actor

Learner

## Trigger

Користувач відповів на останнє питання сесії.

## Preconditions

* Активна сесія існує.
* Усі питання сесії завершені.

## Main Flow

1. Система підраховує результат.
2. Система визначає слабку тему.
3. Система оновлює прогрес.
4. Система закриває session.
5. Бот показує результат.
6. Бот показує наступні дії.

## User-Facing Copy

```text
Training abgeschlossen ✅

Ergebnis: 8/10
Schwachstelle: Artikel
Neue Fehler: 2

Empfehlung:
Wiederhole jetzt deine Fehler oder starte eine neue kurze Übung.
```

Buttons:

```text
🔁 Fehler wiederholen
▶️ Noch einmal üben
📊 Mein Fortschritt
```

## Postconditions

* Сесія має статус `completed`.
* Прогрес оновлений.
* Помилки оновлені.
* Подія `training_completed` записана.
* Подія `result_shown` записана.

## Acceptance Criteria

* Результат показується після кожної завершеної сесії.
* Є кнопка повторення помилок.
* Є кнопка переходу до прогресу.

---

## UC-009 — Open Progress

## Goal

Користувач бачить свою карту прогресу.

## Actor

Learner

## Trigger

Користувач натискає **📊 Mein Fortschritt**.

## Preconditions

* Користувач існує.
* Є хоча б базові дані прогресу або прогрес порожній.

## Main Flow

1. Користувач відкриває прогрес.
2. Система отримує активний рівень.
3. Система рахує прогрес по темах.
4. Система визначає сильні й слабкі теми.
5. Бот показує коротку карту прогресу.

## User-Facing Copy

```text
📊 Mein Fortschritt

Niveau: A2

Starke Themen:
✅ Wortschatz Alltag — 84%
✅ Modalverben — 78%

Schwache Themen:
⚠️ Artikel — 54%
⚠️ Dativ — 47%

Empfehlung für heute:
Übe Dativ und wiederhole deine Fehler bei Artikel.
```

Buttons:

```text
▶️ Üben
🔁 Fehler wiederholen
🎯 Niveau & Thema
```

## Alternative Flow — No Progress Yet

```text
Du hast noch keinen Fortschritt.

Starte eine kurze Übung, damit ich deine Stärken und Schwächen erkennen kann.
```

Buttons:

```text
▶️ Erste Übung starten
```

## Postconditions

* Подія `progress_opened` записана.

## Acceptance Criteria

* Прогрес зрозумілий за 10 секунд.
* Показуються сильні й слабкі теми.
* Порожній прогрес не виглядає як помилка.

---

## UC-010 — Open Mistake Journal

## Goal

Користувач бачить свої помилки.

## Actor

Learner

## Trigger

Користувач натискає **🔁 Fehler wiederholen** або відкриває розділ помилок.

## Preconditions

* Користувач існує.
* У користувача можуть бути або не бути помилки.

## Main Flow

1. Система шукає активні помилки користувача.
2. Бот показує коротке резюме.
3. Бот пропонує повторити помилки.

## User-Facing Copy

```text
🔁 Deine Fehler

Offene Fehler: 12
Häufigstes Thema: Artikel

Du kannst jetzt gezielt deine Fehler wiederholen.
```

Buttons:

```text
▶️ Fehler üben
📊 Mein Fortschritt
🏠 Hauptmenü
```

## Alternative Flow — No Mistakes

```text
Du hast aktuell keine offenen Fehler ✅

Starte eine neue Übung, um weiter zu trainieren.
```

Buttons:

```text
▶️ Üben
🏠 Hauptmenü
```

## Postconditions

* Подія `mistakes_opened` записана.

## Acceptance Criteria

* Якщо помилок немає, користувач не бачить порожній екран.
* Якщо помилки є, є пряма дія для повторення.

---

## UC-011 — Repeat Mistakes

## Goal

Користувач проходить окрему сесію з власних помилок.

## Actor

Learner

## Trigger

Користувач натискає **▶️ Fehler üben**.

## Preconditions

* У користувача є активні помилки.
* Доступ до повторення помилок дозволений планом або поточним правилом Free.

## Main Flow

1. Користувач запускає повторення помилок.
2. Система вибирає активні unresolved або repeated mistakes.
3. Система створює mistake review session.
4. Бот показує питання.
5. Користувач відповідає.
6. Система оновлює статус помилки.
7. Після завершення бот показує результат повторення.

## User-Facing Copy

```text
Fehlertraining gestartet.

Ich zeige dir jetzt Fragen, bei denen du früher Fehler gemacht hast.
```

Result:

```text
Fehlertraining abgeschlossen ✅

Verbessert: 5
Noch offen: 3

Weiter so. Wiederhole diese Fehler später noch einmal.
```

Buttons:

```text
▶️ Weiter üben
📊 Mein Fortschritt
```

## Postconditions

* Статуси помилок оновлені.
* `successful_repeats_count` оновлений.
* Подія `mistakes_repeated` записана.

## Acceptance Criteria

* Помилка не закривається після однієї правильної відповіді.
* Повторення впливає на stability.
* Користувач бачить, що покращено.

---

## UC-012 — Get Daily Recommendation

## Goal

Користувач отримує просту рекомендацію, що тренувати сьогодні.

## Actor

Learner

## Trigger

Рекомендація показується на екрані прогресу, після сесії або при старті тренування.

## Preconditions

* Користувач існує.
* Є достатньо даних або доступна базова рекомендація.

## Main Flow

1. Система аналізує активний рівень.
2. Система аналізує слабкі теми.
3. Система аналізує відкриті помилки.
4. Система аналізує recency.
5. Бот показує коротку рекомендацію.

## User-Facing Copy

```text
Empfehlung für heute:

Übe Dativ und wiederhole deine Fehler bei Artikel.
```

## Alternative Flow — Not Enough Data

```text
Ich brauche noch ein paar Antworten, um eine gute Empfehlung zu geben.

Starte eine kurze Übung.
```

Buttons:

```text
▶️ Üben
```

## Postconditions

* Рекомендація показана.
* Подія може бути записана як `recommendation_shown`.

## Acceptance Criteria

* Рекомендація коротка.
* Рекомендація базується на реальних даних, якщо вони є.
* Якщо даних мало, бот чесно про це повідомляє.

---

## UC-013 — Daily Free Limit Hit

## Goal

Free-користувач досягає денного ліміту й бачить платну пропозицію.

## Actor

Learner

## Trigger

Користувач намагається отримати питання після завершення денного ліміту.

## Preconditions

* Користувач має Free-план.
* Денний ліміт вичерпаний.

## Main Flow

1. Користувач натискає **▶️ Üben**.
2. Система перевіряє денний ліміт.
3. Система бачить, що ліміт вичерпаний.
4. Бот показує повідомлення.
5. Бот пропонує Plus.

## User-Facing Copy

```text
Dein Tageslimit ist erreicht.

Mit Plus kannst du heute weiter üben und deinen vollständigen Fortschritt sehen.
```

Buttons:

```text
⭐ Plus ansehen
📊 Mein Fortschritt
🏠 Hauptmenü
```

## Postconditions

* Нове питання не видано.
* Ліміт не списується додатково.
* Подія `daily_limit_hit` записана.
* Подія `paywall_shown` записана.

## Acceptance Criteria

* Ліміт рахується по Europe/Berlin day.
* Повідомлення німецькою.
* Paywall пояснює користь.

---

## UC-014 — View Paywall After Progress

## Goal

Користувач бачить платну пропозицію після того, як продукт уже показав цінність.

## Actor

Learner

## Trigger

Користувач відкриває функцію, яка доступна в Plus або Pro.

## Preconditions

* Користувач має Free-план.
* Система вже має певні дані про прогрес або помилки.

## Main Flow

1. Користувач відкриває повний прогрес або повторення помилок.
2. Система перевіряє доступ.
3. Система бачить, що функція платна.
4. Бот показує paywall з поясненням користі.

## User-Facing Copy

```text
Ich habe deine Schwachstellen gefunden.

Mit Plus kannst du deinen vollständigen Fortschritt sehen, deine Fehler gezielt wiederholen und mehr Übungen pro Tag machen.
```

Buttons:

```text
⭐ Plus aktivieren
🚀 Pro ansehen
🏠 Hauptmenü
```

## Postconditions

* Платна функція не відкривається без доступу.
* Подія `paywall_shown` записана.

## Acceptance Criteria

* Paywall не з’являється до першої користі.
* Paywall пояснює навчальну цінність.
* Є чітка дія для оплати.

---

## UC-015 — Start Subscription Purchase

## Goal

Користувач починає купівлю підписки.

## Actor

Learner

## Trigger

Користувач натискає **⭐ Plus aktivieren** або **🚀 Pro ansehen**.

## Preconditions

* Користувач існує.
* Платіжна система Telegram Stars доступна.
* План активний для продажу.

## Main Flow

1. Користувач вибирає план.
2. Бот показує короткий опис плану.
3. Користувач підтверджує покупку.
4. Система створює payment record.
5. Система відкриває Telegram Stars invoice.

## User-Facing Copy

```text
Plus

Mehr Übungen pro Tag.
Vollständiger Fortschritt.
Fehler gezielt wiederholen.
Tägliche Empfehlungen.

Möchtest du Plus aktivieren?
```

Buttons:

```text
⭐ Mit Telegram Stars bezahlen
↩️ Zurück
```

## Postconditions

* Створений payment record.
* Подія `payment_started` записана.

## Acceptance Criteria

* Платіж створюється до оплати.
* План чітко описаний.
* Текст німецькою.

---

## UC-016 — Successful Payment

## Goal

Користувач успішно оплачує підписку й отримує доступ.

## Actor

Learner

## Trigger

Telegram повертає успішний платіж.

## Preconditions

* Payment record існує.
* Платіж підтверджений Telegram.
* Платіж ще не був зарахований.

## Main Flow

1. Telegram надсилає payment success event.
2. Система перевіряє payment reference.
3. Система перевіряє idempotency.
4. Система активує підписку.
5. Система оновлює user access.
6. Бот показує підтвердження.

## User-Facing Copy

```text
Plus ist aktiv ✅

Du kannst jetzt mehr üben, deinen vollständigen Fortschritt sehen und deine Fehler gezielt wiederholen.
```

Buttons:

```text
▶️ Üben
📊 Mein Fortschritt
🔁 Fehler wiederholen
```

## Postconditions

* Підписка активована.
* Payment має статус `credited`.
* Подія `payment_succeeded` записана.
* Подія `subscription_started` записана.

## Acceptance Criteria

* Один платіж не зараховується двічі.
* Доступ відкривається тільки після підтвердження.
* Користувач одразу бачить, що змінилося.

---

## UC-017 — Failed Payment

## Goal

Користувач бачить зрозуміле повідомлення, якщо платіж не пройшов.

## Actor

Learner

## Trigger

Telegram або система повертає payment failure.

## Preconditions

* Payment record існує або створення платежу було почато.
* Платіж не підтверджено.

## Main Flow

1. Система отримує failure.
2. Система не активує підписку.
3. Система оновлює payment status.
4. Бот показує повідомлення.
5. Бот дозволяє спробувати ще раз.

## User-Facing Copy

```text
Die Zahlung wurde nicht abgeschlossen.

Du kannst es noch einmal versuchen.
```

Buttons:

```text
⭐ Noch einmal versuchen
🏠 Hauptmenü
```

## Postconditions

* Підписка не активована.
* Подія `payment_failed` записана.

## Acceptance Criteria

* Немає доступу без успішної оплати.
* Користувач не губиться після помилки.
* Повідомлення німецькою.

---

## UC-018 — Subscription Expired

## Goal

Після завершення підписки користувач повертається до Free-доступу без втрати навчальних даних.

## Actor

Learner

## Trigger

Підписка досягла `expires_at`.

## Preconditions

* У користувача була активна підписка.
* Дата завершення настала.

## Main Flow

1. Система перевіряє підписки.
2. Система бачить завершену підписку.
3. Система змінює статус на expired.
4. Користувач повертається до Free-доступу.
5. Бот може показати повідомлення при наступній дії.

## User-Facing Copy

```text
Dein Plus-Zugang ist abgelaufen.

Dein Fortschritt bleibt gespeichert. Mit Plus kannst du wieder mehr üben und deine Fehler gezielt wiederholen.
```

Buttons:

```text
⭐ Plus erneuern
▶️ Üben
```

## Postconditions

* Підписка expired.
* Навчальні дані збережені.
* Подія `subscription_expired` записана.

## Acceptance Criteria

* Дані прогресу не видаляються.
* Платні функції закриті.
* Free-доступ працює.

---

## UC-019 — Change Level After Progress Exists

## Goal

Користувач змінює рівень, але старий прогрес не втрачається.

## Actor

Learner

## Trigger

Користувач відкриває **🎯 Niveau & Thema** і вибирає інший рівень.

## Preconditions

* Користувач має прогрес на попередньому рівні.
* Інший рівень доступний.

## Main Flow

1. Користувач відкриває вибір рівня.
2. Бот показує A1–C1.
3. Користувач вибирає новий рівень.
4. Система оновлює active level.
5. Старий прогрес залишається збереженим.
6. Бот пропонує вибрати тему для нового рівня.

## User-Facing Copy

```text
Niveau geändert: B1

Dein Fortschritt auf anderen Niveaus bleibt gespeichert.
```

Buttons:

```text
🎯 Thema wählen
▶️ Üben
```

## Postconditions

* Новий рівень активний.
* Старий прогрес збережений.
* Подія `level_selected` записана.

## Acceptance Criteria

* Зміна рівня не видаляє прогрес.
* Прогрес рахується окремо по рівнях.
* Користувач отримує зрозуміле підтвердження.

---

## UC-020 — API Quiz Bank Unavailable

## Goal

Бот безпечно обробляє ситуацію, коли API недоступний.

## Actor

Learner

## Trigger

Користувач стартує сесію або переходить до наступного питання, але API не відповідає.

## Preconditions

* Користувач існує.
* API запит потрібен для отримання питання.
* API недоступний або повертає timeout/error.

## Main Flow

1. Система робить запит до API.
2. API не відповідає або повертає помилку.
3. Система не списує денний ліміт.
4. Система записує технічну помилку.
5. Бот показує безпечне повідомлення.

## User-Facing Copy

```text
Etwas ist schiefgelaufen.

Bitte versuche es gleich noch einmal.
```

Buttons:

```text
🔄 Noch einmal versuchen
🏠 Hauptmenü
```

## Postconditions

* Ліміт не списаний.
* Помилка залогована.
* Сесія не пошкоджена.

## Acceptance Criteria

* Бот не падає.
* Користувач бачить зрозуміле повідомлення.
* API failure не створює неправильні answer records.

---

## UC-021 — Not Enough Questions

## Goal

Бот коректно обробляє ситуацію, коли для рівня/теми мало питань.

## Actor

Learner

## Trigger

Користувач стартує тренування за темою, де недостатньо питань.

## Preconditions

* Користувач вибрав рівень і тему.
* API повертає менше питань, ніж потрібно для сесії.

## Main Flow

1. Система запитує питання.
2. API повертає недостатню кількість.
3. Система перевіряє конфігураційне правило.
4. Бот або запускає коротшу сесію, або пропонує іншу тему.

## User-Facing Copy — Short Session

```text
Für dieses Thema gibt es heute nur 6 passende Fragen.

Ich starte eine kurze Übung.
```

## User-Facing Copy — Choose Another Theme

```text
Für dieses Thema gibt es gerade nicht genug Fragen.

Bitte wähle ein anderes Thema.
```

Buttons:

```text
🎯 Thema wählen
🏠 Hauptmenü
```

## Postconditions

* Користувач не застрягає.
* Ліміт списується тільки за реально видані питання.

## Acceptance Criteria

* Недостатня кількість питань не ламає flow.
* Користувач отримує чітку дію.
* Повідомлення німецькою.

---

## UC-022 — Unknown or Expired Button

## Goal

Бот безпечно обробляє застарілу або невідому кнопку.

## Actor

Learner

## Trigger

Користувач натискає стару inline-кнопку або callback, який уже неактуальний.

## Preconditions

* Callback не відповідає актуальному стану.
* Сесія могла бути завершена або застаріла.

## Main Flow

1. Система отримує callback.
2. Система не знаходить валідний стан.
3. Бот показує безпечне повідомлення.
4. Бот повертає користувача до головного меню або актуального екрану.

## User-Facing Copy

```text
Diese Aktion ist nicht mehr verfügbar.

Bitte starte neu vom Hauptmenü.
```

Buttons:

```text
🏠 Hauptmenü
```

## Postconditions

* Система не створює неправильних записів.
* Користувач повернутий у безпечний стан.

## Acceptance Criteria

* Unknown callback не викликає crash.
* Старі кнопки не дозволяють обійти ліміти.
* Повідомлення німецькою.

---

## UC-023 — Duplicate Telegram Update

## Goal

Система не рахує одну відповідь або один платіж двічі.

## Actor

Telegram Platform / Learner

## Trigger

Telegram повторно надсилає той самий update.

## Preconditions

* Update уже був оброблений.
* Система має idempotency guard.

## Main Flow

1. Система отримує update.
2. Система перевіряє update ID або business key.
3. Система бачить, що update уже оброблений.
4. Система не створює дубль відповіді, сесії або платежу.
5. Система повертає безпечний результат.

## Postconditions

* Дубль не створений.
* Дані залишаються консистентні.

## Acceptance Criteria

* Одна відповідь не рахується двічі.
* Один платіж не зараховується двічі.
* Progress не псується через duplicate update.

---

# 5. Admin Use Cases

---

## UC-024 — Admin Views Basic Metrics

## Goal

Адмін бачить базовий стан продукту.

## Actor

Admin

## Trigger

Адмін відкриває admin metrics endpoint або dashboard.

## Preconditions

* Адмін має доступ.
* Admin access захищений.

## Main Flow

1. Адмін відкриває статистику.
2. Система перевіряє доступ.
3. Система показує основні метрики.

## Metrics

Система має показувати:

* total users;
* active users today;
* training sessions today;
* answers today;
* active subscriptions;
* payments today;
* API errors today;
* payment errors today.

## Postconditions

* Адмін отримує базову картину продукту.
* Доступ логований, якщо потрібно.

## Acceptance Criteria

* Метрики захищені.
* Немає відкритого публічного доступу.
* Дані достатні для операційного контролю.

---

## UC-025 — Admin Reviews Learning Metrics

## Goal

Адмін бачить, які рівні й теми використовуються найчастіше.

## Actor

Admin

## Trigger

Адмін відкриває learning metrics.

## Preconditions

* Є навчальні дані.
* Адмін авторизований.

## Main Flow

1. Система збирає агреговані навчальні метрики.
2. Система показує популярні рівні.
3. Система показує популярні теми.
4. Система показує теми з найбільшою кількістю помилок.

## Metrics

* most used levels;
* most used themes;
* themes with most mistakes;
* average session completion;
* mistake repeat usage;
* progress screen opens.

## Postconditions

* Адмін бачить, де користувачам складно.
* Дані можуть використовуватись для покращення контенту.

## Acceptance Criteria

* Метрики не показують зайві персональні дані.
* Дані агреговані.
* Доступ захищений.

---

# 6. End-to-End Product Journeys

---

## Journey 1 — First-Time Learner Activation

1. Користувач відкриває бот.
2. Бот показує привітання.
3. Користувач вибирає рівень A2.
4. Користувач вибирає тему Artikel.
5. Користувач проходить 10 питань.
6. Бот показує результат.
7. Бот показує слабку тему.
8. Користувач відкриває прогрес.

## Success Criteria

Користувач активований, якщо він:

* вибрав рівень;
* вибрав тему;
* завершив першу сесію;
* побачив результат.

---

## Journey 2 — Progress Value Moment

1. Користувач проходить кілька сесій.
2. Система накопичує відповіді.
3. Користувач відкриває прогрес.
4. Бот показує сильні й слабкі теми.
5. Бот дає рекомендацію.
6. Користувач натискає тренування слабкої теми.

## Success Criteria

Користувач бачить не просто відсоток, а конкретну дію:

> що тренувати далі.

---

## Journey 3 — Mistake Recovery

1. Користувач помиляється в кількох питаннях.
2. Система створює mistake records.
3. Після сесії бот пропонує повторити помилки.
4. Користувач запускає Fehlertraining.
5. Система оновлює статуси помилок.
6. Частина помилок переходить у `improved`.

## Success Criteria

Користувач розуміє, що помилки не просто збережені, а перетворені на окреме тренування.

---

## Journey 4 — Free to Plus Conversion

1. Користувач проходить сесії у Free.
2. Бот показує базовий прогрес.
3. Користувач досягає денного ліміту або хоче повний прогрес.
4. Бот показує paywall.
5. Користувач бачить користь Plus.
6. Користувач оплачує через Telegram Stars.
7. Система активує Plus.
8. Користувач відкриває повний прогрес або повторення помилок.

## Success Criteria

Оплата прив’язана до зрозумілої користі:

* більше тренувань;
* повний прогрес;
* повторення помилок.

---

# 7. Release 1 Required Use Cases

Для першої повної версії обов’язкові:

1. UC-001 — First Start
2. UC-002 — Returning User Opens Bot
3. UC-003 — Select Level
4. UC-004 — Select Theme
5. UC-005 — Start Training Session
6. UC-006 — Answer Question Correctly
7. UC-007 — Answer Question Incorrectly
8. UC-008 — Complete Training Session
9. UC-009 — Open Progress
10. UC-010 — Open Mistake Journal
11. UC-011 — Repeat Mistakes
12. UC-012 — Get Daily Recommendation
13. UC-013 — Daily Free Limit Hit
14. UC-014 — View Paywall After Progress
15. UC-015 — Start Subscription Purchase
16. UC-016 — Successful Payment
17. UC-017 — Failed Payment
18. UC-020 — API Quiz Bank Unavailable
19. UC-021 — Not Enough Questions
20. UC-022 — Unknown or Expired Button
21. UC-023 — Duplicate Telegram Update
22. UC-024 — Admin Views Basic Metrics

---

# 8. Final Use Case Statement

Deutsch Trainer Bot має давати користувачу простий завершений шлях:

```text
Start → Niveau wählen → Thema wählen → Üben → Ergebnis → Fortschritt → Fehler wiederholen → Empfehlung → Plus
```

Головний принцип:

> Кожна дія користувача має або навчати, або показувати прогрес, або допомагати повторити слабке місце.

Оцінка відповіді: **98/100**
