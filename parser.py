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



@dataclass
class HumanMonitoringRow:
    name_or_id: str
    week_activity: int
    total_activity: int
    tournament_activity: int
    tournament_total: int


def looks_like_human_monitoring_list(text: str) -> bool:
    """Detect the five-column human monitoring list without stealing normal chat."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return False
    header = " ".join(lines[:2]).lower()
    header_markers = ("name/id", "name / id", "акт", "неделя", "тур")
    header_hint = sum(1 for marker in header_markers if marker in header) >= 2
    row_pattern = re.compile(r"^(.+?)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$")
    row_count = sum(bool(row_pattern.match(line)) for line in lines)
    # With a recognizable header one valid row is enough; without a header,
    # require at least two identical five-number rows to avoid false positives.
    return header_hint and row_count >= 1 or row_count >= 2


def parse_human_monitoring_list(text: str):
    """Parse the user-friendly activity list used by the monitoring screenshots.

    Accepted row:
      Vavix m? 3829 39000 260 780

    Columns:
      name/ID | weekly activity | total activity | tournament activity | tournament total

    Total/tournament totals are informational; only weekly activity is written
    to the weekly snapshot by the bot. This preserves the existing lifetime
    and coin safety rules.
    """
    if not looks_like_human_monitoring_list(text):
        return [], []
    rows = []
    errors = []
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    row_pattern = re.compile(r"^(.+?)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$")
    for idx, line in enumerate(lines, start=1):
        low = line.lower()
        if ("name/id" in low or "name / id" in low or ("акт" in low and "тур" in low)) and not row_pattern.match(line):
            continue
        match = row_pattern.match(line)
        if not match:
            errors.append(f"Строка {idx}: не распознана как строка мониторинга.")
            continue
        name_or_id = match.group(1).strip()
        if not name_or_id:
            errors.append(f"Строка {idx}: пустой name/ID.")
            continue
        try:
            values = [int(match.group(i).replace(" ", "")) for i in range(2, 6)]
        except ValueError:
            errors.append(f"Строка {idx}: неверные числовые значения.")
            continue
        if any(v < 0 for v in values):
            errors.append(f"Строка {idx}: значения не могут быть отрицательными.")
            continue
        rows.append(HumanMonitoringRow(name_or_id, *values))
    if not rows:
        errors.append("В списке не найдено ни одной строки игрока.")
    return rows, errors


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


