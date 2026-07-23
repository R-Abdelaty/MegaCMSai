import getpass
import inspect
import json
import os
import re
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from dotenv import load_dotenv, set_key
from guc_portal import GucPortal
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain.tools import tool
from langgraph.checkpoint.memory import InMemorySaver


# Load API keys and portal credentials from .env.
ENV_FILE = Path(__file__).with_name(".env")
load_dotenv(ENV_FILE)

if not os.environ.get("GUC_USERNAME"):
    os.environ["GUC_USERNAME"] = input("GUC username: ")
    set_key(ENV_FILE, "GUC_USERNAME", os.environ["GUC_USERNAME"])
if not os.environ.get("GUC_PASSWORD"):
    os.environ["GUC_PASSWORD"] = getpass.getpass("GUC password: ")
    set_key(ENV_FILE, "GUC_PASSWORD", os.environ["GUC_PASSWORD"])


def _student_name_from_username(username: str) -> str:
    """Use the first part of the standard first-name.surname portal username."""
    first_name = username.strip().split(".", 1)[0].replace("_", " ").strip()
    return first_name.title() if first_name else "Student"


STUDENT_NAME = _student_name_from_username(os.environ["GUC_USERNAME"])
portal = GucPortal()


class _Style:
    """Small ANSI palette: works in modern Windows terminals without extras."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    MAGENTA = "\033[95m"
    DIM = "\033[2m"


FRANCO_LANGUAGE_INSTRUCTION = (
    "HARD RULE: Reply exclusively in Egyptian Franco using Latin/English "
    "characters only, for example: 'ezayak ya ... eh akhbarak?'. Arabic-script "
    "characters are NEVER allowed. If a Franco word is unclear or unknown, use "
    "the English word instead. Keep official course codes, semester labels, "
    "percentages, and numbers unchanged."
)
ENGLISH_LANGUAGE_INSTRUCTION = "Reply in clear, concise English."


def contains_arabic_script(text: str) -> bool:
    """Arabic-script characters are prohibited in every GU response."""
    return bool(re.search(r"[\u0600-\u06FF]", text))


def parse_language_prefixed_message(message: str) -> tuple[str | None, str]:
    """Extract the required leading `english` or `franco` language selector."""
    first_word, separator, remainder = message.strip().partition(" ")
    language = {
        "english": "english",
        "franco": "franco_egyptian",
    }.get(first_word.casefold())
    return language, remainder.strip() if separator else ""


def _assistant_message(content: str) -> None:
    """Render a clean, recognizable assistant reply in the terminal."""
    if contains_arabic_script(content):
        content = "Sorry, GU needs to rewrite that reply using English letters only. Try again."
    print(f"\n{_Style.CYAN}{_Style.BOLD}╭─ GU{_Style.RESET}")
    for line in content.strip().splitlines() or ["I am here to help."]:
        if line.startswith("### "):
            line = f"{_Style.BOLD}{_Style.GREEN}{line[4:]}{_Style.RESET}"
        else:
            line = line.replace("**", "")
        print(f"{_Style.CYAN}│{_Style.RESET} {line}")
    print(f"{_Style.CYAN}╰────────────────────────────────────────{_Style.RESET}\n")


print(f"{_Style.GREEN}{_Style.BOLD}✓ Portal login successful{_Style.RESET}")


def _portal_operations() -> tuple[str, ...]:
    """Return the safe, callable operations exposed by the portal client."""
    return tuple(
        name
        for name, method in inspect.getmembers(type(portal), predicate=callable)
        if not name.startswith("_")
    )


PORTAL_OPERATIONS = _portal_operations()


# Fixed assessment plans for the current semester. Keys are case-insensitive so
# the agent can translate a student's message into the assessments mapping.
COURSE_SCHEMES: dict[str, dict[str, Any]] = {
    "signals": {"credits": 6, "components": {
        "lab project": (10, None), "lab quizzes": (5, 1),
        "lab assignments": (5, 6), "assignments": (10, None),
        "quizzes": (10, 2), "midterm": (20, None), "final": (40, None),
    }},
    "electric circuits": {"credits": 6, "components": {
        "project": (5, None), "assignments": (10, 2), "quizzes": (10, 2),
        "labs": (15, None), "midterm": (20, None), "final": (40, None),
    }},
    "math": {"credits": 4, "components": {
        "assignments": (15, None), "quizzes": (15, 2), "midterm": (30, None),
        "final": (40, None),
    }},
    "cs": {"credits": 4, "components": {
        "project": (20, None), "project evaluation (quizzes)": (40, None),
        "midterm": (20, None), "final": (20, None),
    }},
    "computer organisation": {"credits": 4, "components": {
        "quizzes": (15, 2), "project": (15, None), "midterm": (25, None),
        "final": (45, None),
    }},
    "concepts": {"credits": 4, "components": {
        "lab tests": (5, None), "quizzes": (10, 2), "project": (20, None),
        "midterm": (25, None), "final": (40, None),
    }},
    "english rpw": {"credits": 1, "components": {
        "quizzes": (10, 1), "narrowing down assignment part 1": (2, None),
        "narrowing down assignment part 2": (3, None), "article review 1": (5, None),
        "article review 2": (10, None), "article review 3": (10, None),
        "literature review + group conference": (10, None), "midterm": (20, None),
        "final": (30, None),
    }},
    "english cps": {"credits": 1, "components": {
        "presentations": (30, None), "group discussion": (20, None),
        "midterm": (20, None), "final": (30, None),
    }},
}

GRADE_BANDS = (
    (94, "A+", 4.0), (90, "A", 4.0), (86, "A-", 3.7),
    (82, "B+", 3.3), (78, "B", 3.0), (74, "B-", 2.7),
    (70, "C+", 2.3), (65, "C", 2.0), (60, "C-", 1.7),
    (55, "D+", 1.3), (50, "D", 1.0), (0, "F", 0.0),
)

_seasons_have_been_shown = False
_semester_terms: list[dict[str, Any]] = []


def api_response(data_type: str, data: dict[str, Any], error: str | None = None) -> str:
    """Return a consistent JSON payload for the frontend."""
    return json.dumps(
        {
            "success": error is None,
            "type": data_type,
            "data": data if error is None else None,
            "error": error,
        },
        default=str,
        ensure_ascii=False,
    )


def _seasons_with_courses() -> list[dict[str, Any]]:
    """Return only portal terms that contain at least one course."""
    populated_seasons = []
    for code, name in portal.available_seasons():
        try:
            courses = list(portal.list_previous_courses(code))
        except Exception:
            # A term that cannot be read should not be displayed as available.
            continue

        if courses:
            populated_seasons.append(
                {"code": code, "name": name, "course_count": len(courses)}
            )
    return populated_seasons


def _grade_item_payload(item: Any) -> dict[str, Any]:
    """Attach a traffic-light status when a portal grade is a percentage."""
    payload = {"assessment": item.assessment, "grade": item.grade}
    try:
        numeric_grade = float(str(item.grade).rstrip("% "))
    except (TypeError, ValueError):
        return payload
    if 0 <= numeric_grade <= 100:
        color, status = _grade_status(numeric_grade)
        payload.update({
            "percentage": numeric_grade,
            "status_color": color,
            "status": status,
            "progress_bar": _progress_bar(color),
        })
    return payload


def _is_regular_semester(term_name: str) -> bool:
    """Winter and Spring are numbered; Summer and Fall retain their names."""
    name = term_name.casefold()
    return "winter" in name or "spring" in name


def _display_terms(terms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Give only Winter/Spring terms the student-friendly Semester N label."""
    numbered_semesters = 0
    displayed = []
    for term in terms:
        if _is_regular_semester(term["name"]):
            numbered_semesters += 1
            label = f"Semester {numbered_semesters}"
        else:
            label = term["name"]
        displayed.append({**term, "display_name": label})
    return displayed


