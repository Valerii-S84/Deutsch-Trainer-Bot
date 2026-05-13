# Deutsch Trainer Bot — UX Flows

## 1. Document Purpose

Цей документ описує UX-потоки Telegram-бота **Deutsch Trainer Bot**.

Він фіксує:

* які екрани існують у боті;
* які повідомлення бачить користувач;
* які кнопки доступні на кожному екрані;
* які переходи дозволені між екранами;
* як виглядають empty states;
* як виглядають error states;
* які UX-інваріанти не можна порушувати.

Усі user-facing тексти, кнопки та приклади екранів у цьому документі наведені **німецькою мовою**, бо користувацький інтерфейс бота має бути повністю німецькомовним.

---

## 2. Global UX Principles

## 2.1. German-Only Interface

Усі повідомлення користувачу мають бути німецькою:

* onboarding;
* головне меню;
* кнопки;
* вибір рівня;
* вибір теми;
* питання;
* відповіді;
* результати;
* прогрес;
* помилки;
* рекомендації;
* paywall;
* платежі;
* повідомлення про помилки.

Українська може використовуватися в робочій документації, але не в Telegram UI.

## 2.2. Supported Levels

Бот підтримує рівні:

```text
A1
A2
B1
B2
C1
```

## 2.3. Primary Navigation

Головна навігація має складатися з трьох основних дій:

```text
▶️ Üben
🎯 Niveau & Thema
📊 Mein Fortschritt
```

## 2.4. Screen Simplicity Rule

Один екран має мати одну головну дію.

Якщо екран має більше трьох кнопок, вони мають бути згруповані за пріоритетом:

1. основна навчальна дія;
2. другорядна дія;
3. повернення або навігація.

## 2.5. Button Stability Rule

Назви кнопок мають бути стабільні в усьому продукті.

| Meaning | Standard Button |
|---|---|
| Start practice | `▶️ Üben` |
| Choose level/theme | `🎯 Niveau & Thema` |
| View progress | `📊 Mein Fortschritt` |
| Repeat mistakes | `🔁 Fehler wiederholen` |
| Practice mistakes | `▶️ Fehler üben` |
| Home | `🏠 Hauptmenü` |
| Back | `↩️ Zurück` |
| Retry | `🔄 Noch einmal versuchen` |
| View Plus | `⭐ Plus ansehen` |
| Activate Plus | `⭐ Plus aktivieren` |
| View Pro | `🚀 Pro ansehen` |

---

## 3. Screen Inventory

Release 1 UX складається з таких основних екранів:

1. Home.
2. Level Selection.
3. Theme Selection.
4. Training Session.
5. Result Screen.
6. Progress Screen.
7. Mistake Screen.
8. Paywall Screen.
9. Subscription Screen.

Додаткові службові стани:

* loading state;
* empty state;
* API error state;
* expired button state;
* payment success state;
* payment failure state.

---

## 4. Global Navigation Map

```text
Home
  ├─ ▶️ Üben → Training Session
  ├─ 🎯 Niveau & Thema → Level Selection → Theme Selection
  └─ 📊 Mein Fortschritt → Progress Screen

Training Session
  └─ completed → Result Screen

Result Screen
  ├─ 🔁 Fehler wiederholen → Mistake Screen / Mistake Training
  ├─ ▶️ Noch einmal üben → Training Session
  └─ 📊 Mein Fortschritt → Progress Screen

Progress Screen
  ├─ ▶️ Üben → Training Session
  ├─ 🔁 Fehler wiederholen → Mistake Screen
  └─ 🎯 Niveau & Thema → Level Selection

Mistake Screen
  ├─ ▶️ Fehler üben → Training Session with session_type = mistake_review
  ├─ 📊 Mein Fortschritt → Progress Screen
  └─ 🏠 Hauptmenü → Home

Paywall Screen
  ├─ ⭐ Plus aktivieren → Subscription Screen
  ├─ 🚀 Pro ansehen → Subscription Screen
  └─ 🏠 Hauptmenü → Home

Subscription Screen
  ├─ ⭐ Mit Telegram Stars bezahlen → Telegram payment flow
  └─ ↩️ Zurück → Paywall Screen or previous screen
```

---

## 5. Home Screen

## 5.1. Purpose

Home — головний екран бота.

Він має за кілька секунд відповісти користувачу:

* що можна зробити зараз;
* де почати тренування;
* де змінити рівень і тему;
* де подивитися прогрес.

