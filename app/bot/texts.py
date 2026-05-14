"""German user-facing text constants for the bot shell."""

from __future__ import annotations

WELCOME_TEXT = (
    "👋 Willkommen bei *Deutsch Trainer Bot*!\\n\\n"
    "Hier beginnt dein Lernfluss in kurzen, klaren Schritten. "
    "Wähle im Menü, was du als Nächstes tun möchtest."
)

MENU_PROMPT = "Was möchtest du als Nächstes tun?"

TRAINING_PROMPT = (
    "📘 Wähle ein Level, um eine neue Übungsrunde zu starten."
)

LEVEL_SELECTED_TEXT = "✅ {level} wurde ausgewählt. Jetzt wähle bitte ein Thema."

THEME_PROMPT = "📚 Wähle ein Thema für die nächste Übung."

THEME_SELECTED_TEXT = (
    "✅ Thema *{theme}* ist gewählt für Niveau *{level}*. "
    "Die erste Frage wird geladen."
)

THEME_ENTRY_TEXT = "🎯 Wähle zuerst ein Thema für dein Training."
TRAINING_NEW_SESSION_BUTTON_TEXT = "🆕 Neues Training"

LEVEL_CALLBACK_FALLBACK_TEXT = (
    "⚠️ Dieses Niveau ist aktuell nicht verfügbar. "
    "Bitte wähle eines der angebotenen Level."
)

THEME_CALLBACK_FALLBACK_TEXT = (
    "⚠️ Dieses Thema ist aktuell nicht verfügbar. "
    "Bitte wähle eines der angebotenen Themen."
)

PROFILE_TEXT = (
    "👤 Dein Profil & Fortschritt"
)

PROFILE_EMPTY_STATE_TEXT = (
    "📭 Noch kein Fortschritt erfasst.\n\n"
    "Starte zuerst ein Training, dann erscheint hier dein Lernstand."
)

PROFILE_PROGRESS_TEMPLATE = (
    "✅ {level} / {theme}: {correct}/{answered} korrekt ({accuracy}%)."
)

SUBSCRIPTION_TEXT = (
    "💳 Der Abo-Bereich ist vorbereitet. "
    "Die Zahlungsanbindung wird in einem späteren Ausbauschritt implementiert."
)

UNKNOWN_MESSAGE_TEXT = (
    "🔁 Diese Nachricht verstehe ich nicht. "
    "Nutze bitte das Menü oder /start, um fortzufahren."
)

UNKNOWN_CALLBACK_TEXT = (
    "⛔️ Dieser Button ist nicht mehr gültig. "
    "Starte bitte mit /start neu."
)

HOME_TEXT = "🏠 Hauptmenü"

MENU_BUTTON_TRAIN = "▶️ Üben"
MENU_BUTTON_LEVEL_THEME = "🎯 Niveau & Thema"
MENU_BUTTON_PROGRESS = "📊 Mein Fortschritt"
MENU_BUTTON_REVIEW = "🧠 Fehler wiederholen"
MENU_BUTTON_SUBSCRIPTION = "💳 Abo"
MENU_BUTTON_HOME = "🏠 Hauptmenü"

LEVELS = ("A1", "A2", "B1", "B2", "C1")
THEMES = (
    "Alltag",
    "Beruf",
    "Reisen",
    "Bewerbung",
    "Grammatik",
    "Wortschatz",
)

CALLBACK_HOME = "bot:home"
CALLBACK_LEVELS = "menu:levels"
CALLBACK_THEMES = "bot:theme"
CALLBACK_PROFILE = "menu:profile"
CALLBACK_REVIEW = "menu:review"
CALLBACK_SUBSCRIPTION = "menu:subscription"
CALLBACK_LEVEL_PREFIX = "level:"
CALLBACK_THEME_PREFIX = "theme:"

CALLBACK_TRAIN_ANSWER_PREFIX = "train:ans"
CALLBACK_TRAIN_NEXT_PREFIX = "train:next"
CALLBACK_TRAIN_RESUME_PREFIX = "train:resume"
CALLBACK_TRAIN_NEW_PREFIX = "train:new"
CALLBACK_TRAIN_CANCEL_PREFIX = "train:cancel"

TRAINING_QUESTION_TEMPLATE = (
    "🧠 Frage {position}/{total}\n\n{question_text}\n\n"
    "Wähle eine Antwort mit einem Button."
)
TRAINING_CORRECT_ANSWER_TEXT = "✅ Richtig! Das ist die korrekte Antwort."
TRAINING_INCORRECT_ANSWER_TEXT = "❌ Nicht korrekt. Richtige Antwort: `{correct_answer}`."
TRAINING_ANSWER_DUPLICATE_TEXT = "⚠️ Diese Frage wurde bereits beantwortet."
TRAINING_EXPLANATION_TEXT = "💡 Erklärung: {explanation}"
TRAINING_NEXT_BUTTON_TEXT = "➡️ Nächste Frage"
TRAINING_FINISH_TEXT = (
    "🎉 Training beendet!\n\n"
    "✅ Richtig: {correct}/{total} ({percent}%)"
)
TRAINING_FINISH_NEW_MISTAKES_TEXT = "🧠 Neue Fehler: {count}"
TRAINING_FINISH_WEAK_THEME_TEXT = "🎯 Schwerpunkt: {theme}"
TRAINING_FINISH_RECOMMENDATION_TEXT = "➡️ Empfehlung: {recommendation}"
TRAINING_SESSION_RESUME_TEXT = (
    "⚠️ Du hast bereits eine aktive Trainingsrunde.\n"
    "Möchtest du sie fortsetzen oder eine neue Runde starten?"
)
TRAINING_RESUME_NO_ACTIVE_TEXT = (
    "⚠️ Die aktive Sitzung wurde bereits abgeschlossen oder nicht mehr gefunden."
)
TRAINING_SESSION_COMPLETED_TEXT = "🏁 Diese Runde ist bereits beendet."
TRAINING_SESSION_CANCELLED_TEXT = "✅ Sitzung wurde beendet."
TRAINING_NO_LEVEL_SELECTED_TEXT = "⚠️ Bitte wähle zuerst ein Niveau bevor du ein Thema auswählst."
TRAINING_THEME_NOT_AVAILABLE_TEXT = "⚠️ Dieses Thema ist aktuell nicht verfügbar."

REVIEW_EMPTY_STATE_TEXT = (
    "🧹 Keine aktiven Fehler für die Wiederholung.\n\n"
    "Lerne zuerst neue Fragen, dann werden falsche Antworten automatisch erfasst."
)

TRAINING_QUIZBANK_AUTH_ERROR_TEXT = (
    "🔒 Quiz-Bank Authentifizierung fehlgeschlagen. Bitte versuche es später erneut."
)
TRAINING_QUIZBANK_RATE_LIMIT_TEXT = (
    "⏳ Quiz-Bank ist gerade ausgelastet. Bitte in einem Moment erneut versuchen."
)
TRAINING_QUIZBANK_UNAVAILABLE_TEXT = (
    "🌐 Quiz-Bank ist vorübergehend nicht erreichbar. Bitte versuche es später erneut."
)
TRAINING_QUIZBANK_VALIDATION_TEXT = "⚠️ Quiz-Frage-Daten sind ungültig."
TRAINING_SESSION_ERROR_TEXT = "⚠️ Trainingsrunde konnte nicht geladen werden. Bitte erneut versuchen."
