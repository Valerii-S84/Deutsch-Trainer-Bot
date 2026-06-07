"""German user-facing text constants for the bot shell."""

from __future__ import annotations

WELCOME_TEXT = (
    "👋 Willkommen bei *Deutsch Trainer Bot*!\\n\\n"
    "Hier beginnt dein Lernfluss in kurzen, klaren Schritten. "
    "Wähle im Menü, was du als Nächstes tun möchtest."
)

MENU_PROMPT = "Was möchtest du heute üben?"

TRAINING_PROMPT = (
    "📘 Wähle ein Niveau, um eine neue Übungsrunde zu starten."
)

LEVEL_SELECTED_TEXT = "✅ {level} wurde ausgewählt. Jetzt wähle bitte ein Thema."

THEME_PROMPT = "📚 Wähle ein Thema für die nächste Übung."
THEME_EMPTY_STATE_TEXT = (
    "📭 Für dieses Niveau sind aktuell keine aktiven Themen verfügbar. "
    "Bitte wähle ein anderes Niveau."
)

THEME_SELECTED_TEXT = (
    "✅ Thema *{theme}* ist gewählt für Niveau *{level}*. "
    "Die erste Frage wird geladen."
)

THEME_ENTRY_TEXT = "🎯 Wähle zuerst ein Thema für dein Training."
TRAINING_NEW_SESSION_BUTTON_TEXT = "🆕 Neues Training"

LEVEL_CALLBACK_FALLBACK_TEXT = (
    "⚠️ Dieses Niveau ist aktuell nicht verfügbar. "
    "Bitte wähle eines der angebotenen Niveaus."
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
    "{status_icon} {level} / {theme}: {correct}/{answered} korrekt ({accuracy}%). "
    "Abdeckung: {coverage}. Stabilität: {stability}%. Schwäche: {weakness}%."
)

PROFILE_STRONG_THEMES_HEADER = "Starke Themen:"
PROFILE_WEAK_THEMES_HEADER = "Schwache Themen:"
PROFILE_DETAILS_HEADER = "Details:"
PROFILE_RECOMMENDATION_HEADER = "Empfehlung für heute:"
PROFILE_NO_STRONG_THEMES_TEXT = "Noch kein starkes Thema."
PROFILE_NO_WEAK_THEMES_TEXT = "Keine klare Schwachstelle erkannt."

SUBSCRIPTION_TEXT = (
    "💳 Dein Abo\n\n"
    "Aktueller Zugang: {access_plan}\n"
    "Abo-Status: {status}\n\n"
    "Plus bietet mehr Übungen pro Tag, vollständigen Fortschritt und gezielte Fehlerwiederholung.\n"
    "Pro enthält zusätzlich erweiterte Statistik und einen tieferen Fehlerüberblick."
)