def _semester_abbreviation(display_name: str) -> str:
    """Turn Semester 3 into S3; retain a compact meaningful Summer/Fall label."""
    name = " ".join(display_name.split())
    if name.casefold().startswith("semester "):
        return f"S{name.split()[-1]}"
    parts = name.split()
    if not parts:
        return "S"
    prefix = "SU" if parts[0].casefold().startswith("summer") else "F"
    year = parts[-1][-2:] if parts[-1].isdigit() and len(parts[-1]) == 4 else ""
    return f"{prefix}{year}"


def _course_label(
    course_name: str, semester_name: str, portal_course_code: str | None = None
) -> str:
    """Display the real portal course code, never an invented abbreviation."""
    semester_code = _semester_abbreviation(semester_name)
    if portal_course_code:
        return f"{course_name} ({portal_course_code} · {semester_code})"
    return f"{course_name} ({semester_code})"


def _course_match_score(
    query: str, course_name: str, portal_course_code: str, semester_name: str
) -> float:
    """Score an inexact request without ignoring an explicit course number."""
    candidate = " ".join(course_name.casefold().split())
    query_words = query.split()
    requested_number = int(query_words[-1]) if query_words and query_words[-1].isdigit() else None
    subject_words = query_words[:-1] if requested_number is not None else query_words
    subject_query = " ".join(subject_words) or query
    similarity = SequenceMatcher(None, subject_query, candidate).ratio()
    candidate_words = candidate.split()
    prefix_matches = sum(
        any(candidate_word.startswith(word) or word.startswith(candidate_word)
            for candidate_word in candidate_words)
        for word in subject_words
    )
    subject_score = max(similarity, prefix_matches / max(len(subject_words), 1))
    code_digits = "".join(character for character in portal_course_code if character.isdigit())
    if requested_number is not None:
        course_number_in_name = str(requested_number) in candidate.split()
        code_matches = code_digits.startswith(str(requested_number))
        semester_matches = _semester_abbreviation(semester_name) == f"S{requested_number}"
        if course_number_in_name or code_matches or semester_matches:
            # A matching course title, 101/201/301-style code, or Semester N
            # makes "Math N" a confident match.
            return max(subject_score, 0.95)
        # A subject-only match (Math vs Maths) is not enough when the student
        # explicitly asked for a numbered course.
        return min(subject_score, 0.8)
    return subject_score


