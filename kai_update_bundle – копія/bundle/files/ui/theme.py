from __future__ import annotations

from string import Template

# Токени кольорів: єдине місце правди для обох тем (дизайн за цільовим скриншотом)
DARK = dict(
    bg="#0A0A0E", surface="#101015", card="#15151C", card2="#1B1B24", border="#25252F",
    text="#ECECF2", muted="#8C8C9A", accent="#5B3FE0", accent_hover="#6F55EC", accent_text="#FFFFFF",
    input_bg="#101015", hover="#1B1B24", nav_text="#C9C9D4",
    sec_bg="#1B1B24", sec_hover="#262633", sec_text="#E4E4EC",
    danger_bg="#5E1A1F", danger_text="#FEE2E2", danger_border="#B42323",
    high_bg="#3A1519", high_fg="#F87171", med_bg="#3A2210", med_fg="#FB923C",
    low_bg="#11301F", low_fg="#4ADE80", subj_bg="#16204A", subj_fg="#8FA8FF",
    t_backlog_bg="#22222B", t_backlog_fg="#A5A5B4", t_todo_bg="#14233F", t_todo_fg="#7FA8FF",
    t_prog_bg="#201B4A", t_prog_fg="#A99CFF", t_review_bg="#4A3511", t_review_fg="#F5C26B",
    t_done_bg="#0F3B2A", t_done_fg="#6EE7B7",
    ok_bg="#0F3B2A", ok_fg="#6EE7B7", warn_bg="#4A3511", warn_fg="#F5C26B", bad_bg="#4A1519", bad_fg="#FCA5A5",
    accent_card_bg="#17142B", accent_card_border="#4B38B8", danger_card_bg="#2A1215",
)
LIGHT = dict(
    bg="#F4F4F8", surface="#FFFFFF", card="#FFFFFF", card2="#F1F1F6", border="#DCDCE6",
    text="#16161F", muted="#6B6B7B", accent="#5B3FE0", accent_hover="#4A30C8", accent_text="#FFFFFF",
    input_bg="#FFFFFF", hover="#ECECF4", nav_text="#3A3A4A",
    sec_bg="#F6F6FA", sec_hover="#E8E8F1", sec_text="#232330",
    danger_bg="#DC2626", danger_text="#FFFFFF", danger_border="#B91C1C",
    high_bg="#FEE2E2", high_fg="#B91C1C", med_bg="#FFEDD5", med_fg="#C2410C",
    low_bg="#DCFCE7", low_fg="#15803D", subj_bg="#E0E7FF", subj_fg="#3730A3",
    t_backlog_bg="#E7E7EF", t_backlog_fg="#55556A", t_todo_bg="#DBEAFE", t_todo_fg="#1D4ED8",
    t_prog_bg="#E5E0FF", t_prog_fg="#4C35C9", t_review_bg="#FEF3C7", t_review_fg="#92400E",
    t_done_bg="#DCFCE7", t_done_fg="#166534",
    ok_bg="#DCFCE7", ok_fg="#15803D", warn_bg="#FEF3C7", warn_fg="#B45309", bad_bg="#FEE2E2", bad_fg="#B91C1C",
    accent_card_bg="#F0EDFF", accent_card_border="#8A76F0", danger_card_bg="#FEF2F2",
)

