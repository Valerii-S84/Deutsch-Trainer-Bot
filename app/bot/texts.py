"""German user-facing text constants for Milestone 3 bot shell."""

from __future__ import annotations

WELCOME_TEXT = (
    "👋 Willkommen bei *Deutsch Trainer Bot*!\\n\\n"
    "Hier beginnt dein Lernfluss in kurzen, klaren Schritten. "
    "Wähle im Menü, was du als Nächstes tun möchtest."
)

MENU_PROMPT = "Was möchtest du als Nächstes tun?"

TRAINING_PROMPT = (
    "📘 Wähle ein Level, um eine neue Übung einzuleiten. "
    "Der eigentliche Quiz-Flow wird in einem späteren Meilenstein implementiert."
)

LEVEL_SELECTED_TEXT = "✅ {level} wurde ausgewählt. Jetzt wähle bitte ein Thema."

THEME_PROMPT = "📚 Wähle ein Thema für die nächste Übung."

THEME_SELECTED_TEXT = (
    "✅ Thema *{theme}* ist gewählt. "
    "Die Trainingsauslieferung ist in dieser Milestone noch nicht aktiv."
)

THEME_ENTRY_TEXT = "🎯 Wähle zuerst ein Thema für dein Training."

LEVEL_CALLBACK_FALLBACK_TEXT = (
    "⚠️ Dieses Niveau ist aktuell nicht verfügbar. "
    "Bitte wähle eines der angebotenen Level."
)

THEME_CALLBACK_FALLBACK_TEXT = (
    "⚠️ Dieses Thema ist aktuell nicht verfügbar. "
    "Bitte wähle eines der angebotenen Themen."
)

PROFILE_TEXT = (
    "👤 Dein Profil & Fortschritt sind angelegt. "
    "Die Fortschrittsberechnung und Historie sind Teil eines späteren Milestones."
)

SUBSCRIPTION_TEXT = (
    "💳 Subscription-Bereich ist vorbereitet. "
    "Die Payment-Integration wird in einem späteren Milestone implementiert."
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
MENU_BUTTON_SUBSCRIPTION = "💳 Subscription"
MENU_BUTTON_HOME = "🏠 Hauptmenü"

LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")
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
CALLBACK_SUBSCRIPTION = "menu:subscription"
CALLBACK_LEVEL_PREFIX = "level:"
CALLBACK_THEME_PREFIX = "theme:"