def _semester_number(term_name: str) -> int | None:
    """Accept student shorthand such as S3, Sem3, Semester 3, or semester3."""
    compact = "".join(term_name.casefold().split())
    for prefix in ("semester", "sem", "s"):
        if compact.startswith(prefix):
            suffix = compact.removeprefix(prefix)
            return int(suffix) if suffix.isdigit() and int(suffix) > 0 else None
    return None


def _find_displayed_term(term_name: str) -> dict[str, Any] | None:
    """Find a portal term from either its real name or its Semester N shorthand."""
    requested = " ".join(term_name.casefold().split())
    semester_number = _semester_number(term_name)
    terms = _semester_terms or _seasons_with_courses()
    for term in _display_terms(terms):
        if semester_number and term["display_name"].casefold() == f"semester {semester_number}":
            return term
        if requested == term["display_name"].casefold() or requested in term["name"].casefold():
            return term
    return None


def _display_term_name(term_name: str) -> str:
    """Resolve a portal term name to its Semester N or Summer/Fall display name."""
    term = _find_displayed_term(term_name)
    return term["display_name"] if term else term_name


def _current_semester() -> dict[str, Any]:
    """The active term is the last portal term that contains courses."""
    terms = _seasons_with_courses()
    if not terms:
        raise ValueError("No course-containing semesters were found on the portal.")
    return _display_terms(terms)[-1]


@tool
def available_seasons() -> str:
    """List course-containing terms; codes appear only on the first request."""
    global _seasons_have_been_shown, _semester_terms
    try:
        _semester_terms = _seasons_with_courses()
        displayed_terms = _display_terms(_semester_terms)
        if not _seasons_have_been_shown:
            _seasons_have_been_shown = True
            return api_response(
                "available_seasons",
                {
                    "first_display": True,
                    "terms": [
                        {**term, "semester": term["display_name"]}
                        for term in displayed_terms
                    ],
                },
            )
        return api_response(
            "available_seasons",
            {
                "first_display": False,
                "terms": [
                    {"semester": term["display_name"],
                     "course_count": term["course_count"]}
                    for term in displayed_terms
                ],
            },
        )
    except Exception as error:
        return api_response("available_seasons", {}, f"Could not retrieve terms: {error}")


@tool
def list_previous_courses(term: str) -> str:
    """List courses from a named term or its Semester 1, Semester 2, etc. label."""
    try:
        global _semester_terms
        if not _semester_terms:
            _semester_terms = _seasons_with_courses()
        selected_term = _find_displayed_term(term)
        code = selected_term["code"] if selected_term else None
        display_term = term
        if selected_term:
            display_term = selected_term["display_name"]
        if not code:
            return api_response(
                "previous_courses",
                {},
                f"No term named '{term}' was found. Use available_seasons first.",
            )

        courses = list(portal.list_previous_courses(code))
        if not courses:
            return api_response(
                "previous_courses",
                {},
                f"The term '{term}' has no courses and is not displayed.",
            )

        return api_response(
            "previous_courses",
            {
                "term": display_term,
                "courses": [
                    {
                        "code": course_code,
                        "name": course_name,
                        "label": _course_label(course_name, display_term, course_code),
                    }
                    for course_code, course_name in courses
                ],
            },
        )
    except Exception as error:
        return api_response(
            "previous_courses", {}, f"Could not retrieve courses for '{term}': {error}"
        )


@tool
def get_grades_by_name(term: str, course_name: str) -> str:
    """Get assessment grades for a course in a named academic term."""
    try:
        matched_term = _find_displayed_term(term)
        portal_term = matched_term["name"] if matched_term else term
        display_term = matched_term["display_name"] if matched_term else term
        grades = portal.get_grades_by_name(portal_term, course_name)
        portal_course_code = None
        if matched_term:
            portal_course_code = next(
                (
                    code for code, name in portal.list_previous_courses(matched_term["code"])
                    if name.casefold() == grades.course.casefold()
                ),
                None,
            )
        return api_response(
            "course_grades",
            {
                "course": grades.course,
                "term": display_term,
                "course_label": _course_label(
                    grades.course, display_term, portal_course_code
                ),
                "items": [_grade_item_payload(item) for item in grades.items],
            },
        )
    except Exception as error:
        return api_response(
            "course_grades",
            {},
            f"Could not retrieve grades for '{course_name}' in '{term}': {error}",
        )