## 5.2. Entry Points

Home відкривається:

* після `/start` для returning user;
* після завершення onboarding;
* після натискання `🏠 Hauptmenü`;
* після expired або unknown callback;
* після завершення payment/error flow.

## 5.3. Default Copy

```text
Was möchtest du heute üben?
```

## 5.4. Default Buttons

```text
▶️ Üben
🎯 Niveau & Thema
📊 Mein Fortschritt
```

## 5.5. Returning User Copy

```text
Willkommen zurück.

Was möchtest du heute üben?
```

## 5.6. New User Redirect

Якщо користувач не має `selected_level`, Home не має показуватися як основний екран.

Бот має вести користувача на Level Selection.

## 5.7. Transitions

| Button | Destination |
|---|---|
| `▶️ Üben` | Training Session start. |
| `🎯 Niveau & Thema` | Level Selection. |
| `📊 Mein Fortschritt` | Progress Screen. |

## 5.8. Acceptance Criteria

* Home має тільки три основні дії.
* Усі кнопки німецькою.
* Користувач може повернутися до Home з основних екранів.
* Home не має містити paywall як перший досвід.

---

## 6. Level Selection Screen

## 6.1. Purpose

Level Selection дозволяє користувачу вибрати активний рівень навчання.

## 6.2. Entry Points

Level Selection відкривається:

* під час onboarding;
* з кнопки `🎯 Niveau & Thema`;
* після empty theme state;
* після зміни рівня користувачем.

## 6.3. Copy

```text
Wähle dein Niveau:
```

## 6.4. Buttons

```text
A1
A2
B1
B2
C1
```

Optional navigation button:

```text
🏠 Hauptmenü
```

## 6.5. After Selection Copy

```text
Dein Niveau: A2

Wähle jetzt ein Thema oder starte direkt mit dem Training.
```

## 6.6. After Selection Buttons

```text
🎯 Thema wählen
▶️ Üben
🏠 Hauptmenü
```

## 6.7. State Changes

Після вибору рівня система оновлює:

* `selected_level`;
* active Progress Topic scope;
* recommendation context;
* analytics event `level_selected`.

## 6.8. Transitions

| Button | Destination |
|---|---|
| `A1`–`C1` | Level selected state. |
| `🎯 Thema wählen` | Theme Selection. |
| `▶️ Üben` | Training Session with recommended/default theme. |
| `🏠 Hauptmenü` | Home. |

## 6.9. Acceptance Criteria

* Рівні A1–C1 доступні.
* Вибір рівня не видаляє старий прогрес.
* Старий прогрес лишається прив’язаний до попереднього рівня.
* Текст і кнопки німецькою.

---

## 7. Theme Selection Screen

## 7.1. Purpose

Theme Selection дозволяє користувачу вибрати тему в межах активного рівня.

## 7.2. Entry Points

Theme Selection відкривається:

* після вибору рівня;
* з `🎯 Thema wählen`;
* з `🎯 Niveau & Thema`;
* з insufficient questions state.

## 7.3. Copy

```text
Wähle ein Thema:
```

## 7.4. Default Theme Buttons

```text
Artikel
Verben
Fälle
Wortschatz
Alltag
Prüfung
```

Navigation:

```text
🎯 Niveau wählen
🏠 Hauptmenü
```

## 7.5. Availability Rule

Бот показує тільки теми, для яких є доступні питання в API Quiz Bank або валідному локальному cache.

## 7.6. After Selection Copy

```text
Thema gespeichert: Artikel

Du kannst jetzt mit dem Training beginnen.
```

## 7.7. After Selection Buttons

```text
▶️ Üben
📊 Mein Fortschritt
🏠 Hauptmenü
```

## 7.8. Empty State

Якщо для активного рівня немає тем:

```text
Für dieses Niveau sind gerade keine Themen verfügbar.

Bitte wähle ein anderes Niveau.
```

Buttons:

```text
🎯 Niveau wählen
🏠 Hauptmenü
```

## 7.9. Transitions

| Button | Destination |
|---|---|
| Theme button | Theme selected state. |
| `▶️ Üben` | Training Session. |
| `📊 Mein Fortschritt` | Progress Screen. |
| `🎯 Niveau wählen` | Level Selection. |
| `🏠 Hauptmenü` | Home. |

## 7.10. Acceptance Criteria

* Тема зберігається як `selected_theme`.
* Недоступні теми не показуються.
* Empty state не виглядає як помилка.
* Усі user-facing тексти німецькою.

