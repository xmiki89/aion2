"""Dark theme for the meter."""

BG = "#131316"
CARD = "#1B1B20"
CARD_SOFT = "#191A1F"
TEXT = "#F3F4F7"
MUTED = "#8C8F99"
ACCENT = "#4C6FFF"
BORDER = "#26262C"

QSS = f"""
QWidget#window {{
    background: {BG};
}}
QWidget {{
    color: {TEXT};
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 12px;
}}
QLabel {{
    background: transparent;
}}
QFrame#card {{
    background: {CARD};
    border-radius: 14px;
}}
QLabel#cardLabel {{
    color: {MUTED};
    font-size: 11px;
    font-weight: 500;
}}
QLabel#cardValue {{
    color: #F6F7F9;
    font-size: 21px;
    font-weight: 700;
}}
QFrame#tabBar {{
    background: #101013;
    border: 1px solid #1E1E23;
    border-radius: 24px;
}}
QPushButton#tab {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 18px;
    padding: 7px 22px;
    color: #9A9DA6;
    font-size: 11.5px;
    font-weight: 600;
}}
QPushButton#tab:hover {{
    color: #E7E9EE;
}}
QPushButton#tab:checked {{
    background: #1C1C21;
    border: 1px solid #E9EAEE;
    color: #FFFFFF;
}}
QPushButton#chip {{
    background: #1E1E23;
    border: 1px solid #2A2A31;
    border-radius: 15px;
    padding: 6px 14px;
    color: #D7D9DF;
    font-size: 11px;
    font-weight: 600;
}}
QPushButton#chip:hover {{
    border-color: #3B3B44;
}}
QPushButton#chip:checked {{
    background: #212741;
    border: 1px solid {ACCENT};
    color: #EEF1FA;
}}
QPushButton#updateChip {{
    background: #1C2A44;
    border: 1px solid {ACCENT};
    border-radius: 14px;
    padding: 6px 14px;
    color: #CFDCFF;
    font-size: 11px;
    font-weight: 700;
}}
QPushButton#updateChip:hover {{
    background: #25365A;
}}
QLabel#youChip {{
    background: #1A1A1F;
    border: 1px solid #2A2A31;
    border-radius: 14px;
    padding: 6px 12px;
    color: #C9CCD4;
    font-size: 11px;
    font-weight: 600;
}}
QLabel#emptyTitle {{
    color: #E9EAEF;
    font-size: 15px;
    font-weight: 600;
}}
QLabel#emptySub {{
    color: #8C8F99;
    font-size: 11.5px;
}}
QLabel#emptyHint {{
    color: #6F727C;
    font-size: 10.5px;
}}
QLabel#badgeDemo {{
    background: #2A2116;
    border: 1px solid #5B4526;
    border-radius: 10px;
    padding: 3px 9px;
    color: #E7B966;
    font-size: 10px;
    font-weight: 700;
}}
QLabel#badgeLive {{
    background: #14261C;
    border: 1px solid #2E6B45;
    border-radius: 10px;
    padding: 3px 9px;
    color: #6FD79A;
    font-size: 10px;
    font-weight: 700;
}}
QPushButton#back {{
    background: transparent;
    border: none;
    color: #9A9DA6;
    font-size: 11.5px;
    font-weight: 600;
    padding: 2px 2px;
    text-align: left;
}}
QPushButton#back:hover {{
    color: #FFFFFF;
}}
QLabel#dName {{
    color: #FFFFFF;
    font-size: 17px;
    font-weight: 700;
}}
QLabel#dSpec {{
    color: #93969F;
    font-size: 11.5px;
}}
QLabel#dDps {{
    color: #FFFFFF;
    font-size: 17px;
    font-weight: 700;
}}
QLabel#dDpsMeta {{
    color: #93969F;
    font-size: 12px;
}}
QFrame#statCard {{
    background: {CARD_SOFT};
    border-radius: 12px;
}}
QLabel#statTitle {{
    color: {MUTED};
    font-size: 11px;
}}
QLabel#statValue {{
    color: #F6F7F9;
    font-size: 21px;
    font-weight: 700;
}}
QLabel#bhTitle {{
    color: #FFFFFF;
    font-size: 12.5px;
    font-weight: 700;
}}
QLabel#bhMeta {{
    color: #93969F;
    font-size: 11.5px;
}}
QLabel#status {{
    color: #7C7F89;
    font-size: 11px;
}}
QLabel#statusOk {{
    color: #6FD79A;
    font-size: 11px;
}}
QScrollArea {{
    background: transparent;
    border: none;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    margin: 2px 0;
}}
QScrollBar::handle:vertical {{
    background: #383840;
    border-radius: 3px;
    min-height: 28px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
"""
