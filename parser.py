import re
from dataclasses import dataclass


@dataclass
class ActivityEntry:
    nick: str
    player_id: str
    activity: int


def clean_number(value: str) -> int:
    value = value.strip()

    value = (
        value
        .replace(" ", "")
        .replace("\u00a0", "")
        .replace(".", "")
        .replace(",", "")
    )

    return int(value)


def parse_standard_line(line: str):
    pattern = re.compile(
        r"^\s*"
        r"(?:ник\s+)?"
        r"(.+?)"
        r"\s+ID\s+(\d+)"
        r"\s+активность\s+([\d\s.,]+)"
        r"\s*$",
        re.IGNORECASE
    )

    match = pattern.match(line)

    if not match:
        return None

    nick = match.group(1).strip()
    player_id = match.group(2).strip()
    activity = clean_number(match.group(3))

    return ActivityEntry(
        nick=nick,
        player_id=player_id,
        activity=activity
    )


def parse_pipe_line(line: str):
    parts = [
        x.strip()
        for x in line.split("|")
    ]

    if len(parts) != 3:
        return None

    nick = parts[0]

    player_id_match = re.search(
        r"\d+",
        parts[1]
    )

    activity_match = re.search(
        r"[\d\s.,]+",
        parts[2]
    )

    if not player_id_match or not activity_match:
        return None

    return ActivityEntry(
        nick=nick,
        player_id=player_id_match.group(),
        activity=clean_number(
            activity_match.group()
        )
    )


def parse_simple_line(line: str):
    pattern = re.compile(
        r"^\s*(.+?)\s+(\d{4,})\s+([\d\s.,]+)\s*$"
    )

    match = pattern.match(line)

    if not match:
        return None

    nick = match.group(1).strip()
    player_id = match.group(2).strip()
    activity = clean_number(
        match.group(3)
    )

    return ActivityEntry(
        nick=nick,
        player_id=player_id,
        activity=activity
    )


def parse_activity_text(
    text: str
) -> tuple[list[ActivityEntry], list[str]]:

    entries = []
    errors = []

    seen_ids = set()

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    for line_number, line in enumerate(
        lines,
        start=1
    ):

        entry = None

        try:
            entry = parse_standard_line(line)

            if entry is None:
                entry = parse_pipe_line(line)

            if entry is None:
                entry = parse_simple_line(line)

        except ValueError:
            errors.append(
                f"Строка {line_number}: "
                f"неверное число активности."
            )
            continue

        if entry is None:
            errors.append(
                f"Строка {line_number} "
                f"не распознана."
            )
            continue

        if not entry.nick:
            errors.append(
                f"Строка {line_number}: "
                f"пустой ник."
            )
            continue

        if entry.activity < 0:
            errors.append(
                f"Строка {line_number}: "
                f"отрицательная активность."
            )
            continue

        if entry.player_id in seen_ids:
            errors.append(
                f"Строка {line_number}: "
                f"ID {entry.player_id} "
                f"повторяется."
            )
            continue

        seen_ids.add(entry.player_id)

        entries.append(entry)

    return entries, errors


@dataclass
class HumanMonitoringEntry:
    """Entry from the compact game activity table.

    Source format:
      NICK_OR_ID WEEK_ACTIVITY GAME_TOTAL TOURNAMENT_ACTIVITY TOURNAMENT_TOTAL

    The last four whitespace-separated fields are numeric, so nicknames may
    contain spaces. The values are snapshots, not deltas.
    """
    name_or_id: str
    week_activity: int
    game_total: int
    tournament_activity: int
    tournament_total: int