---

## 8. Training Session Screen

## 8.1. Purpose

Training Session — основний навчальний екран.

Він показує питання, варіанти відповідей і короткий feedback після відповіді.

## 8.2. Entry Points

Training Session стартує з:

* `▶️ Üben`;
* `▶️ Noch einmal üben`;
* `▶️ Fehler üben`;
* recommendation action;
* first exercise button.

## 8.3. Start Copy

```text
Training gestartet.

Niveau: A2
Thema: Artikel

Frage 1 von 10
```

## 8.4. Question Copy Pattern

```text
Wähle die richtige Antwort:

Ich habe ___ Auto.
```

## 8.5. Answer Buttons

```text
A) ein
B) eine
C) einen
D) einem
```

Optional navigation:

```text
🏠 Hauptmenü
```

## 8.6. Correct Feedback

```text
Richtig ✅
```

Optional explanation:

```text
Erklärung:
„Auto“ ist neutral. Deshalb heißt es: ein Auto.
```

## 8.7. Incorrect Feedback

```text
Nicht ganz ❌

Richtig ist: ein Auto

Erklärung:
„Auto“ ist neutral. Deshalb heißt es: ein Auto.
```

## 8.8. Session Progress Indicator

Кожне питання має показувати позицію:

```text
Frage 3 von 10
```

## 8.9. Button Rules

* Користувач може дати тільки одну відповідь на питання.
* Після відповіді answer buttons мають бути заблоковані або ігнорувати повторне натискання.
* Duplicate Telegram update не має створювати другу відповідь.
* `🏠 Hauptmenü` має завершувати або abandon активну сесію за безпечним правилом.

## 8.10. API Loading State

```text
Einen Moment bitte.

Ich lade deine nächste Frage.
```

## 8.11. API Error State

```text
Etwas ist schiefgelaufen.

Bitte versuche es gleich noch einmal.
```

Buttons:

```text
🔄 Noch einmal versuchen
🏠 Hauptmenü
```

## 8.12. Insufficient Questions State

```text
Für dieses Thema gibt es gerade nicht genug Fragen.

Bitte wähle ein anderes Thema.
```

Buttons:

```text
🎯 Thema wählen
🏠 Hauptmenü
```

## 8.13. Transitions

| Event | Destination |
|---|---|
| Correct answer | Next question or Result Screen. |
| Incorrect answer | Next question or Result Screen. |
| Last question answered | Result Screen. |
| API error | API Error State. |
| Not enough questions | Theme Selection. |
| Home button | Home, session abandoned. |

## 8.14. Acceptance Criteria

* Питання й пояснення німецькою.
* Одна відповідь не рахується двічі.
* Feedback короткий.
* API failure не списує daily limit.
* Після останнього питання відкривається Result Screen.

---

## 9. Result Screen

## 9.1. Purpose

Result Screen завершує навчальну сесію й показує користувачу короткий результат, слабке місце й наступні дії.

## 9.2. Entry Points

Result Screen відкривається після:

* завершення regular training session;
* завершення mistake review session;
* завершення recommended session.

## 9.3. Regular Result Copy

```text
Training abgeschlossen ✅

Ergebnis: 8/10
Schwachstelle: Artikel
Neue Fehler: 2

Empfehlung:
Wiederhole jetzt deine Fehler oder starte eine neue kurze Übung.
```

## 9.4. Regular Result Buttons

```text
🔁 Fehler wiederholen
▶️ Noch einmal üben
📊 Mein Fortschritt
```

## 9.5. Mistake Training Result Copy

```text
Fehlertraining abgeschlossen ✅

Verbessert: 5
Noch offen: 3

Wiederhole diese Fehler später noch einmal.
```

## 9.6. Mistake Training Result Buttons

```text
▶️ Weiter üben
📊 Mein Fortschritt
🏠 Hauptmenü
```

## 9.7. No Mistakes After Result

Якщо після сесії немає відкритих помилок:

```text
Training abgeschlossen ✅

Ergebnis: 10/10

Sehr gut. Du hast aktuell keine offenen Fehler.
```

Buttons:

```text
▶️ Noch einmal üben
📊 Mein Fortschritt
🏠 Hauptmenü
```

## 9.8. Paywall Moment

Якщо користувач Free і після результату доступна тільки базова карта прогресу:

```text
Ich habe deine Schwachstellen gefunden.

Mit Plus kannst du deinen vollständigen Fortschritt sehen und deine Fehler gezielt wiederholen.
```

Buttons:

```text
⭐ Plus ansehen
📊 Mein Fortschritt
▶️ Noch einmal üben
```

## 9.9. Transitions

| Button | Destination |
|---|---|
| `🔁 Fehler wiederholen` | Mistake Screen or Paywall Screen depending on access. |
| `▶️ Noch einmal üben` | Training Session. |
| `▶️ Weiter üben` | Training Session. |
| `📊 Mein Fortschritt` | Progress Screen. |
| `⭐ Plus ansehen` | Paywall Screen. |
| `🏠 Hauptmenü` | Home. |

## 9.10. Acceptance Criteria

* Result Screen має бути коротким.
* Result Screen має показувати наступну дію.
* Result Screen не має перевантажувати поясненнями.
* Paywall може з’являтися тільки після value moment.

---

## 10. Progress Screen

## 10.1. Purpose

Progress Screen показує карту знань користувача.

Він має за 10 секунд дати відповідь:

* які теми сильні;
* які теми слабкі;
* що тренувати сьогодні.

## 10.2. Entry Points

Progress Screen відкривається з:

* `📊 Mein Fortschritt`;
* Result Screen;
* Mistake Screen;
* Paywall preview;
* Home.

## 10.3. Default Copy

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

## 10.4. Default Buttons

```text
▶️ Üben
🔁 Fehler wiederholen
🎯 Niveau & Thema
```

## 10.5. Empty Progress State

```text
Du hast noch keinen Fortschritt.

Starte eine kurze Übung, damit ich deine Stärken und Schwächen erkennen kann.
```

Buttons:

```text
▶️ Erste Übung starten
🎯 Niveau & Thema
```

## 10.6. Limited Free Progress State

```text
📊 Mein Fortschritt

Niveau: A2

Du hast schon genug Antworten für eine erste Auswertung.

Mit Plus kannst du deine vollständige Fortschrittskarte sehen.
```

Buttons:

```text
⭐ Plus ansehen
▶️ Üben
🔁 Fehler wiederholen
```

## 10.7. Topic Detail Preview

Release 1 не потребує складного detail screen, але Progress Screen може показувати короткий список тем:

```text
Artikel: 54%
Verben: 71%
Wortschatz: 82%
Dativ: 47%
```

## 10.8. Transitions

| Button | Destination |
|---|---|
| `▶️ Üben` | Training Session. |
| `▶️ Erste Übung starten` | Training Session. |
| `🔁 Fehler wiederholen` | Mistake Screen or Paywall Screen. |
| `🎯 Niveau & Thema` | Level Selection. |
| `⭐ Plus ansehen` | Paywall Screen. |

## 10.9. Acceptance Criteria

* Progress зрозумілий за 10 секунд.
* Сильні й слабкі теми видимі.
* Рекомендація коротка.
* Free state не приховує повністю цінність продукту.
* User-facing copy німецькою.

---

## 11. Mistake Screen

## 11.1. Purpose

Mistake Screen показує помилки користувача й дає прямий шлях до повторення.

## 11.2. Entry Points

Mistake Screen відкривається з:

* `🔁 Fehler wiederholen`;
* Result Screen;
* Progress Screen;
* Plus feature list.

## 11.3. Default Copy

```text
🔁 Deine Fehler

Offene Fehler: 12
Häufigstes Thema: Artikel

Du kannst jetzt gezielt deine Fehler wiederholen.
```

## 11.4. Default Buttons

```text
▶️ Fehler üben
📊 Mein Fortschritt
🏠 Hauptmenü
```

## 11.5. No Mistakes State

```text
Du hast aktuell keine offenen Fehler ✅

Starte eine neue Übung, um weiter zu trainieren.
```

Buttons:

```text
▶️ Üben
📊 Mein Fortschritt
🏠 Hauptmenü
```

## 11.6. Free Access Restricted State

Якщо повторення помилок доступне тільки в Plus:

```text
Ich habe deine Fehler gespeichert.

Mit Plus kannst du sie gezielt wiederholen.
```

Buttons:

```text
⭐ Plus ansehen
📊 Mein Fortschritt
🏠 Hauptmenü
```

## 11.7. Mistake Training Start Copy

```text
Fehlertraining gestartet.

Ich zeige dir jetzt Fragen, bei denen du früher Fehler gemacht hast.
```

## 11.8. Transitions