@tool
def get_course_grades_all_semesters(course_name: str) -> str:
    """Find a course and return its grades from every portal semester directly.

    Use this whenever a student names a course without naming a specific term.
    It searches every course-containing past semester and the current semester,
    so do not ask the student to choose a semester first.
    """
    try:
        needle = " ".join(course_name.casefold().split())
        all_course_records: list[dict[str, str]] = []
        for term in _display_terms(_seasons_with_courses()):
            season_code = term["code"]
            season_name = term["display_name"]
            try:
                available_courses = portal.list_previous_courses(season_code)
            except Exception:
                continue
            for course_code, matched_name in available_courses:
                all_course_records.append({
                    "semester": season_name,
                    "season_code": season_code,
                    "course": matched_name,
                    "course_code": course_code,
                    "source": "previous",
                })

        # The current term is not always included in the previous-grades list.
        try:
            current_display_name = _current_semester()["display_name"]
            for course_code, matched_name in portal.list_current_courses():
                all_course_records.append({
                    "semester": current_display_name,
                    "season_code": "",
                    "course": matched_name,
                    "course_code": course_code,
                    "source": "current",
                })
        except Exception:
            pass

        course_records = [
            record for record in all_course_records
            if needle in record["course"].casefold()
        ]
        if not course_records:
            suggested_records = [
                record for record in all_course_records
                if _course_match_score(
                    needle,
                    record["course"],
                    record["course_code"],
                    record["semester"],
                ) >= 0.5
            ]
            if suggested_records:
                suggested_records.sort(
                    key=lambda record: _course_match_score(
                        needle,
                        record["course"],
                        record["course_code"],
                        record["semester"],
                    ),
                    reverse=True,
                )
                best_score = _course_match_score(
                    needle,
                    suggested_records[0]["course"],
                    suggested_records[0]["course_code"],
                    suggested_records[0]["semester"],
                )
                if best_score >= 0.9:
                    # A numbered portal code (for example MATH301) is a clear
                    # enough match for a request such as "Math 3".
                    best_code = suggested_records[0]["course_code"]
                    course_records = [
                        record for record in all_course_records
                        if record["course_code"] == best_code
                    ]
                else:
                    return api_response(
                        "course_name_options",
                        {
                            "query": course_name,
                            "courses": list(dict.fromkeys(
                                _course_label(
                                    record["course"], record["semester"], record["course_code"]
                                ) for record in suggested_records
                            )),
                            "course_names": list(dict.fromkeys(
                                record["course"] for record in suggested_records
                            )),
                            "message": "I found similar course names. Please choose one.",
                        },
                    )
            if not course_records:
                return api_response(
                    "course_grades_all_semesters", {},
                    f"No course matching '{course_name}' was found in your portal semesters.",
                )

        # A precise match wins. Otherwise, do not guess between similarly named
        # courses such as "Math 1" and "Math 2".
        exact_records = [
            record for record in course_records
            if " ".join(record["course"].casefold().split()) == needle
        ]
        selected_records = exact_records or course_records
        options = sorted({record["course"] for record in selected_records})
        if not exact_records and len(options) > 1:
            return api_response(
                "course_name_options",
                {
                    "query": course_name,
                    "courses": sorted({
                        _course_label(
                            record["course"], record["semester"], record["course_code"]
                        )
                        for record in selected_records
                    }),
                    "course_names": options,
                    "message": "Please choose one of these course names.",
                },
            )

        results = []
        for record in selected_records:
            try:
                if record["source"] == "current":
                    grades = portal.get_current_grades(record["course_code"])
                else:
                    grades = portal.get_previous_grades(
                        record["season_code"], record["course_code"]
                    )
                results.append({
                    "semester": record["semester"],
                    "course": record["course"],
                    "course_label": _course_label(
                        record["course"], record["semester"], record["course_code"]
                    ),
                    "items": [_grade_item_payload(item) for item in grades.items],
                })
            except Exception:
                continue
        if not results:
            return api_response(
                "course_grades_all_semesters", {},
                f"'{options[0]}' was found, but its grades could not be retrieved right now.",
            )
        return api_response(
            "course_grades_all_semesters",
            {"course_query": course_name, "matches": results},
        )
    except Exception as error:
        return api_response(
            "course_grades_all_semesters", {},
            f"Could not retrieve grades for '{course_name}': {error}",
        )


def _grade_band(mark: float) -> tuple[str, float]:
    """Return the supplied percentage grade and its 4-point GPA equivalent."""
    for minimum, letter, point in GRADE_BANDS:
        if mark >= minimum:
            return letter, point
    raise ValueError("Marks must be between 0 and 100.")