# Важливо: у QSS динамічну властивість обирають як [class="X"], а не `.X` (це C++-клас).
_QSS = Template(r"""
QMainWindow, QWidget#RootContainer { background-color: $bg; color: $text;
    font-family: "Segoe UI", "Inter", sans-serif; font-size: 13px; }
QLabel { background: transparent; }

QFrame#Sidebar { background-color: $surface; border-right: 1px solid $border; }
QLabel#BrandTitle { color: $text; font-size: 15px; font-weight: 700; letter-spacing: 0.4px; }
QLabel#BrandSubtitle { color: $muted; font-size: 11px; }
QLabel[class="NavSection"] { color: $muted; font-size: 10px; font-weight: 700; letter-spacing: 1px; padding: 8px 6px 2px 6px; }

QPushButton[class="NavButton"] { text-align: left; padding: 8px 12px; border: none; border-radius: 8px;
    color: $nav_text; background-color: transparent; font-size: 13px; font-weight: 500; }
QPushButton[class="NavButton"]:hover { background-color: $hover; color: $text; }
QPushButton[class="NavButton"][active="true"] { background-color: $card2; color: $text; font-weight: 600;
    border-left: 3px solid $accent; }

QFrame#TopBar { background-color: $surface; border-bottom: 1px solid $border; }

QFrame[class="Card"] { background-color: $card; border: 1px solid $border; border-radius: 12px; }
QFrame[class="CardAccent"] { background-color: $accent_card_bg; border: 1px solid $accent_card_border; border-radius: 12px; }
QFrame[class="CardDanger"] { background-color: $danger_card_bg; border: 1px solid $danger_border; border-radius: 12px; }

QLabel[class="SectionTitle"] { font-size: 22px; font-weight: 700; color: $text; }
QLabel[class="CardTitle"] { font-size: 13px; font-weight: 600; color: $text; }
QLabel[class="MutedText"] { color: $muted; font-size: 12px; }

QLabel[class="Badge"], QLabel[class="Chip"] { background-color: $card2; color: $subj_fg; border: 1px solid $border;
    border-radius: 6px; padding: 3px 8px; font-size: 11px; font-weight: 600; }
QLabel[class="BadgeSuccess"] { background-color: $ok_bg; color: $ok_fg; border-radius: 6px; padding: 3px 8px; font-size: 11px; font-weight: 600; }
QLabel[class="BadgeWarning"] { background-color: $warn_bg; color: $warn_fg; border-radius: 6px; padding: 3px 8px; font-size: 11px; font-weight: 600; }
QLabel[class="BadgeDanger"], QLabel[class="ChipDanger"] { background-color: $bad_bg; color: $bad_fg; border-radius: 6px; padding: 3px 8px; font-size: 11px; font-weight: 600; }

QLabel[class="TagHigh"] { background-color: $high_bg; color: $high_fg; border-radius: 5px; padding: 2px 7px; font-size: 11px; font-weight: 600; }
QLabel[class="TagMed"] { background-color: $med_bg; color: $med_fg; border-radius: 5px; padding: 2px 7px; font-size: 11px; font-weight: 600; }
QLabel[class="TagLow"] { background-color: $low_bg; color: $low_fg; border-radius: 5px; padding: 2px 7px; font-size: 11px; font-weight: 600; }
QLabel[class="TagMuted"] { background-color: $card2; color: $muted; border-radius: 5px; padding: 2px 7px; font-size: 11px; font-weight: 600; }
QLabel[class="TagSubject"] { background-color: $subj_bg; color: $subj_fg; border-radius: 5px; padding: 2px 7px; font-size: 11px; font-weight: 600; }
QLabel[class="TagId"] { color: $muted; font-size: 11px; }

/* Кольорові заголовки колонок Kanban (tone = статус завдання) */
QLabel[tone] { border-radius: 8px; padding: 7px 12px; font-size: 13px; font-weight: 700; }
QLabel[tone="backlog"] { background-color: $t_backlog_bg; color: $t_backlog_fg; }
QLabel[tone="todo"] { background-color: $t_todo_bg; color: $t_todo_fg; }
QLabel[tone="in_progress"] { background-color: $t_prog_bg; color: $t_prog_fg; }
QLabel[tone="review"] { background-color: $t_review_bg; color: $t_review_fg; }
QLabel[tone="done"] { background-color: $t_done_bg; color: $t_done_fg; }

QPushButton[class="PrimaryBtn"] { background-color: $accent; color: $accent_text; border: none; border-radius: 8px; padding: 7px 14px; font-weight: 600; }
QPushButton[class="PrimaryBtn"]:hover { background-color: $accent_hover; }
QPushButton[class="SecondaryBtn"] { background-color: $sec_bg; color: $sec_text; border: 1px solid $border; border-radius: 8px; padding: 6px 12px; font-weight: 500; }
QPushButton[class="SecondaryBtn"]:hover { background-color: $sec_hover; }
QPushButton[class="DangerBtn"] { background-color: $danger_bg; color: $danger_text; border: 1px solid $danger_border; border-radius: 8px; padding: 6px 12px; font-weight: 600; }
QPushButton:disabled { color: $muted; }

QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit { background-color: $input_bg; color: $text;
    border: 1px solid $border; border-radius: 8px; padding: 6px 10px; selection-background-color: $accent; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus { border: 1px solid $accent; }
QComboBox QAbstractItemView { background-color: $card; color: $text; border: 1px solid $border; selection-background-color: $accent; }

QTableWidget { background-color: $card; alternate-background-color: $card2; color: $text; gridline-color: $border;
    border: 1px solid $border; border-radius: 8px; selection-background-color: $accent; selection-color: $accent_text; }
QHeaderView::section { background-color: $card2; color: $muted; padding: 7px; border: none; font-weight: 600; }

QTabWidget::pane { border: none; }
QTabBar::tab { background: transparent; color: $muted; padding: 7px 14px; border-radius: 8px; margin-right: 4px; font-weight: 600; }
QTabBar::tab:selected { background: $card2; color: $text; }
QTabBar::tab:hover:!selected { color: $text; }

QProgressBar { background-color: $card2; border: none; border-radius: 5px; text-align: center; color: $text; font-weight: 600; height: 14px; }
QProgressBar::chunk { background-color: $accent; border-radius: 5px; }

QCheckBox { spacing: 8px; }
QScrollArea { border: none; background-color: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: $border; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: $border; border-radius: 4px; min-width: 30px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QToolTip { background-color: $card2; color: $text; border: 1px solid $border; }
""")

DARK_STYLESHEET = _QSS.substitute(DARK)
LIGHT_STYLESHEET = _QSS.substitute(LIGHT)


def get_stylesheet(theme_name: str) -> str:
    return LIGHT_STYLESHEET if theme_name.lower() == "light" else DARK_STYLESHEET