| Button | Destination |
|---|---|
| `▶️ Fehler üben` | Training Session with `session_type = mistake_review`. |
| `📊 Mein Fortschritt` | Progress Screen. |
| `⭐ Plus ansehen` | Paywall Screen. |
| `▶️ Üben` | Training Session. |
| `🏠 Hauptmenü` | Home. |

## 11.9. Acceptance Criteria

* Якщо помилок немає, користувач бачить positive empty state.
* Якщо помилки є, головна дія — `▶️ Fehler üben`.
* Mistake Screen не закриває помилку після одного правильного повторення.
* Усі тексти німецькою.

---

## 12. Paywall Screen

## 12.1. Purpose

Paywall Screen пояснює платну цінність після того, як користувач уже побачив користь.

Він не має бути першим досвідом користувача.

## 12.2. Entry Points

Paywall Screen може відкриватися:

* після результату сесії;
* після виявлення слабкої теми;
* після повторної помилки;
* після daily limit hit;
* перед повною картою прогресу;
* перед повним mistake repeat access.

## 12.3. Progress Paywall Copy

```text
Ich habe deine Schwachstellen gefunden.

Mit Plus kannst du deinen vollständigen Fortschritt sehen und deine Fehler gezielt wiederholen.
```

## 12.4. Daily Limit Paywall Copy

```text
Dein Tageslimit ist erreicht.

Mit Plus kannst du heute weiter üben und deinen vollständigen Fortschritt sehen.
```

## 12.5. Mistake Paywall Copy

```text
Du hast mehrere offene Fehler.

Mit Plus kannst du sie gezielt wiederholen und schneller schließen.
```

## 12.6. Paywall Buttons

```text
⭐ Plus aktivieren
🚀 Pro ansehen
🏠 Hauptmenü
```

Optional secondary button:

```text
📊 Mein Fortschritt
```

## 12.7. Paywall Content Rules

Paywall має продавати навчальний результат, а не “більше кнопок”.

Allowed value points:

* vollständiger Fortschritt;
* Fehler gezielt wiederholen;
* mehr Übungen pro Tag;
* tägliche Empfehlungen;
* erweiterte Statistik.

## 12.8. Forbidden Paywall Pattern

Не використовувати:

```text
Kaufe Plus.
```

як єдине пояснення.

## 12.9. Transitions

| Button | Destination |
|---|---|
| `⭐ Plus aktivieren` | Subscription Screen for Plus. |
| `🚀 Pro ansehen` | Subscription Screen for Pro. |
| `📊 Mein Fortschritt` | Progress Screen. |
| `🏠 Hauptmenü` | Home. |

## 12.10. Acceptance Criteria

* Paywall з’являється після value moment.
* Paywall copy німецькою.
* Paywall пояснює конкретну навчальну користь.
* Є clear CTA для Plus або Pro.

---

## 13. Subscription Screen

## 13.1. Purpose

Subscription Screen показує план, його користь і запускає оплату через Telegram Stars.

## 13.2. Entry Points

Subscription Screen відкривається з:

* `⭐ Plus aktivieren`;
* `🚀 Pro ansehen`;
* `⭐ Plus erneuern`;
* failed payment retry.

## 13.3. Plus Plan Copy

```text
Plus

Mehr Übungen pro Tag.
Vollständiger Fortschritt.
Fehler gezielt wiederholen.
Tägliche Empfehlungen.

Möchtest du Plus aktivieren?
```

## 13.4. Pro Plan Copy

```text
Pro

Mehr Übungen pro Tag.
Erweiterte Statistik.
Tieferer Fehlerüberblick.
Persönlicher Lernplan.

Möchtest du Pro aktivieren?
```

## 13.5. Subscription Buttons

```text
⭐ Mit Telegram Stars bezahlen
↩️ Zurück
```

Optional:

```text
⭐ Plus ansehen
🚀 Pro ansehen
```

## 13.6. Payment Loading State

```text
Die Zahlung wird vorbereitet.

Bitte warte einen Moment.
```

## 13.7. Payment Success State

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

## 13.8. Pro Success State

```text
Pro ist aktiv ✅

Du hast jetzt Zugriff auf erweiterte Statistik und mehr Training.
```

Buttons:

```text
▶️ Üben
📊 Mein Fortschritt
🔁 Fehler wiederholen
```

## 13.9. Payment Failure State

```text
Die Zahlung wurde nicht abgeschlossen.

Du kannst es noch einmal versuchen.
```