def _grade_status(mark: float) -> tuple[str, str]:
    """Return a frontend-ready traffic-light status for an assessment average."""
    if mark >= 75:
        return "green", "good"
    if mark >= 60:
        return "yellow", "needs attention"
    return "red", "at risk"


def _progress_bar(status_color: str) -> str:
    """Return a chat-friendly traffic-light bar with a fixed visual meaning."""
    bars = {
        "green": "🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩",
        "yellow": "🟨🟨🟨🟨🟨⬜⬜⬜⬜⬜",
        "red": "🟥🟥⬜⬜⬜⬜⬜⬜⬜⬜",
    }
    return bars[status_color]


def _normalise_course_name(name: str) -> str:
    name = " ".join(name.casefold().split())
    aliases = {"computer organization": "computer organisation", "computer science": "cs"}
    return aliases.get(name, name)


@tool
def calculate_all_semesters_gpa(courses: list[dict[str, Any]]) -> str:
    """Calculate every semester GPA and the cumulative GPA from completed courses.

    Each course needs ``semester``, ``course``, and a final ``grade_point``
    (0-4) or ``final_mark`` (0-100). Supply ``credits`` unless the course is
    one of the fixed current-semester courses, whose credit hours are known.
    This tool is for completed courses from one or many semesters; it returns a
    GPA for every semester and a cumulative GPA. Ask for missing values before
    calling it rather than inventing them.
    """
    try:
        if not courses:
            return api_response("all_semesters_gpa", {}, "Provide completed courses first.")

        grouped: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"credits": 0.0, "quality_points": 0.0, "courses": []}
        )
        total_credits = 0.0
        total_quality_points = 0.0
        for index, course in enumerate(courses, start=1):
            semester = str(course["semester"]).strip()
            course_name = str(course["course"]).strip()
            if not semester or not course_name:
                raise ValueError(f"Course {index} needs both semester and course name.")

            if "final_mark" in course:
                final_mark = float(course["final_mark"])
                if not 0 <= final_mark <= 100:
                    raise ValueError(f"Course {index} final_mark must be between 0 and 100.")
                letter, grade_point = _grade_band(final_mark)
            elif "grade_point" in course:
                grade_point = float(course["grade_point"])
                if not 0 <= grade_point <= 4:
                    raise ValueError(f"Course {index} grade_point must be between 0 and 4.")
                final_mark = None
                letter = None
            else:
                raise ValueError(
                    f"Course {index} needs final_mark (0-100) or grade_point (0-4)."
                )

            known_course = COURSE_SCHEMES.get(_normalise_course_name(course_name))
            credits = float(course.get("credits", known_course["credits"] if known_course else 0))
            if credits <= 0:
                raise ValueError(
                    f"Course {index} needs positive credits; they are not known for '{course_name}'."
                )
            quality_points = grade_point * credits
            semester_data = grouped[semester]
            semester_data["credits"] += credits
            semester_data["quality_points"] += quality_points
            semester_data["courses"].append({
                "course": course_name,
                "course_label": _course_label(course_name, semester),
                "credits": credits,
                "final_mark": final_mark,
                "letter_grade": letter,
                "grade_point": grade_point,
            })
            total_credits += credits
            total_quality_points += quality_points

        semesters = []
        for semester, details in grouped.items():
            semesters.append({
                "semester": semester,
                "gpa": round(details["quality_points"] / details["credits"], 2),
                "credits": details["credits"],
                "courses": details["courses"],
            })
        return api_response(
            "all_semesters_gpa",
            {
                "semesters": semesters,
                "cumulative_gpa": round(total_quality_points / total_credits, 2),
                "total_credits": total_credits,
            },
        )
    except (KeyError, TypeError, ValueError) as error:
        return api_response("all_semesters_gpa", {}, f"Could not calculate GPA: {error}")