def parse_human_monitoring_text(text: str):
    """Parse the explicit VAKA_ACTIVITY_LIST format.

    The first non-empty line MUST be ``VAKA_ACTIVITY_LIST`` (or the Russian
    marker ``СПИСОК АКТИВНОСТИ``). This explicit marker prevents ordinary chat
    messages from being mistaken for monitoring data.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return [], ["Пустой список активности."]

    marker = lines[0].strip().upper()
    allowed = {"VAKA_ACTIVITY_LIST", "СПИСОК АКТИВНОСТИ"}
    if marker not in allowed:
        return [], ["Не найден маркер VAKA_ACTIVITY_LIST / СПИСОК АКТИВНОСТИ."]

    entries = []
    errors = []
    seen = set()

    for line_no, line in enumerate(lines[1:], start=2):
        # Ignore optional table header copied from a screenshot/text table.
        compact = re.sub(r"[\s/]+", " ", line).strip().lower()
        if ("name" in compact or "ник" in compact) and "акт" in compact:
            continue

        m = re.match(
            r"^\s*(.*?)\s+([0-9][0-9\s.,]*)\s+([0-9][0-9\s.,]*)\s+"
            r"([0-9][0-9\s.,]*)\s+([0-9][0-9\s.,]*)\s*$",
            line,
        )
        if not m:
            errors.append(
                f"Строка {line_no}: ожидается «Ник/ID Акт_неделя Акт_всего Тур_акт Тур_всего»."
            )
            continue

        name = m.group(1).strip()
        if not name:
            errors.append(f"Строка {line_no}: пустой ник/ID.")
            continue

        try:
            vals = [clean_number(m.group(i)) for i in range(2, 6)]
        except ValueError:
            errors.append(f"Строка {line_no}: неверное число.")
            continue

        if any(v < 0 for v in vals):
            errors.append(f"Строка {line_no}: отрицательное значение.")
            continue

        key = name.casefold()
        if key in seen:
            errors.append(f"Строка {line_no}: игрок «{name}» повторяется.")
            continue
        seen.add(key)

        entries.append(HumanMonitoringEntry(name, *vals))

    if not entries:
        errors.append("Нет ни одной строки игрока.")
    return entries, errors


def total_activity(
    entries: list[ActivityEntry]
) -> int:
    return sum(
        entry.activity
        for entry in entries
    )


def format_number(number: int) -> str:
    return f"{number:,}".replace(
        ",",
        " "
    )

@dataclass
class MonitoringEntry:
    player_id: str
    nick: str
    activity: int
    game_total: int | None = None

    def __getitem__(self, key):
        """Dict-style compatibility for older monitoring integrations/tests."""
        if key == "player_id":
            return self.player_id
        if key == "nick":
            return self.nick
        if key == "activity":
            return self.activity
        if key == "game_total":
            return self.game_total
        raise KeyError(key)


def parse_monitoring_text(text: str):
    """Parse the strict VAKA_MONITORING_V1 payload.

    Format:
      VAKA_MONITORING_V1
      WEEK|YYYY-MM-DD
      PLAYER|UID|NICK|WEEK_ACTIVITY[|GAME_TOTAL]
      TOURNAMENT|TOURNAMENT_ID|UID|POINTS
      END

    GAME_TOTAL is informational only and is never used for bot lifetime activity.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or lines[0] != "VAKA_MONITORING_V1":
        return None, [], [], ["Не найден заголовок VAKA_MONITORING_V1."]
    week_start = None
    players = []
    tournaments = []
    errors = []
    ended = False
    seen_players = set()
    for idx, line in enumerate(lines[1:], start=2):
        if line == "END":
            ended = True
            continue
        parts = [x.strip() for x in line.split("|")]
        try:
            if parts[0] == "WEEK" and len(parts) == 2:
                week_start = parts[1]
                import datetime as _dt
                d = _dt.date.fromisoformat(week_start)
                if d.weekday() != 0:
                    raise ValueError("дата недели должна быть понедельником")
            elif parts[0] == "PLAYER" and len(parts) in (4, 5):
                uid = parts[1]
                if not uid.isdigit():
                    raise ValueError("UID должен содержать только цифры")
                nick = parts[2].strip()
                activity = clean_number(parts[3])
                game_total = clean_number(parts[4]) if len(parts) == 5 and parts[4] else None
                if not nick:
                    raise ValueError("пустой ник")
                if activity < 0:
                    raise ValueError("отрицательная активность")
                if uid in seen_players:
                    raise ValueError("UID повторяется")
                seen_players.add(uid)
                players.append(MonitoringEntry(uid, nick, activity, game_total))
            elif parts[0] == "TOURNAMENT" and len(parts) == 4:
                tid, uid = parts[1], parts[2]
                points = clean_number(parts[3])
                if not tid.isdigit() or not uid.isdigit() or points < 0:
                    raise ValueError("неверные данные турнира")
                tournaments.append((int(tid), uid, points))
            else:
                errors.append(f"Строка {idx}: неизвестная или неверная запись.")
        except (ValueError, TypeError) as exc:
            errors.append(f"Строка {idx}: {exc}")
    if not week_start:
        errors.append("Не указана WEEK|YYYY-MM-DD.")
    if not ended:
        errors.append("Не найден END.")
    if not players:
        errors.append("Нет ни одного PLAYER.")
    return week_start, players, tournaments, errors


def parse_monitoring_payload(text: str):
    """Backward-compatible name for the VAKA monitoring protocol parser.

    V6.8.4 uses :func:`parse_monitoring_text` internally, while older tests
    and integrations still import ``parse_monitoring_payload``. Keep both
    names available without changing the protocol or parsed data.
    """
    return parse_monitoring_text(text)


