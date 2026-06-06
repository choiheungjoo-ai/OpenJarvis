"""Newton data models.

Importing this package imports every model, so SQLAlchemy's metadata is
populated for ``Base.metadata.create_all()`` and Alembic autogen.

Public re-exports
-----------------
    Base                       — DeclarativeBase
    User, Persona, UserPersonaLink, ChatSession, Message
    RegistrationRequest, AuthAttempt
    GuestActivity
    SystemMetric, UserPattern, ProactiveNotification,
    ScreenCapture, CalendarEvent
    ToolPolicy
"""

from newton.models.auth_attempt import AuthAttempt
from newton.models.base import Base
from newton.models.calendar_event import CalendarEvent
from newton.models.chat_session import ChatSession
from newton.models.guest_activity import GuestActivity
from newton.models.message import Message
from newton.models.persona import Persona
from newton.models.proactive_notification import ProactiveNotification
from newton.models.registration_request import RegistrationRequest
from newton.models.screen_capture import ScreenCapture
from newton.models.system_metric import SystemMetric
from newton.models.tool_policy import ToolPolicy
from newton.models.user import User
from newton.models.user_pattern import UserPattern
from newton.models.user_persona_link import UserPersonaLink

__all__ = [
    "AuthAttempt",
    "Base",
    "CalendarEvent",
    "ChatSession",
    "GuestActivity",
    "Message",
    "Persona",
    "ProactiveNotification",
    "RegistrationRequest",
    "ScreenCapture",
    "SystemMetric",
    "ToolPolicy",
    "User",
    "UserPattern",
    "UserPersonaLink",
]