@tool
def calculate_gpa(semester: str, courses: list[dict[str, Any]]) -> str:
    """Calculate current marks and GPA using the fixed semester assessment plans.

    Ask the student for their current semester first. The active semester is
    determined from the portal as its last term that contains courses; do not
    use these fixed plans for another term. For each course, pass
    ``course`` and an ``assessments`` object whose keys are assessment names and
    values are percentages (0-100), or lists for repeated work. For example:
    {"course": "Signals", "assessments": {"quizzes": [70, 90, 80],
    "midterm": 75}}. Best-of rules are applied automatically. Credit hours are
    fixed by the plan. Incomplete courses receive a numerical current average
    and a green/yellow/red status, not a final GPA entry.
    """
    try:
        current_semester = _current_semester()
        submitted_semester = " ".join(semester.casefold().split())
        accepted_names = {
            current_semester["name"].casefold(),
            current_semester["display_name"].casefold(),
        }
        requested_number = _semester_number(semester)
        current_number = _semester_number(current_semester["display_name"])
        if submitted_semester not in accepted_names and not (
            requested_number is not None and requested_number == current_number
        ):
            return api_response(
                "gpa", {},
                "The current semester is the last course-containing portal term: "
                f"{current_semester['display_name']}. Please calculate for that term.",
            )
        if not courses:
            return api_response("gpa", {}, "Provide at least one course and its marks.")

        total_credits = 0.0
        total_quality_points = 0.0
        breakdown = []
        for index, course in enumerate(courses, start=1):
            course_name = str(course["course"])
            scheme = COURSE_SCHEMES.get(_normalise_course_name(course_name))
            if not scheme:
                return api_response(
                    "gpa", {},
                    f"'{course_name}' is not in the fixed semester course list.",
                )

            assessments = course.get("assessments")
            if not isinstance(assessments, dict):
                return api_response(
                    "gpa", {},
                    f"Provide an assessments object for '{course_name}'.",
                )

            submitted = {" ".join(str(key).casefold().split()): value
                         for key, value in assessments.items()}
            weighted_mark = 0.0
            completed_weight = 0.0
            missing = []
            for component, (weight, best_count) in scheme["components"].items():
                value = submitted.get(component)
                if value is None:
                    missing.append(component)
                    continue
                marks = value if isinstance(value, list) else [value]
                marks = [float(mark) for mark in marks]
                if not marks or any(mark < 0 or mark > 100 for mark in marks):
                    raise ValueError(f"'{component}' marks must be between 0 and 100.")
                selected = sorted(marks, reverse=True)[:best_count] if best_count else marks
                average = sum(selected) / len(selected)
                earned = weight * average / 100
                weighted_mark += earned
                completed_weight += weight

            current_average = weighted_mark / completed_weight * 100 if completed_weight else 0
            letter, grade_point = _grade_band(current_average)
            status_color, status = _grade_status(current_average)
            complete = not missing
            credits = float(scheme["credits"])
            entry = {
                "course": course_name,
                "course_label": _course_label(
                    course_name, current_semester["display_name"]
                ),
                "credits": credits,
                "earned_so_far": round(weighted_mark, 2),
                "completed_weight": completed_weight,
                "current_average": round(current_average, 2),
                "simple_calculation": (
                    f"{weighted_mark:.2f} earned points ÷ "
                    f"{completed_weight:.0f} completed points × 100 = "
                    f"{current_average:.2f}%"
                ) if completed_weight else "No marks have been entered yet.",
                "current_letter_grade": letter,
                "status_color": status_color,
                "status": status,
                "progress_bar": _progress_bar(status_color),
                "remaining_assessments": missing,
                "is_final": complete,
            }
            if complete:
                entry["grade_point"] = grade_point
                entry["quality_points"] = round(grade_point * credits, 2)
                total_credits += credits
                total_quality_points += grade_point * credits
            breakdown.append(entry)

        data: dict[str, Any] = {
            "semester": current_semester["display_name"],
            "portal_semester": current_semester["name"],
            "courses": breakdown,
            "status_legend": {
                "green": "75% or higher — good",
                "yellow": "60% to 74.99% — needs attention",
                "red": "below 60% — at risk",
            },
        }
        if total_credits:
            data.update({
                "final_courses_gpa": round(total_quality_points / total_credits, 2),
                "final_courses_credits": total_credits,
                "final_courses_quality_points": round(total_quality_points, 2),
            })
        else:
            data["final_courses_gpa"] = None
            data["note"] = "No course is complete yet; current averages are not final GPA values."
        return api_response("gpa", data)
    except (KeyError, TypeError, ValueError) as error:
        return api_response("gpa", {}, f"Could not calculate marks: {error}")


@tool
def portal_action(operation: str, arguments: dict[str, Any] | None = None) -> str:
    """Call an available GUC portal operation after login.

    Use an operation listed in the system instructions and pass its named
    parameters in ``arguments``. The stored portal session is reused, so users
    are not asked for their credentials again.
    """
    if operation not in PORTAL_OPERATIONS:
        return api_response("portal_action", {}, f"Unknown portal operation: {operation}.")

    method = getattr(portal, operation)
    try:
        result = method(**(arguments or {}))
        return api_response("portal_action", {"operation": operation, "result": result})
    except Exception as error:
        return api_response(
            "portal_action", {}, f"Portal operation '{operation}' failed: {error}"
        )

# Change this to the model/provider you want to use.
MODEL = "anthropic:claude-haiku-4-5"
llm = init_chat_model(MODEL)



