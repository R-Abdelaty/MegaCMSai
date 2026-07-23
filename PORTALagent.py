import getpass
import inspect
import json
import os
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

portal = GucPortal()
print("Logged in.")


def _portal_operations() -> tuple[str, ...]:
    """Return the safe, callable operations exposed by the portal client."""
    return tuple(
        name
        for name, method in inspect.getmembers(type(portal), predicate=callable)
        if not name.startswith("_")
    )


PORTAL_OPERATIONS = _portal_operations()


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


@tool
def available_seasons() -> str:
    """List only academic terms from the GUC portal that contain courses."""
    try:
        return api_response(
            "available_seasons",
            {"terms": _seasons_with_courses()},
        )
    except Exception as error:
        return api_response("available_seasons", {}, f"Could not retrieve terms: {error}")


@tool
def list_previous_courses(term: str) -> str:
    """List courses from a previous academic term, such as 'Winter 2024'."""
    try:
        code = next(
            (
                season_code
                for season_code, season_name in portal.available_seasons()
                if term.casefold() in season_name.casefold()
            ),
            None,
        )
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
                "term": term,
                "term_code": code,
                "courses": [
                    {"code": course_code, "name": course_name}
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
        grades = portal.get_grades_by_name(term, course_name)
        return api_response(
            "course_grades",
            {
                "course": grades.course,
                "term": grades.season,
                "items": [
                    {"assessment": item.assessment, "grade": item.grade}
                    for item in grades.items
                ],
            },
        )
    except Exception as error:
        return api_response(
            "course_grades",
            {},
            f"Could not retrieve grades for '{course_name}' in '{term}': {error}",
        )


@tool
def calculate_gpa(courses: list[dict[str, Any]]) -> str:
    """Calculate weighted GPA from course grade points and credit hours.

    Each course must include ``grade_point`` (for example 3.7) and ``credits``
    (for example 3). An optional ``course`` name is included in the response.
    Grade points must use the GPA scale chosen by the application, commonly 0-4.
    """
    try:
        if not courses:
            return api_response("gpa", {}, "Provide at least one course.")

        total_credits = 0.0
        total_quality_points = 0.0
        breakdown = []

        for index, course in enumerate(courses, start=1):
            grade_point = float(course["grade_point"])
            credits = float(course["credits"])
            if grade_point < 0 or credits <= 0:
                return api_response(
                    "gpa",
                    {},
                    f"Course {index} must have a non-negative grade point and positive credits.",
                )

            quality_points = grade_point * credits
            total_credits += credits
            total_quality_points += quality_points
            breakdown.append(
                {
                    "course": course.get("course", f"Course {index}"),
                    "grade_point": grade_point,
                    "credits": credits,
                    "quality_points": round(quality_points, 2),
                }
            )

        return api_response(
            "gpa",
            {
                "gpa": round(total_quality_points / total_credits, 2),
                "total_credits": total_credits,
                "total_quality_points": round(total_quality_points, 2),
                "courses": breakdown,
            },
        )
    except (KeyError, TypeError, ValueError) as error:
        return api_response(
            "gpa",
            {},
            "Each course needs numeric 'grade_point' and 'credits' values. "
            f"Details: {error}",
        )


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
you are a personal assistant that helps students in the guc. Ask for their name only in the
first message, then help with the content media system (cms) and portal information.
Never ask for a GUC/GIU username or password in chat: authentication has already completed
before the agent starts, using credentials stored locally in .env.
After a student gives their name, address them by that name naturally in your replies,
especially at the beginning of a response. Do not ask for their name again.
you can also help them with claculating their grades and also helping them  in sending 
emails through their emails, act friendly and happy to help always, dont use emojis alot 
maybe in the first message only .

Your responsibilities:
- find the course names, list them, get content from the files inside the cms
- get transcript by year, get grades based on course names , get all grades and 
  all of these are done on the portal

Portal access:
- The student is logged in before this agent starts. Use the `portal_action`
  tool whenever portal data is required.
- Use `available_seasons` when the student asks which academic terms are available.
- Use `list_previous_courses` to list courses from a specific previous term.
- Use `get_grades_by_name` to retrieve assessment grades for a named course and term.
- Use `calculate_gpa` when the student provides final course grade points and credits.
- Available portal operations: {portal_operations}

Rules:
-youre name is GU ASSISTANT
- Be clear and concise.
- Ask for missing information when it is needed.
- Only use tools when they help complete the user's request.
- be as friendly as possible
""".format(
    portal_operations=", ".join(PORTAL_OPERATIONS) or "none exposed by the portal client"
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
        calculate_gpa,
        portal_action,
    ],
    checkpointer=checkpointer,
)


def main() -> None:
    """Run an interactive conversation with the agent."""
    print("GUASSISTANT is ready for work. Type 'exit' or 'quit' to leave.")
    name = input("What is your name? ").strip()
    if name.lower() in {"exit", "quit"}:
        return
    if not name:
        name = "Student"

    greeting = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": f"My name is {name}. Please remember to address me by name.",
                }
            ]
        },
        config=thread_config,
    )
    print(f"\nGU ASSISTANT: {greeting['messages'][-1].content}\n")

    while True:
        user_message = input(f"{name}: ").strip()
        if user_message.lower() in {"exit", "quit"}:
            break
        if not user_message:
            continue

        result = agent.invoke(
            {"messages": [{"role": "user", "content": user_message}]},
            config=thread_config,
        )
        print(f"\nGU ASSISTANT: {result['messages'][-1].content}\n")


if __name__ == "__main__":
    main()
