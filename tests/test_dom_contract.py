"""DOM contract tests: pin the verified selectors to the saved site snapshots.

The repo ships two saved copies of ru.virt-chat.com — these tests parse them
directly, so any future drift in the app DOM is caught here before it reaches
the browser layer.
"""
import pathlib

from bs4 import BeautifulSoup

ROOT = pathlib.Path(__file__).resolve().parents[1]
MAIN = "Вирт чат.html"
PRIVAT = "Вирт чат privat.html"


def load(name: str) -> BeautifulSoup:
    return BeautifulSoup((ROOT / name).read_text(encoding="utf-8", errors="replace"),
                         "html.parser")


def user_rows(soup) -> list:
    vp = soup.select_one("cdk-virtual-scroll-viewport.users-list-viewport")
    assert vp is not None, "viewport not found"
    return [r for r in vp.select("container-item") if r.find("user-item")]


def header_rows(soup) -> list:
    vp = soup.select_one("cdk-virtual-scroll-viewport.users-list-viewport")
    return [r for r in vp.select("container-item") if r.find("users-header-item")]


def nick(row) -> str:
    el = row.select_one("user-item .primary-text")
    assert el is not None
    return el.get_text(strip=True)  # raw text has padding spaces — must trim


def test_main_viewport_and_rows():
    soup = load(MAIN)
    rows = user_rows(soup)
    assert len(rows) == 25
    nicks = [nick(r) for r in rows]
    assert "Lizalo4ka" in nicks and "LadyToi" in nicks
    assert len(set(nicks)) == len(nicks), "duplicate nicknames in one render"


def test_header_row_is_not_a_user():
    soup = load(PRIVAT)
    assert len(user_rows(soup)) == 2
    headers = header_rows(soup)
    assert len(headers) == 1
    title = headers[0].select_one("users-header-item .primary-text").get_text(strip=True)
    assert title == "Пользователи"
    counter = headers[0].select_one(".users-counter")
    assert counter is not None and counter.get_text(strip=True) == "2"


def test_gender_and_registration_flags():
    soup = load(MAIN)
    by_nick = {nick(r): r for r in user_rows(soup)}
    lady = by_nick["LadyToi"].select_one(".avatar-wrapper")
    classes = lady.get("class")
    assert "female-avatar" in classes and "registered-badge" in \
        lady.select_one(".registered-badge").get("class")
    guests = [n for n, r in by_nick.items()
              if r.select_one(".avatar-wrapper .anonymous-badge") is not None]
    assert guests, "expected at least one guest (anonymous badge) row"
    males = [n for n, r in by_nick.items()
             if "male-avatar" in (r.select_one(".avatar-wrapper").get("class") or [])]
    assert males


def test_trailing_spaces_are_real():
    soup = load(MAIN)
    raw = soup.select_one("user-item .primary-text").text
    assert raw != raw.strip(), "expected untrimmed nickname text in the DOM"


def test_tabs():
    soup = load(PRIVAT)
    tabs = soup.select('[role=tablist].tabs-list div[role=tab]')
    assert len(tabs) == 4
    titles = []
    for t in tabs:
        p = t.select_one("p.chat-title")
        unread = p.select_one("span.unread")
        if unread:  # the room tab carries an unread badge — strip it
            unread.extract()
        titles.append(p.get_text(" ", strip=True))
    assert "Гостиная" in titles and "_ШепотНочи_" in titles
    close = soup.select_one('div[role=tab] button.tab-close-button')
    assert close is not None
    assert close["aria-label"].startswith("Закрыть чат ")
    active = soup.select_one(".tab-item.active")
    assert active is not None and active.get("aria-selected") == "true"
    # the main room tab has no close button, person tabs do
    room = next(t for t in tabs
                if "room" in (t.select_one("mat-icon").get("data-mat-icon-name") or ""))
    assert room.select_one("button.tab-close-button") is None


def test_message_form():
    soup = load(MAIN)
    ta = soup.select_one("app-message-form textarea[matinput]")
    assert ta is not None
    assert ta["placeholder"] == "Сообщение" and ta["maxlength"] == "1000"
    send = soup.select_one("app-message-form button[type=submit]")
    assert send is not None and send.select_one("mat-icon").get_text(strip=True) == "send"
    icons = [b.select_one("mat-icon").get_text(strip=True)
             for b in soup.select("app-message-form button[matsuffix]")]
    assert "image" in icons and "insert_emoticon" in icons
    hint = [h.get_text(strip=True) for h in soup.select("app-message-form mat-hint")]
    assert any(h.endswith("/ 1000") for h in hint)


def test_hidden_file_input():
    for name in (MAIN, PRIVAT):
        soup = load(name)
        f = soup.select_one("input#file[type=file]")
        assert f is not None, name
        assert f["accept"] == "image/*"


def test_selector_constants_reference_verified_marks():
    from chatflow.browser import selectors as s
    assert "users-list-viewport" in s.VIEWPORT
    assert s.USER_ROW.startswith(s.ROW) and ":has(user-item)" in s.USER_ROW
    assert "female-avatar" in s.FEMALE and "registered-badge" in s.REGISTERED
    assert "type=submit" in s.SEND_BTN and "input#file" in s.FILE_INPUT
    assert "span.unread" in s.TAB_TITLE_JS and "trim()" in s.TAB_TITLE_JS
    assert ".primary-text" in s.ROWS_JS and "user-item" in s.ROWS_JS