SYSTEM_PROMPT = """
you are a personal assistant that helps students in the guc. The logged-in
student's first name is {student_name}, derived from their portal username in
the standard first-name.surname format. Address them naturally by that name;
never ask them for their name in chat.
Never ask for a GUC/GIU username or password in chat: authentication has already completed
before the agent starts, using credentials stored locally in .env.
you can also help them with claculating their grades and also helping them  in sending 
emails through their emails, act friendly and happy to help always, dont use emojis alot 
maybe in the first message only .

Your responsibilities:
- find the course names, list them, get content from the files inside the cms
- get transcript by year, get grades based on course names , get all grades and 
  all of these are done on the portal

When a student asks "what do you do?", "help", "features", or anything
similar, answer with this friendly product overview (adapt the greeting to
their name, but do not expose internal tools or JSON):

### Your GUC study companion

I can help you stay on top of your semester in one place:

- **Portal & courses** — find your available semesters, course names, and
  previous-course information. Winter and Spring are kept simple as Semester
  1, Semester 2, and so on; Summer and Fall keep their real names.
- **Grades made clear** — look up course grades and turn percentage results
  into an easy Green / Yellow / Red progress view with a visual bar.
- **Current-semester tracker** — calculate your grade so far, automatically
  apply best-quiz/best-assignment rules, show what still remains, and explain
  the calculation in plain language.
- **GPA planner** — calculate a completed semester GPA, compare several
  semesters, and see your cumulative GPA. I will ask for any missing marks or
  credit hours instead of guessing.
- **Study support** — help you find course material in the CMS and make sense
  of what to focus on next.

### Why use GU instead of only the portal?

The regular portal is where your official records live. GU makes
those records easier to use: you can ask in normal language instead of
searching through pages, understand your grade *so far* rather than seeing
separate marks, get best-of rules and GPA calculations done for you, and spot
which courses need attention through clear progress colors. It is your quick,
friendly layer on top of the official portal—not a replacement for official
results.

Finish with one warm, short invitation such as: "Tell me a course, semester,
or grade you would like to check." Keep this overview visually tidy and no
longer than these sections.

Do not show this overview at the start of a chat or volunteer it during normal
questions. Do not send a welcome message or opening question: the interface
already provides the input field. Respond only after the student sends a
message. By default, keep every answer to the direct result plus the next
needed action (usually one to three short sentences). Expand only when the
student asks for details, an explanation, help, features, or a breakdown.

Language:
- Every student message is prefixed with `english` or `franco`. That first word
  is only the language selector, not part of the student's request. Answer the
  remaining message in the selected language.
- Do not respond to the language selector by itself with a welcome or feature
  overview; ask only for the remaining request when it is missing.
- `english` is a rule to respond freely in English.
- `franco` is a HARD, NON-NEGOTIABLE RULE: respond exclusively in Egyptian
  Franco using Latin/English characters. NEVER output Arabic-script characters
  under any circumstance. Use natural phrasing such as "ezayak ya ... eh
  akhbarak?" If you do not know a word in Franco written with English letters,
  use its English equivalent. Keep official portal course codes, course labels,
  semester labels, percentages, and numbers exactly unchanged.

Portal access:
- The student is logged in before this agent starts. Use the `portal_action`
  tool whenever portal data is required.
- Use `available_seasons` when the student asks which academic terms are available.
  The first result contains portal codes and Semester 1, Semester 2, etc. labels.
  After that, call and refer to Winter/Spring terms only by their Semester label.
  Number only Winter and Spring terms. A Summer or Fall term appears only when
  the student has courses in it and must always use its real term name.
- Use `list_previous_courses` with a Semester label for Winter/Spring, or the
  real Summer/Fall term name when applicable.
- Treat `S3`, `Sem3`, `Semester3`, and `Semester 3` as the same semester.
  When a student uses one of these labels, resolve it directly; never ask them
  whether they mean Winter or Spring.
- Use `get_grades_by_name` to retrieve assessment grades for a named course and term.
- When a student asks about a specific course but does not give a term, call
  `get_course_grades_all_semesters` immediately. It searches all semesters and
  the current semester; never ask the student to choose a semester first.
  If it returns `course_name_options`, show the listed course names in a short
  numbered list and ask the student which one they mean. Never guess between
  similar course names. This includes similar spellings such as "Math 3" and
  "Mathematics 3". Recognize portal course-number patterns too: "Math 3" can
  mean a code such as MATH301, and "Circuits 2" can mean a code ending in 201.
  When that code or semester match is clear, use it directly rather than asking.
  If a requested number does not match, do not use a subject-only match; show
  the possible course labels and briefly state what is ambiguous.
  Whenever you show a course, use its `course_label` if available: it includes
  the full course name, its real portal course code, and the semester badge
  (for example, `Communication (COMM401 · S3)`). Never invent a course-code
  abbreviation such as SIG.
  Clearly show each returned percentage and its status color: green is good,
  yellow needs attention, and red is at risk.
- Before calculating marks, ensure you know the student's name; use it warmly in
  the reply. Ask for the course and any missing assessment marks. Credit hours
  are fixed in the calculation tool, but tell the student the course credit
  hours it reports. When the student supplies marks in a message, translate
  them into the `assessments` object expected by `calculate_gpa`; repeated marks
  such as quizzes must be passed as a list. Explain that `current_average` is
  the grade across work completed so far, while `earned_so_far` is its current
  contribution to the final course mark. Do not present an incomplete course as
  a final grade or include it in GPA.
- Before `calculate_gpa`, ask the student which semester is current. The fixed
  assessment rules apply only to the current portal term, which is the last
  semester containing courses. Do not guess or reuse them for another term.
  Always report the numerical current average and the green/yellow/red status
  for incomplete courses.
- Use `calculate_all_semesters_gpa` when the student wants a completed
  semester GPA, GPA across multiple semesters, or cumulative GPA. Ask for each
  missing final mark/grade point and credit hours instead of estimating them.
- When a student asks for GPA or a course calculation, give the simplest useful
  answer first: course name, current percentage, letter grade, color status,
  and the one-line `simple_calculation` returned by the tool. Do not dump JSON,
  assessment-by-assessment details, credit totals, or GPA internals unless the
  student specifically asks for them.
- Available portal operations: {portal_operations}

Rules:
- Your name is GU.
- Be clear and concise.
- Make every student-facing response easy to scan and pleasant to read. Use a
  short friendly heading when useful, blank lines between sections, and compact
  Markdown bullets. Use **bold** only for the most important number, course,
  or next action. Do not use tables for a single course or a small answer.
- For grade answers, use this visual order: course name, **percentage** and
  letter grade, the status word (Green / Yellow / Red), then the one-line
  calculation. On the next line, show the `progress_bar` exactly as returned
  by the tool. It is a visual status indicator, not the precise mark: green is
  a full bar, yellow is half full, and red is a short bar. State the next
  assessment only when it helps the student.
- Make grade answers feel like a friendly chatbot card. Use this compact form:
  `### Course name`, then `**78.5% · B · Green — Good**`, then the progress
  bar and a single calculation line. Keep emojis limited to the progress bar;
  do not add decorative emoji elsewhere.
- For term and course lists, use a numbered list with the Semester label and
  course count. Never expose technical JSON, tool payloads, portal codes after
  the first term display, or internal implementation details.
- Make grade explanations encouraging and fun: celebrate strong results with a
  brief upbeat line, and frame weaker results as a practical next step. Keep it
  genuine and specific to the numbers; never overdo emojis or make promises
  about a final grade that is not yet earned.
- Ask for missing information when it is needed.
- Only use tools when they help complete the user's request.
- be as friendly as possible
""".format(
    portal_operations=", ".join(PORTAL_OPERATIONS) or "none exposed by the portal client",
    student_name=STUDENT_NAME,
).strip()