SUBSCRIPTION_STATUS_FREE_TEXT = "Kostenlos"
SUBSCRIPTION_STATUS_ACTIVE_TEXT = "{plan} aktiv bis {expires_at}"
SUBSCRIPTION_STATUS_PENDING_TEXT = "{plan} wartet auf Zahlungsbestätigung"
SUBSCRIPTION_STATUS_EXPIRED_TEXT = "{plan} ist am {expires_at} abgelaufen"
SUBSCRIPTION_STATUS_CANCELLED_TEXT = "{plan} wurde beendet"
SUBSCRIPTION_STATUS_FAILED_TEXT = "{plan} konnte nicht aktiviert werden"
SUBSCRIPTION_STATUS_INACTIVE_TEXT = "Kein aktives Abo"
PAYMENT_PLUS_BUTTON_TEXT = "⭐ Plus mit Stars bezahlen"
PAYMENT_PRO_BUTTON_TEXT = "🚀 Pro mit Stars bezahlen"
PAYMENT_INVOICE_PAY_BUTTON_TEXT = "Bezahlen ⭐ {amount_stars}"
PAYMENT_RETRY_BUTTON_TEXT = "⭐ Noch einmal versuchen"
PAYMENT_CONFIG_REQUIRED_TEXT = (
    "Die Zahlung ist aktuell nicht verfügbar.\n\n"
    "Bitte versuche es später erneut."
)
PAYMENT_PLAN_CHANGE_BLOCKED_TEXT = (
    "Plus ist erst wieder verfügbar, wenn dein Pro-Abo abgelaufen ist.\n\n"
    "Dein aktueller Pro-Zugang bleibt aktiv."
)
PAYMENT_PRECHECKOUT_ERROR_TEXT = "Diese Zahlung konnte nicht bestätigt werden."
PAYMENT_SUCCESS_PLUS_TEXT = (
    "Plus ist aktiv ✅\n\n"
    "Du kannst jetzt mehr üben, deinen vollständigen Fortschritt sehen und deine Fehler gezielt wiederholen."
)
PAYMENT_SUCCESS_PRO_TEXT = (
    "Pro ist aktiv ✅\n\n"
    "Du hast jetzt Zugriff auf erweiterte Statistik und mehr Training."
)
PAYMENT_FAILURE_TEXT = (
    "Die Zahlung wurde nicht abgeschlossen.\n\n"
    "Du kannst es noch einmal versuchen."
)
PAYWALL_DAILY_LIMIT_TEXT = (
    "Dein Tageslimit ist erreicht.\n\n"
    "Mit Plus kannst du heute weiter üben und deinen vollständigen Fortschritt sehen."
)
PAYWALL_PROGRESS_TEXT = (
    "Ich habe deine Schwachstellen gefunden.\n\n"
    "Mit Plus kannst du deinen vollständigen Fortschritt sehen und deine Fehler gezielt wiederholen."
)
PAYWALL_MISTAKE_REPEAT_TEXT = (
    "Du hast offene Fehler.\n\n"
    "Mit Plus kannst du sie gezielt wiederholen und schneller schließen."
)
PAYWALL_PLUS_BUTTON_TEXT = "⭐ Plus ansehen"
PAYWALL_PRO_BUTTON_TEXT = "🚀 Pro ansehen"

UNKNOWN_MESSAGE_TEXT = (
    "🔁 Diese Nachricht verstehe ich nicht. "
    "Nutze bitte das Menü oder /start, um fortzufahren."
)

UNKNOWN_CALLBACK_TEXT = (
    "⛔️ Dieser Button ist nicht mehr gültig. "
    "Starte bitte mit /start neu."
)

RATE_LIMIT_HIT_TEXT = "Bitte warte kurz und versuche es dann erneut."

ADMIN_METRICS_UNAUTHORIZED_TEXT = "Diese Admin-Funktion ist nicht verfügbar."
ADMIN_METRICS_UNAVAILABLE_TEXT = "Admin-Metriken sind aktuell nicht verfügbar."

HOME_TEXT = "🏠 Hauptmenü"

MENU_BUTTON_TRAIN = "▶️ Üben"
MENU_BUTTON_LEVEL_THEME = "🎯 Niveau & Thema"
MENU_BUTTON_PROGRESS = "📊 Mein Fortschritt"
MENU_BUTTON_REVIEW = "🔁 Fehler wiederholen"
MENU_BUTTON_REVIEW_START = "▶️ Fehler üben"
MENU_BUTTON_HOME = "🏠 Hauptmenü"

LEVELS = ("A1", "A2", "B1", "B2", "C1")
CALLBACK_HOME = "bot:home"
CALLBACK_LEVELS = "menu:levels"
CALLBACK_THEMES = "bot:theme"
CALLBACK_PROFILE = "menu:profile"
CALLBACK_REVIEW = "menu:review"
CALLBACK_REVIEW_START = "review:start"
CALLBACK_SUBSCRIPTION = "menu:subscription"
CALLBACK_PAYMENT_PLAN_PREFIX = "payment:plan:"
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

REVIEW_SCREEN_TEXT = (
    "🔁 Deine Fehler sind bereit.\n\n"
    "Starte eine kurze Wiederholung, um offene Fehler gezielt zu üben."
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
