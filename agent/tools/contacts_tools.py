from langchain_core.tools import tool
from agent.tools.confirmation import consume_tool_authorization

from ..services.contacts_service import (
    search_contacts as search_contacts_service,
    save_contact as save_contact_service,
)


@tool
def find_contact(query: str, limit: int = 10) -> dict:
    """Find contacts by name or any sequence of phone-number digits.

    If multiple matches are returned, ask the user which contact they mean.
    This tool does not place calls or send messages.
    """
    try:
        return search_contacts_service(query, limit)
    except (ValueError, RuntimeError) as error:
        return {"success": False, "matches": [], "count": 0, "message": str(error)}
    except Exception as error:
        return {
            "success": False,
            "matches": [],
            "count": 0,
            "message": f"Contact search failed ({type(error).__name__}).",
        }


@tool
def create_contact(
    name: str, phone: str, email: str = "", confirmed: bool = False
) -> dict:
    """Preview a contact and create it only after explicit user confirmation.

    First call with confirmed=False to show the exact name, phone, and optional
    email preview. Call again with confirmed=True only after the user approves
    that preview. This tool never contacts anyone.
    """
    try:
        confirmed = confirmed and consume_tool_authorization("create_contact")
        return save_contact_service(name, phone, email, confirmed)
    except (ValueError, RuntimeError) as error:
        return {
            "success": False,
            "created": False,
            "requires_confirmation": False,
            "message": str(error),
        }
    except Exception as error:
        return {
            "success": False,
            "created": False,
            "requires_confirmation": False,
            "message": f"Contact creation failed ({type(error).__name__}).",
        }


CONTACT_TOOLS = [find_contact, create_contact]