# Keeps the conversation history for the same thread ID during this run.
checkpointer = InMemorySaver()
thread_config = {"configurable": {"thread_id": "cms-agent"}}

agent = create_agent(
    model=llm,
    system_prompt=SYSTEM_PROMPT,
    tools=[
        available_seasons,
        list_previous_courses,
        get_grades_by_name,
        get_course_grades_all_semesters,
        calculate_gpa,
        calculate_all_semesters_gpa,
        portal_action,
    ],
    checkpointer=checkpointer,
)


def main() -> None:
    """Run an interactive conversation with the agent."""
    print(
        f"\n{_Style.MAGENTA}{_Style.BOLD}╔════════════════════════════════════════╗\n"
        "║                 GU                     ║\n"
        f"╚════════════════════════════════════════╝{_Style.RESET}\n"
        f"{_Style.DIM}Your GUC portal companion • Type 'exit' or 'quit' to leave.{_Style.RESET}\n"
    )
    while True:
        user_message = input(f"{_Style.YELLOW}Input:{_Style.RESET} ").strip()
        if user_message.lower() in {"exit", "quit"}:
            break
        if not user_message:
            continue
        language, student_message = parse_language_prefixed_message(user_message)
        if language is None:
            _assistant_message("Start your message with english or franco, then write your request.")
            continue
        if not student_message:
            _assistant_message(
                "Ekteb el so2al." if language == "franco_egyptian"
                else "Enter your request after the language selector."
            )
            continue

        language_instruction = (
            FRANCO_LANGUAGE_INSTRUCTION
            if language == "franco_egyptian"
            else ENGLISH_LANGUAGE_INSTRUCTION
        )
        try:
            result = agent.invoke(
                {"messages": [{
                    "role": "user",
                    "content": (
                        f"[Language instruction: {language_instruction}]\n\n"
                        f"Student request: {student_message}"
                    ),
                }]},
                config=thread_config,
            )
            _assistant_message(result["messages"][-1].content)
        except Exception:
            _assistant_message("GU could not complete that request right now. Please try again.")


if __name__ == "__main__":
    main()