Buttons:

```text
⭐ Noch einmal versuchen
🏠 Hauptmenü
```

## 13.10. Subscription Expired State

```text
Dein Plus-Zugang ist abgelaufen.

Dein Fortschritt bleibt gespeichert. Mit Plus kannst du wieder mehr üben und deine Fehler gezielt wiederholen.
```

Buttons:

```text
⭐ Plus erneuern
▶️ Üben
```

## 13.11. Transitions

| Button | Destination |
|---|---|
| `⭐ Mit Telegram Stars bezahlen` | Telegram Stars invoice. |
| `⭐ Noch einmal versuchen` | Retry payment creation. |
| `⭐ Plus erneuern` | Subscription Screen for Plus. |
| `▶️ Üben` | Training Session. |
| `📊 Mein Fortschritt` | Progress Screen. |
| `🔁 Fehler wiederholen` | Mistake Screen. |
| `↩️ Zurück` | Paywall Screen or previous screen. |
| `🏠 Hauptmenü` | Home. |

## 13.12. Acceptance Criteria

* План описаний коротко.
* Оплата запускається тільки після явного натискання.
* Підписка активується тільки після confirmed payment.
* Failure state не відкриває доступ.
* Success state одразу пояснює, що стало доступним.
* Усі тексти німецькою.

---

## 14. Error and Safety Screens

## 14.1. Unknown or Expired Button

```text
Diese Aktion ist nicht mehr verfügbar.

Bitte starte neu vom Hauptmenü.
```

Buttons:

```text
🏠 Hauptmenü
```

## 14.2. Generic Error

```text
Etwas ist schiefgelaufen.

Bitte versuche es noch einmal.
```

Buttons:

```text
🔄 Noch einmal versuchen
🏠 Hauptmenü
```

## 14.3. Missing Level

```text
Wähle zuerst dein Niveau.
```

Buttons:

```text
A1
A2
B1
B2
C1
```

## 14.4. Missing Theme

```text
Wähle zuerst ein Thema.
```

Buttons:

```text
🎯 Thema wählen
🏠 Hauptmenü
```

## 14.5. Safety Rules

* Unknown callback не має ламати сесію.
* Expired button не має обходити daily limit.
* Duplicate answer не має створювати другий User Answer.
* Payment callback не має активувати підписку двічі.
* API error не має списувати daily limit.

---

## 15. Callback Action Catalog

Це не технічна прив’язка до конкретної бібліотеки, а словник UX-дій.

| UX Action | Meaning |
|---|---|
| `home.open` | Відкрити Home. |
| `level.open` | Відкрити Level Selection. |
| `level.select` | Вибрати рівень A1–C1. |
| `theme.open` | Відкрити Theme Selection. |
| `theme.select` | Вибрати тему. |
| `training.start` | Почати regular training. |
| `training.answer` | Відповісти на питання. |
| `training.retry` | Повторити після API error. |
| `progress.open` | Відкрити Progress Screen. |
| `mistakes.open` | Відкрити Mistake Screen. |
| `mistakes.start` | Почати mistake review session. |
| `paywall.open` | Відкрити Paywall Screen. |
| `subscription.open` | Відкрити Subscription Screen. |
| `payment.start` | Почати Telegram Stars payment. |
| `payment.retry` | Повторити оплату. |

---

## 16. UX Acceptance Checklist

Перед реалізацією або зміною Telegram UX потрібно перевірити:

* усі user-facing тексти німецькою;
* Home має три основні дії;
* Level Selection містить A1, A2, B1, B2, C1;
* Theme Selection не показує теми без питань;
* Training Session не приймає duplicate answer;
* Result Screen має наступну дію;
* Progress Screen зрозумілий за 10 секунд;
* Mistake Screen має empty state;
* Paywall з’являється після value moment;
* Subscription Screen не активує доступ без confirmed payment;
* error states повертають користувача в безпечний flow;
* кнопки використовують стабільні назви.

---

## 17. Final UX Statement

Deutsch Trainer Bot має відчуватися як простий, швидкий і німецькомовний Telegram-тренажер.

Користувач має завжди бачити одну зрозумілу наступну дію:

```text
Üben → Ergebnis → Fortschritt → Fehler wiederholen → Empfehlung
```

Головний UX-стандарт:

> За 10 секунд користувач має зрозуміти, що робити далі, і вся взаємодія має залишатися німецькою мовою.
